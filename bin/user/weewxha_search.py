"""Search list extension for the weewxha skin.

Provides these template tags to skins/weewxha/*.tmpl:

  $weewxha_generated_at   -- ISO 8601 timestamp string, computed once per run
  $hajson(value)          -- renders a raw observation value as a JSON scalar
                             literal (null for None, otherwise a plain number
                             or quoted string), so hand-written JSON templates
                             never emit invalid tokens like the Python string
                             "None".
  $weewxha_forecast       -- Zambretti forecast for the current conditions: a
                             dict of code/text/trend/delta keys (see
                             _blank_forecast below), with None for anything
                             that could not be computed.

Compatible with WeeWX 4.x and 5.x; both load search list extensions the same
way via the [CheetahGenerator] search_list_extensions option in skin.conf.
"""

import datetime
import json
import logging
import os
import time

import weewx.units
from weeutil.weeutil import list_as_string, to_bool, to_float, to_int
from weewx.cheetahgenerator import SearchList

from user.weewxha_forecast import (
    DEFAULT_BARO_LOWER,
    DEFAULT_BARO_UPPER,
    TREND_ARROWS,
    ZAMBRETTI_TEXTS,
    trend_state,
    zambretti_code,
    zambretti_text,
)
from user.weewxha_ha import (
    DEFAULT_TIMEOUT,
    HomeAssistantError,
    PressureHistory,
    fetch_humidity,
    fetch_pressure,
    fetch_temperature,
)
from user.weewxha_chart import Series, line_chart
from user.weewxha_history import ForecastHistory
from user.weewxha_icons import (
    condition_for_code,
    favicon_data_uri,
    moon_phase_name,
    moon_svg,
    condition_for_nws_icon,
    condition_label,
    icon_for_code,
    icon_svg,
)
from user.weewxha_nws import (
    ALERTS_TTL,
    DEFAULT_USER_AGENT,
    FORECAST_TTL,
    RADAR_CACHE_TTL,
    NwsClient,
    cache_radar_image,
    describe_age,
)

log = logging.getLogger(__name__)

# How far from the requested time an archive record may sit and still be used
# for the forecast. Generous enough to ride out a missed archive period without
# silently comparing pressures from hours away from where we asked.
RECORD_MAX_DELTA = 3600

DEFAULT_TREND_PERIOD = 10800  # 3 hours, the classic Zambretti trend window

# Where the forecast's pressure came from.
SOURCE_STATION = "station"
SOURCE_HOME_ASSISTANT = "homeassistant"

DEFAULT_HISTORY_FILE = "weewxha_pressure.json"
DEFAULT_NWS_CACHE = "weewxha_nws.json"
DEFAULT_FORECAST_HISTORY = "weewxha_forecast_history.json"

# How much archive history the charts cover, and how finely it is sampled.
CHART_SPAN = 86400
CHART_INTERVAL = 1800

# Charted unless [History] observations says otherwise. Deliberately a useful
# handful rather than everything the schema allows -- a wview_extended station
# reports thirty-odd types, and a wall of charts is harder to read than none.
DEFAULT_CHART_OBSERVATIONS = ("outTemp", "outHumidity", "barometer", "windSpeed", "rain")

# Averaging is right for most observations but wrong for a few: rain has to be
# totalled over each interval, and a gust is only interesting at its peak.
CHART_AGGREGATES = {"rain": "sum", "rainRate": "max", "windGust": "max"}

# Direction is circular, so an arithmetic mean of it is meaningless -- 350 and
# 10 degrees average to south. Refused rather than plotted wrongly.
CHART_EXCLUDED = {"windDir", "windGustDir"}

# How many decimals each kind of value is labelled with.
CHART_DECIMALS = {"barometer": 2, "rain": 2, "rainRate": 2, "UV": 1}


def hajson(value):
    """Render a raw scalar as a JSON literal (used inline in .tmpl files)."""
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return json.dumps(value)
    return json.dumps(str(value))


class WeewxHaSearchList(SearchList):
    def __init__(self, generator):
        super(WeewxHaSearchList, self).__init__(generator)

        forecast_dict = generator.skin_dict.get("Forecast", {})
        self.forecast_enabled = to_bool(forecast_dict.get("enable", True))
        self.trend_period = to_int(forecast_dict.get("trend_period", DEFAULT_TREND_PERIOD))
        self.baro_lower = to_float(forecast_dict.get("baro_lower", DEFAULT_BARO_LOWER))
        self.baro_upper = to_float(forecast_dict.get("baro_upper", DEFAULT_BARO_UPPER))
        self.data_binding = forecast_dict.get("data_binding", "wx_binding")

        # Per-letter text overrides, for translating or rewording the phrases.
        # ConfigObj splits values containing commas into lists, so rejoin them.
        self.texts = dict(ZAMBRETTI_TEXTS)
        for code, text in forecast_dict.get("Texts", {}).items():
            self.texts[code.strip().upper()] = list_as_string(text)

        self._configure_home_assistant(forecast_dict.get("HomeAssistant", {}))
        self._configure_nws(generator.skin_dict.get("NWS", {}))
        self._configure_history(generator.skin_dict.get("History", {}))

        # get_extension_list runs once per template, but the forecast only
        # changes once per report. Without this the skin would poll Home
        # Assistant -- and re-query the database -- once for every template.
        self._cache = {}

    def _configure_home_assistant(self, ha_dict):
        """Optional pressure source: a Home Assistant sensor entity."""
        self.ha_enabled = to_bool(ha_dict.get("enable", False))
        self.ha_url = ha_dict.get("url", "")
        self.ha_entity_id = ha_dict.get("barometer_entity_id", "").strip()
        self.ha_timeout = to_float(ha_dict.get("timeout", DEFAULT_TIMEOUT))
        self.ha_unit = ha_dict.get("unit") or None
        # Zambretti needs sea-level pressure. Many cheap sensors report the
        # absolute pressure where they sit, which at any altitude is lower --
        # about 29 hPa at 250 m -- and produces a confidently wrong forecast
        # with nothing on the page to reveal it.
        self.ha_pressure_type = (
            ha_dict.get("pressure_type", "sealevel") or "sealevel").strip().lower()
        self.ha_verify = to_bool(ha_dict.get("verify", True))
        self.ha_ca_file = ha_dict.get("ca_file", "").strip() or None

        # The token can live in weewx.conf, or -- better, since weewx.conf is
        # usually world-readable -- in a file of its own.
        self.ha_token = self._secret(ha_dict, "token")

        # Optional indoor readings, for a station with no console sensors.
        # Readings borrowed from Home Assistant, for a station missing the
        # sensor. Keyed by the observation they stand in for.
        self.ha_readings = {}
        for observation, option in (
            ("inTemp", "inside_temperature_entity_id"),
            ("inHumidity", "inside_humidity_entity_id"),
        ):
            entity = ha_dict.get(option, "").strip()
            if entity:
                self.ha_readings[observation] = entity
        self.ha_inside_unit = ha_dict.get("inside_unit", "").strip() or None
        self.ha_temperature_unit = (
            ha_dict.get("temperature_unit", "").strip() or self.ha_inside_unit)

        self.ha_history_file = ha_dict.get("history_file") or os.path.join(
            self._state_dir(), DEFAULT_HISTORY_FILE
        )
        # Keep enough history to cover the trend window with room to spare.
        self.ha_retention = to_int(ha_dict.get("retention", 2 * self.trend_period))

    def _configure_nws(self, nws_dict):
        """Optional: forecast, alerts and radar from the US National Weather Service."""
        self.nws_enabled = to_bool(nws_dict.get("enable", False))
        # Defaults to the station's own coordinates.
        self.nws_latitude = to_float(
            nws_dict.get("latitude", self.generator.stn_info.latitude_f))
        self.nws_longitude = to_float(
            nws_dict.get("longitude", self.generator.stn_info.longitude_f))
        self.nws_user_agent = list_as_string(
            nws_dict.get("user_agent", DEFAULT_USER_AGENT))
        self.nws_timeout = to_float(nws_dict.get("timeout", 15.0))
        self.nws_forecast_ttl = to_int(nws_dict.get("forecast_ttl", FORECAST_TTL))
        self.nws_alerts_ttl = to_int(nws_dict.get("alerts_ttl", ALERTS_TTL))
        self.nws_radar_station = nws_dict.get("radar_station", "").strip() or None
        # default  -- radar.weather.gov exactly as it comes, no settings
        #             imposed. What you get by visiting the site.
        # enhanced -- the local single-site view, centred on the station.
        #             Super-resolution reflectivity, which shows clear-air
        #             clutter on a quiet day.
        # standard -- the station's regional composite page.
        # image    -- the pre-rendered GIF loop, from the local cache.
        mode = (nws_dict.get("radar_mode", "default") or "").strip().lower()
        if mode == "interactive":       # the earlier name for the station page
            mode = "standard"
        self.nws_radar_mode = (
            mode if mode in ("default", "enhanced", "standard", "image") else "default"
        )
        self.nws_radar_height = to_int(nws_dict.get("radar_height", 460))
        # A local copy of the loop, so the radar still shows when the network
        # is down -- the only source that needs nothing beyond the web server
        # already serving this page.
        self.nws_radar_cache = to_bool(nws_dict.get("radar_cache", True))
        self.nws_radar_cache_ttl = to_int(nws_dict.get("radar_cache_ttl", RADAR_CACHE_TTL))
        # Map zoom for the enhanced view. 8 covers a metropolitan area.
        self.nws_radar_zoom = to_int(nws_dict.get("radar_zoom", 8))
        self.nws_cache_file = nws_dict.get("cache_file") or os.path.join(
            self._state_dir(), DEFAULT_NWS_CACHE
        )

    def _cache_radar(self, radar, now):
        """Store the loop beside the dashboard and describe the copy's age."""
        radar.update({"local_url": None, "cached_age": None,
                      "cached_label": None, "cache_fresh": None})
        if not self.nws_radar_cache:
            return

        filename = "%s_loop.gif" % radar["station"]
        destination = os.path.join(self._html_root(), "radar", filename)
        cached = cache_radar_image(
            radar["loop_url"],
            destination,
            self.nws_user_agent,
            timeout=self.nws_timeout,
            ttl=self.nws_radar_cache_ttl,
            now=now,
        )
        if not cached:
            return

        # Relative, so it works whatever hostname the dashboard is served on.
        radar["local_url"] = "radar/%s" % filename
        radar["cached_age"] = cached["age"]
        radar["cached_label"] = describe_age(cached["age"])
        radar["cache_fresh"] = cached["fresh"]

    def _html_root(self):
        """Where this report's files are written."""
        html_root = self.generator.skin_dict.get(
            "HTML_ROOT", self.generator.config_dict["StdReport"]["HTML_ROOT"])
        if os.path.isabs(html_root):
            return html_root
        return os.path.join(self.generator.config_dict["WEEWX_ROOT"], html_root)

    def _configure_history(self, history_dict):
        """Past forecasts and the history charts drawn from them."""
        self.history_enabled = to_bool(history_dict.get("enable", True))
        self.history_retention = to_int(history_dict.get("retention", 604800))
        self.chart_span = to_int(history_dict.get("chart_span", CHART_SPAN))
        self.chart_interval = to_int(history_dict.get("chart_interval", CHART_INTERVAL))

        observations = history_dict.get("observations", list(DEFAULT_CHART_OBSERVATIONS))
        if isinstance(observations, str):
            observations = [observations]
        self.chart_observations = [
            name.strip() for name in observations
            if name.strip() and name.strip() not in CHART_EXCLUDED
        ]
        self.history_file = history_dict.get("history_file") or os.path.join(
            self._state_dir(), DEFAULT_FORECAST_HISTORY
        )

    def _record_history(self, now, forecast):
        """Append this run's forecast and return the history."""
        history = ForecastHistory(self.history_file, retention=self.history_retention).load()
        if forecast.get("code"):
            history.add(
                now,
                code=forecast.get("code"),
                text=forecast.get("text"),
                condition=condition_for_code(forecast.get("code")),
                pressure=forecast.get("pressure"),
                trend=forecast.get("trend"),
                source=forecast.get("source"),
            )
            history.save()
        return history

    @staticmethod
    def _friendly_time(iso_timestamp):
        """An ISO 8601 stamp as a short local time, or None if unparseable."""
        if not iso_timestamp:
            return None
        text = str(iso_timestamp)
        # Python 3.6 cannot parse a trailing "Z"; normalise it.
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        try:
            moment = datetime.datetime.fromisoformat(text)
        except ValueError:
            return None
        if moment.tzinfo is not None:
            moment = moment.astimezone()
        return moment.strftime("%a %H:%M")

    @staticmethod
    def _with_labels(entries):
        """Add a human-readable time, so templates need no date handling."""
        labelled = []
        for entry in entries:
            copy = dict(entry)
            copy["when"] = time.strftime("%a %H:%M", time.localtime(entry["timestamp"]))
            labelled.append(copy)
        return labelled

    def _charts(self, now, db_manager, history):
        """SVG charts of where the station, Home Assistant and the forecast have been."""
        charts = {"items": [], "has_any": False}
        start = now - self.chart_span

        # Station observations come from WeeWX's own archive. An observation
        # the station doesn't record simply yields no points and no chart,
        # the same way it gets no entity in Home Assistant.
        for obs in self.chart_observations:
            points = self._archive_series(db_manager, obs, start, now)
            unit = self._display_unit(obs)
            svg = line_chart(
                Series(points, obs, "chart-line", CHART_DECIMALS.get(obs, 1)),
                unit=unit,
            )
            if svg:
                charts["items"].append({
                    "key": obs,
                    "title": self._observation_label(obs),
                    "svg": svg,
                    "unit": unit,
                    "points": len(points),
                })

        # The forecast's own pressure, which for a Home Assistant source never
        # reaches the archive at all.
        pressure_points = [(t, v) for t, v in history.series("pressure") if t >= start]
        svg = line_chart(
            Series(pressure_points, "forecast pressure", "chart-line-alt", 2),
            unit=self._display_unit("barometer"),
        )
        if svg:
            charts["items"].append({
                "key": "forecast_pressure",
                "title": "Forecast pressure",
                "svg": svg,
                "unit": self._display_unit("barometer"),
                "points": len(pressure_points),
            })

        charts["has_any"] = bool(charts["items"])
        return charts

    def _observation_label(self, obs_type):
        """The skin's own label for an observation, e.g. "Outside Temperature"."""
        try:
            return self.generator.skin_dict["Labels"]["Generic"].get(obs_type, obs_type)
        except (KeyError, TypeError):
            return obs_type

    def _archive_series(self, db_manager, obs_type, start, stop):
        """Downsampled (timestamp, value) pairs from the archive, in display units."""
        try:
            import weewx.xtypes
            from weeutil.weeutil import TimeSpan
            start_vt, stop_vt, value_vt = weewx.xtypes.get_series(
                obs_type, TimeSpan(start, stop), db_manager,
                aggregate_type=CHART_AGGREGATES.get(obs_type, "avg"),
                aggregate_interval=self.chart_interval,
            )
        except Exception as e:
            log.debug("weewxha: no series for %s: %s", obs_type, e)
            return []

        converted = self.generator.converter.convert(value_vt)
        points = []
        for timestamp, value in zip(stop_vt[0], converted[0]):
            if timestamp is None or value is None:
                continue
            points.append((int(timestamp), float(value)))
        return points

    def _display_unit(self, obs_type):
        """The unit label this skin shows `obs_type` in, as a reader sees it."""
        try:
            unit = self.generator.converter.getTargetUnit(obs_type)[0]
        except Exception:
            return ""
        try:
            # get_label_string returns a display label such as " \u00b0F".
            return self.generator.formatter.get_label_string(unit, plural=False).strip()
        except Exception:
            return unit

    def _borrowed(self):
        """Readings taken from Home Assistant to stand in for missing sensors.

        Reported in the skin's own units, so they sit alongside the station's
        own readings rather than in whatever Home Assistant happened to use.
        Each is independent: one entity failing does not cost the others.
        """
        borrowed = {}
        if not self.ha_enabled:
            return borrowed

        for observation, entity_id in self.ha_readings.items():
            humidity = observation.endswith("Humidity")
            try:
                if humidity:
                    value, unit, group = (
                        fetch_humidity(
                            self.ha_url, self.ha_token, entity_id,
                            timeout=self.ha_timeout,
                            verify=self.ha_verify, ca_file=self.ha_ca_file),
                        "percent", "group_percent",
                    )
                else:
                    value, unit = fetch_temperature(
                        self.ha_url, self.ha_token, entity_id,
                        timeout=self.ha_timeout, default_unit=self.ha_temperature_unit,
                        verify=self.ha_verify, ca_file=self.ha_ca_file)
                    group = "group_temperature"

                helper = weewx.units.ValueHelper(
                    weewx.units.ValueTuple(value, unit, group),
                    formatter=self.generator.formatter,
                    converter=self.generator.converter,
                )
                raw = helper.raw
                borrowed[observation] = {
                    "value": None if raw is None else round(raw, 2),
                    "unit": helper.value_t[1],
                    "formatted": str(helper),
                    "entity_id": entity_id,
                }
            except HomeAssistantError as e:
                log.warning("weewxha: no %s from Home Assistant: %s", observation, e)

        return borrowed

    def _almanac(self, now):
        """Time, date and the sun and moon for the station's location."""
        result = {
            "timestamp": int(now),
            "time": time.strftime("%H:%M", time.localtime(now)),
            "date": time.strftime("%A, %d %B %Y", time.localtime(now)),
            "sunrise": None, "sunset": None, "day_length": None,
            "moonrise": None, "moonset": None,
            "moon_phase": None, "moon_fullness": None, "moon_icon": None,
            "waxing": None,
        }
        try:
            import weewx.almanac
            info = self.generator.stn_info
            altitude = weewx.units.convert(info.altitude_vt, "meter")[0]
            almanac = weewx.almanac.Almanac(
                now, info.latitude_f, info.longitude_f, altitude=altitude,
                formatter=self.generator.formatter,
                converter=self.generator.converter,
            )

            rise, set_ = self._event_time(almanac, "sunrise"), self._event_time(almanac, "sunset")
            result["sunrise"], result["sunset"] = self._clock(rise), self._clock(set_)
            if rise and set_ and set_ > rise:
                minutes = int((set_ - rise) / 60)
                result["day_length"] = "%dh %02dm" % (minutes // 60, minutes % 60)

            fullness = getattr(almanac, "moon_fullness", None)
            phase_text = str(getattr(almanac, "moon_phase", "") or "")
            # The phase wording says which way it is going; there is no
            # separate flag for it.
            waxing = "decreasing" not in phase_text.lower()
            if fullness is not None:
                fullness = float(fullness)
                result["moon_fullness"] = round(fullness)
                result["waxing"] = waxing
                result["moon_phase"] = moon_phase_name(fullness, waxing)
                result["moon_icon"] = moon_svg(fullness, waxing, 46)

            # Only with pyephem installed.
            if getattr(almanac, "hasExtras", False):
                result["moonrise"] = self._clock(self._event_time(almanac.moon, "rise"))
                result["moonset"] = self._clock(self._event_time(almanac.moon, "set"))
        except Exception as e:
            log.error("weewxha: could not compute the almanac: %s", e)
        return result

    @staticmethod
    def _event_time(source, name):
        """The epoch time of an almanac event, or None."""
        try:
            value = getattr(source, name)
        except Exception:
            return None
        raw = getattr(value, "raw", value)
        try:
            return float(raw)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _clock(timestamp):
        if not timestamp:
            return None
        return time.strftime("%H:%M", time.localtime(timestamp))

    def _nws(self, now):
        """The NWS snapshot, or an empty one when disabled or unreachable."""
        blank = {"point": None, "days": [], "alerts": [], "radar": None,
                 "forecast_updated": None, "forecast_text": "", "narrative": [],
                 "stale": False,
                 "office": None, "pane_height": self.nws_radar_height}
        if not self.nws_enabled:
            return blank
        try:
            client = NwsClient(
                self.nws_latitude,
                self.nws_longitude,
                self.nws_cache_file,
                user_agent=self.nws_user_agent,
                timeout=self.nws_timeout,
                forecast_ttl=self.nws_forecast_ttl,
                alerts_ttl=self.nws_alerts_ttl,
                radar_station=self.nws_radar_station,
                condition_for_icon=condition_for_nws_icon,
                radar_zoom=self.nws_radar_zoom,
            )
            snapshot = client.snapshot(now)
            # The radar decides how tall the pane row is; the alerts list
            # scrolls within the same height rather than stretching past it.
            snapshot["pane_height"] = self.nws_radar_height
            if snapshot.get("radar"):
                snapshot["radar"]["mode"] = self.nws_radar_mode
                snapshot["radar"]["height"] = self.nws_radar_height
                snapshot["radar"]["embed_url"] = {
                    "enhanced": snapshot["radar"]["enhanced_url"],
                    "standard": snapshot["radar"]["page_url"],
                }.get(self.nws_radar_mode, snapshot["radar"]["default_url"])
                self._cache_radar(snapshot["radar"], now)
            for alert in snapshot.get("alerts") or []:
                alert["expires_label"] = self._friendly_time(alert.get("expires"))
                alert["effective_label"] = self._friendly_time(alert.get("effective"))
            return snapshot
        except Exception as e:
            # Same rule as the forecast: never cost the user their report.
            log.error("weewxha: could not fetch NWS data: %s", e)
            return blank

    @staticmethod
    def _secret(ha_dict, name):
        """Read `name` from config, or `name_file` if that's how it's stored.

        Keeping the token out of weewx.conf matters: it's usually world-readable.
        """
        value = ha_dict.get(name, "").strip()
        path = ha_dict.get("%s_file" % name, "").strip()
        if path:
            try:
                with open(path, "r") as fh:
                    return fh.read().strip()
            except OSError as e:
                log.error(
                    "weewxha: could not read %s_file %s: %s "
                    "(it must be readable by the user WeeWX runs as)",
                    name, path, e,
                )
                return ""
        return value

    def _state_dir(self):
        """A writable directory for our pressure history.

        Prefers wherever WeeWX already keeps its SQLite database, so this file
        sits with the rest of WeeWX's mutable state instead of in the middle
        of the configuration or the published HTML.
        """
        config_dict = self.generator.config_dict
        weewx_root = config_dict.get("WEEWX_ROOT", ".")
        try:
            sqlite_root = config_dict["DatabaseTypes"]["SQLite"]["SQLITE_ROOT"]
        except (KeyError, TypeError):
            return weewx_root
        return os.path.join(weewx_root, sqlite_root) if not os.path.isabs(sqlite_root) else sqlite_root

    def get_extension_list(self, timespan, db_lookup):
        generated_at = datetime.datetime.fromtimestamp(
            timespan.stop
        ).astimezone().isoformat()

        if timespan.stop not in self._cache:
            forecast = self._forecast(timespan, db_lookup)
            history = charts = None
            if self.history_enabled:
                try:
                    history = self._record_history(timespan.stop, forecast)
                    charts = self._charts(timespan.stop, db_lookup(self.data_binding), history)
                except Exception as e:
                    # History and charts are decoration; never lose the report.
                    log.error("weewxha: could not build history charts: %s", e)
            self._cache = {timespan.stop: {
                "forecast": forecast,
                "nws": self._nws(timespan.stop),
                "almanac": self._almanac(timespan.stop),
                "borrowed": self._borrowed(),
                "history": self._with_labels(history.recent(12)) if history else [],
                "changes": self._with_labels(history.changes("code", 8)) if history else [],
                "charts": charts or {"has_any": False, "items": []},
            }}
        cached = self._cache[timespan.stop]

        return [
            {
                "weewxha_generated_at": generated_at,
                "hajson": hajson,
                "weewxha_forecast": cached["forecast"],
                "weewxha_nws": cached["nws"],
                "weewxha_now": cached["almanac"],
                "weewxha_borrowed": cached["borrowed"],
                "weewxha_history": cached["history"],
                "weewxha_changes": cached["changes"],
                "weewxha_charts": cached["charts"],
                "weewxha_icon": icon_svg,
            }
        ]

    def _blank_forecast(self):
        """The shape every consumer sees, with nothing filled in."""
        return {
            "code": None,
            "text": None,
            "trend": None,
            "trend_arrow": None,
            "delta": None,
            "delta_unit": None,
            "delta_str": None,
            "pressure": None,
            "pressure_unit": None,
            "pressure_str": None,
            "source": None,
            "condition": None,
            "condition_label": None,
            "icon": None,
            "favicon": favicon_data_uri(None),
            "period_hours": round(self.trend_period / 3600.0, 2),
        }

    def _forecast(self, timespan, db_lookup):
        """Compute the Zambretti forecast for the end of the report timespan.

        Never raises: a station whose pressure history doesn't reach back far
        enough yet (or hardware with no barometer at all) gets a blank forecast
        and the rest of the report still generates.
        """
        forecast = self._blank_forecast()
        if not self.forecast_enabled:
            return forecast

        try:
            db_manager = db_lookup(self.data_binding)
            now = timespan.stop
            record = db_manager.getRecord(now, max_delta=RECORD_MAX_DELTA)

            # Pressure and trend must come from the same source, or the
            # reported change describes one sensor and the forecast another.
            source, pressure, rate, delta_hpa = self._pressure(now, record, db_manager)
            if pressure is None:
                log.debug("weewxha: no pressure reading; skipping forecast")
                return forecast

            forecast["source"] = source
            forecast.update(self._describe_pressure(pressure))
            if rate is not None:
                forecast.update(self._describe_trend(delta_hpa, rate))

            code = zambretti_code(
                pressure,
                rate,
                time.localtime(now).tm_mon,
                wind_dir=self._degrees(record, "windDir"),
                wind_speed=self._as_unit(record, "windSpeed", "meter_per_second"),
                north=self.generator.stn_info.latitude_f >= 0,
                baro_lower=self.baro_lower,
                baro_upper=self.baro_upper,
            )
            forecast["code"] = code
            forecast["text"] = zambretti_text(code, self.texts)
            forecast["condition"] = condition_for_code(code)
            forecast["condition_label"] = condition_label(forecast["condition"])
            forecast["icon"] = icon_for_code(code)
            forecast["favicon"] = favicon_data_uri(forecast["condition"])
        except Exception as e:
            # A broken forecast must not cost the user the whole report.
            log.error("weewxha: could not compute forecast: %s", e)
            return self._blank_forecast()

        return forecast

    def _pressure(self, now, record, db_manager):
        """Pick a pressure source and read it.

        Returns (source, pressure_hPa, rate_hPa_per_hour, delta_hPa); the rate
        and delta are None until there's enough history to measure them.

        Home Assistant wins when it's configured, since a station with its own
        barometer wouldn't be pointed at one. If that fetch fails the station
        barometer takes over, so a Home Assistant outage degrades the forecast
        instead of stopping it.
        """
        if self.ha_enabled:
            try:
                return self._ha_pressure(now, record, db_manager)
            except HomeAssistantError as e:
                log.warning("weewxha: %s; falling back to the station barometer", e)

        return self._station_pressure(now, record, db_manager)

    def _ha_pressure(self, now, record, db_manager):
        """Read the configured Home Assistant entity and trend its history."""
        pressure = fetch_pressure(
            self.ha_url,
            self.ha_token,
            self.ha_entity_id,
            timeout=self.ha_timeout,
            default_unit=self.ha_unit,
            verify=self.ha_verify,
            ca_file=self.ha_ca_file,
        )

        # Correct before storing, so the history and its trend are all one
        # kind of pressure.
        pressure = self._to_sea_level(pressure, record, db_manager, now)

        history = PressureHistory(
            self.ha_history_file, self.ha_entity_id, retention=self.ha_retention
        )
        history.load().add(now, pressure).save()

        rate = delta_hpa = None
        change = history.change(now, pressure, self.trend_period, RECORD_MAX_DELTA)
        if change is not None:
            delta_hpa, elapsed = change
            rate = delta_hpa / (elapsed / 3600.0)

        return SOURCE_HOME_ASSISTANT, pressure, rate, delta_hpa

    def _to_sea_level(self, pressure_hpa, record, db_manager, now):
        """Reduce an absolute reading to sea level, if it is one.

        Uses WeeWX's own conversion, so the result matches what WeeWX would
        derive for a station barometer at the same altitude.
        """
        if self.ha_pressure_type not in ("absolute", "station"):
            return pressure_hpa

        try:
            import weewx.uwxutils
            elevation = weewx.units.convert(
                self.generator.stn_info.altitude_vt, "meter")[0]
            if elevation is None:
                raise ValueError("station altitude is unknown")

            temperature = self._as_unit(record, "outTemp", "degree_C")
            if temperature is None:
                temperature = 15.0
            # The reduction wants a 12-hour mean as well as the current
            # reading; fall back to the current one when the archive can't
            # supply it.
            mean = self._mean_temperature(db_manager, now)
            if mean is None:
                mean = temperature
            humidity = record.get("outHumidity") if record else None
            if humidity is None:
                humidity = 50.0

            corrected = weewx.uwxutils.TWxUtils.StationToSeaLevelPressure(
                pressure_hpa, elevation, temperature, mean, float(humidity))
            log.debug("weewxha: reduced %.1f hPa at %.0f m to %.1f hPa at sea level",
                      pressure_hpa, elevation, corrected)
            return corrected
        except Exception as e:
            log.error("weewxha: could not reduce the pressure to sea level "
                      "(%s); using it uncorrected", e)
            return pressure_hpa

    def _mean_temperature(self, db_manager, now, hours=12):
        """Mean outside temperature in Celsius over the last `hours`."""
        try:
            import weewx.xtypes
            from weeutil.weeutil import TimeSpan
            value_t = weewx.xtypes.get_aggregate(
                "outTemp", TimeSpan(now - hours * 3600, now), "avg", db_manager)
            return weewx.units.convert(value_t, "degree_C")[0]
        except Exception:
            return None

    def _station_pressure(self, now, record, db_manager):
        """Read the station barometer and trend it from WeeWX's archive."""
        pressure = self._as_hpa(record, "barometer")
        if pressure is None:
            return SOURCE_STATION, None, None, None

        rate = delta_hpa = None
        then = db_manager.getRecord(now - self.trend_period, max_delta=RECORD_MAX_DELTA)
        past_pressure = self._as_hpa(then, "barometer")
        if past_pressure is not None:
            elapsed = record["dateTime"] - then["dateTime"]
            if elapsed > 0:
                delta_hpa = pressure - past_pressure
                rate = delta_hpa / (elapsed / 3600.0)

        return SOURCE_STATION, pressure, rate, delta_hpa

    def _describe_pressure(self, pressure_hpa):
        """Render the pressure the forecast used, in the skin's own units."""
        pressure = self._pressure_helper(pressure_hpa)
        raw = pressure.raw
        return {
            "pressure": None if raw is None else round(raw, 4),
            "pressure_unit": pressure.value_t[1],
            "pressure_str": str(pressure),
        }

    def _pressure_helper(self, value_hpa):
        return weewx.units.ValueHelper(
            weewx.units.ValueTuple(value_hpa, "mbar", "group_pressure"),
            formatter=self.generator.formatter,
            converter=self.generator.converter,
        )

    def _describe_trend(self, delta_hpa, rate):
        """Render the pressure change in the skin's configured pressure unit."""
        state = trend_state(rate)
        delta = self._pressure_helper(delta_hpa)
        raw = delta.raw
        return {
            "trend": state,
            "trend_arrow": TREND_ARROWS.get(state),
            "delta": None if raw is None else round(raw, 4),
            "delta_unit": delta.value_t[1],
            "delta_str": str(delta),
        }

    @staticmethod
    def _degrees(record, obs_type):
        """Compass directions are stored in degrees in every unit system."""
        if record is None:
            return None
        return record.get(obs_type)

    @staticmethod
    def _as_unit(record, obs_type, unit):
        """A record value converted to `unit`, or None if unavailable."""
        if record is None or record.get(obs_type) is None:
            return None
        value_t = weewx.units.as_value_tuple(record, obs_type)
        return weewx.units.convert(value_t, unit)[0]

    def _as_hpa(self, record, obs_type):
        # 1 mbar == 1 hPa, and 'mbar' is the token every WeeWX version knows.
        return self._as_unit(record, obs_type, "mbar")
