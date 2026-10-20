"""Forecast, alerts and radar from the US National Weather Service.

api.weather.gov needs no key, but it does require a User-Agent that identifies
you -- the NWS asks for an application name and contact address so they can
get in touch about traffic rather than simply blocking it.

Three things are fetched, on separate schedules because they change at very
different rates:

  * /points/{lat},{lon}   -- which office, grid square and radar cover this
                             location. Effectively static; cached for a week.
  * .../forecast          -- 14 periods (day and night) making up seven days.
                             The NWS regenerates these roughly hourly.
  * /alerts/active        -- watches, warnings and advisories in force now.
                             Refetched every report, since a tornado warning
                             half an hour stale is worse than none at all.

Everything is cached on disk. A fetch that fails falls back to the cached copy
however old it is, marked as stale, because a forecast from an hour ago beats
an empty panel. Only the US is covered; elsewhere this simply stays disabled.

Standard library only, so installing the skin doesn't drag in dependencies.
"""

import base64
import json
import logging
import os
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request

log = logging.getLogger(__name__)

API_ROOT = "https://api.weather.gov"

# Two ways to show a radar site, e.g. KDIX:
#   loop  -- a pre-rendered animated GIF. Light, but static imagery.
#   page  -- the NWS's own interactive viewer, which pans, zooms and animates.
#            It sets no X-Frame-Options or frame-ancestors, so it can be
#            embedded; verified by rendering it in a frame rather than by
#            reading the headers alone.
RADAR_LOOP_URL = "https://radar.weather.gov/ridge/standard/%s_loop.gif"
RADAR_PAGE_URL = "https://radar.weather.gov/station/%s/standard"
# The NWS's local single-site view -- super-resolution base reflectivity for
# one radar, rather than the regional composite the standard view shows. This
# is what weather.gov's own office pages link to as "Enhanced".
RADAR_ENHANCED_URL = "https://radar.weather.gov/station/%s/enhanced"
RADAR_SETTINGS_URL = "https://radar.weather.gov/?settings=v1_%s#/"
# The viewer with nothing imposed on it: whatever layer, framing and defaults
# the NWS currently ships. Dictating settings means tracking their choices
# forever and getting it subtly wrong in between.
RADAR_DEFAULT_URL = "https://radar.weather.gov/"

DEFAULT_RADAR_ZOOM = 7

DEFAULT_TIMEOUT = 15.0
DEFAULT_USER_AGENT = "weewxha weewx skin (set user_agent in weewx.conf)"

# Seconds before each kind of data is refetched.
POINT_TTL = 604800     # a week; the grid square for a location doesn't move
FORECAST_TTL = 1800    # half an hour; the NWS regenerates roughly hourly
ALERTS_TTL = 300       # every report cycle
RADAR_CACHE_TTL = 600  # the loop itself only regenerates every few minutes

# Severities the NWS uses, most serious first, for sorting and styling.
SEVERITY_ORDER = ("Extreme", "Severe", "Moderate", "Minor", "Unknown")


class NwsError(Exception):
    """Anything that stopped us getting data from the NWS."""


def _get_json(url, user_agent, timeout):
    """GET a JSON document, with the headers api.weather.gov expects."""
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": user_agent,
            # geo+json is what the API returns for most endpoints.
            "Accept": "application/geo+json,application/json;q=0.9",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        if e.code == 404:
            raise NwsError(
                "%s: not found (404). The NWS only covers the United States "
                "and its territories." % url
            )
        if e.code == 403:
            raise NwsError(
                "%s: forbidden (403). The NWS requires a User-Agent naming "
                "your application and a contact address." % url
            )
        raise NwsError("HTTP %s from %s" % (e.code, url))
    except urllib.error.URLError as e:
        raise NwsError("could not reach %s: %s" % (url, e.reason))
    except (ValueError, OSError) as e:
        raise NwsError("bad response from %s: %s" % (url, e))


def to_days(periods, condition_for_icon=None):
    """Fold the NWS's day/night periods into one entry per calendar day.

    The API alternates daytime and overnight periods, and which comes first
    depends on the time of day the forecast was issued. Pairing them gives the
    familiar high/low per day; a leading overnight period ("Tonight") becomes
    a day of its own with only a low.
    """
    days = []
    index = 0
    while index < len(periods):
        period = periods[index]
        precipitation = (period.get("probabilityOfPrecipitation") or {}).get("value")
        day = {
            "name": period.get("name"),
            "start": period.get("startTime"),
            "is_daytime": bool(period.get("isDaytime")),
            "unit": period.get("temperatureUnit"),
            "short": period.get("shortForecast"),
            "detailed": period.get("detailedForecast"),
            "precipitation": precipitation,
            "wind": " ".join(
                part for part in (period.get("windSpeed"), period.get("windDirection")) if part
            ),
            "icon": period.get("icon"),
            "condition": None,
            "high": None,
            "low": None,
        }
        if condition_for_icon is not None:
            day["condition"] = condition_for_icon(period.get("icon"))

        if period.get("isDaytime"):
            day["high"] = period.get("temperature")
            following = periods[index + 1] if index + 1 < len(periods) else None
            if following is not None and not following.get("isDaytime"):
                day["low"] = following.get("temperature")
                index += 2
            else:
                index += 1
        else:
            # An overnight period with no daytime ahead of it.
            day["low"] = period.get("temperature")
            index += 1

        days.append(day)
    return days


def centred_radar_url(latitude, longitude, zoom=DEFAULT_RADAR_ZOOM):
    """The default viewer, centred on a point.

    Only the centre and zoom are sent. Naming an agenda id changes which
    product is displayed even when no layer is given -- "local" forces the
    single-site super-resolution reflectivity, which is mostly clear-air
    clutter on a quiet day -- so the id is left out and the NWS's own default
    view survives. Verified by loading each variant and reading back which
    product the application reports.
    """
    settings = {"agenda": {"center": [float(longitude), float(latitude)],
                           "zoom": int(zoom)}}
    encoded = base64.urlsafe_b64encode(
        json.dumps(settings, separators=(",", ":")).encode("utf-8")
    ).decode("ascii").rstrip("=")
    return RADAR_SETTINGS_URL % encoded


def enhanced_radar_url(latitude, longitude, station, zoom=DEFAULT_RADAR_ZOOM,
                       animating=True):
    """The enhanced radar centred on a point, with no location selected.

    radar.weather.gov encodes its whole view state in one base64 parameter.
    The shape here is the one weather.gov's own office pages use: agenda "local"
    for a single site with super-resolution reflectivity, rather than the
    national mosaic.

    No location key is sent, which is how the app itself builds a station
    view. Setting one drops a pin and opens the "Weather for a location" panel
    over the map; leaving it out gives the radar alone, centred where asked.
    """
    # Mirrors how radar.weather.gov's own application builds its "Enhanced"
    # link, read out of its bundle, so the layer renders the way it does on
    # weather.gov. The one deliberate difference is the centre: the app uses
    # the radar site's coordinates, and we use the station's.
    #
    # transparent matters most. Without it the reflectivity layer is painted
    # opaque everywhere it has a value, including the clear-air return a
    # single site always sees, which covers the map in speckle instead of
    # showing weather over terrain.
    settings = {
        "agenda": {
            "id": "local",
            "center": [float(longitude), float(latitude)],
            "zoom": int(zoom),
            "filter": "WSR-88D",
            "layer": "sr_bref",
            "station": station,
            "transparent": True,
            "alertsOverlay": True,
            "stationIconsOverlay": True,
        },
        "animating": bool(animating),
        "base": "standard",
        "county": False,
        "cwa": False,
        "state": False,
        "menu": False,
        "shortFusedOnly": True,
        "opacity": {"alerts": 0.8, "local": 0.6, "localStations": 0.8, "national": 0.6},
    }
    encoded = base64.urlsafe_b64encode(
        json.dumps(settings, separators=(",", ":")).encode("utf-8")
    ).decode("ascii").rstrip("=")
    return RADAR_SETTINGS_URL % encoded


def to_forecast_text(periods):
    """The forecast as plain prose, the way the NWS writes it.

    The dashboard shows numbers and a glyph, but the narrative is what a
    forecaster actually wrote, and it is the form worth having for a
    notification, a spoken briefing, or anywhere a chart cannot go.
    """
    paragraphs = []
    for period in periods or []:
        name = period.get("name")
        detail = period.get("detailedForecast") or period.get("shortForecast")
        if name and detail:
            paragraphs.append("%s: %s" % (name, detail))
    return "\n\n".join(paragraphs)


def to_narrative(periods):
    """Each forecast period's own text, kept separate.

    to_days folds day and night together to give a high and a low, which
    throws away the overnight narrative. This keeps all fourteen, so a single
    period can be read on its own rather than sliced out of one long string.
    """
    narrative = []
    for period in periods or []:
        narrative.append({
            "name": period.get("name"),
            "start": period.get("startTime"),
            "end": period.get("endTime"),
            "is_daytime": bool(period.get("isDaytime")),
            "short": period.get("shortForecast"),
            "detailed": period.get("detailedForecast"),
            "temperature": period.get("temperature"),
            "unit": period.get("temperatureUnit"),
        })
    return narrative


def to_alerts(features):
    """Reduce alert features to the fields worth displaying, worst first."""
    alerts = []
    for feature in features or []:
        properties = feature.get("properties") or {}
        alerts.append({
            "id": properties.get("id"),
            "event": properties.get("event"),
            "severity": properties.get("severity"),
            "urgency": properties.get("urgency"),
            "certainty": properties.get("certainty"),
            "headline": properties.get("headline"),
            "area": properties.get("areaDesc"),
            "effective": properties.get("effective"),
            "expires": properties.get("expires"),
            "ends": properties.get("ends"),
            "description": properties.get("description"),
            "instruction": properties.get("instruction"),
            "url": properties.get("@id"),
        })

    def rank(alert):
        severity = alert.get("severity") or "Unknown"
        try:
            return SEVERITY_ORDER.index(severity)
        except ValueError:
            return len(SEVERITY_ORDER)

    alerts.sort(key=rank)
    return alerts


def cache_radar_image(url, destination, user_agent, timeout=DEFAULT_TIMEOUT,
                      ttl=RADAR_CACHE_TTL, now=None):
    """Keep a local copy of the radar loop, and report how old it is.

    The point is the offline case. The interactive viewer and the remote GIF
    both need the *viewer's* browser to reach the internet; a copy sitting in
    the same directory as the dashboard needs only the web server that is
    already serving the page. When the network is down, that copy is the only
    radar anyone is going to see.

    Returns a dict describing the local file, or None if there isn't one and
    we couldn't fetch it. `fresh` is False when this attempt failed and the
    file on disk is what was there before.
    """
    now = int(now if now is not None else time.time())

    existing = None
    try:
        existing = int(os.path.getmtime(destination))
    except OSError:
        pass

    if existing is not None and (now - existing) < ttl:
        return {"path": destination, "fetched": existing,
                "age": now - existing, "fresh": True}

    def keep_existing(problem):
        """Report the failure, and hold on to whatever is already on disk."""
        if existing is not None:
            log.warning("weewxha: %s; keeping the cached copy", problem)
            return {"path": destination, "fetched": existing,
                    "age": now - existing, "fresh": False}
        log.warning("weewxha: %s", problem)
        return None

    # Fetching and writing are reported separately. They fail for entirely
    # different reasons -- one is the network, the other is a directory the
    # WeeWX user cannot write to -- and a single message covering both sends
    # you looking at the wrong one.
    request = urllib.request.Request(url, headers={"User-Agent": user_agent})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = response.read()
        if not payload:
            raise NwsError("empty response")
    except (urllib.error.URLError, NwsError, OSError) as e:
        return keep_existing("could not fetch the radar image from %s: %s" % (url, e))

    directory = os.path.dirname(destination) or "."
    try:
        os.makedirs(directory, exist_ok=True)
        fd, tmp_path = tempfile.mkstemp(dir=directory, prefix=".weewxha-radar-", suffix=".tmp")
        try:
            with os.fdopen(fd, "wb") as fh:
                fh.write(payload)
            # mkstemp creates at 0600, but this one is served to browsers by
            # the web server, which runs as somebody else entirely.
            os.chmod(tmp_path, 0o644)
            os.replace(tmp_path, destination)
        except BaseException:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise
    except OSError as e:
        return keep_existing(
            "fetched the radar image but could not write %s: %s "
            "(that directory must be writable by the user WeeWX runs as)"
            % (destination, e)
        )

    return {"path": destination, "fetched": now, "age": 0, "fresh": True}


def describe_age(seconds):
    """A short human description of how old something is."""
    if seconds is None:
        return None
    if seconds < 90:
        return "just now"
    minutes = int(round(seconds / 60.0))
    if minutes < 60:
        return "%d minute%s ago" % (minutes, "" if minutes == 1 else "s")
    hours = seconds / 3600.0
    if hours < 24:
        rounded = int(round(hours))
        return "%d hour%s ago" % (rounded, "" if rounded == 1 else "s")
    days = int(round(hours / 24.0))
    return "%d day%s ago" % (days, "" if days == 1 else "s")


class NwsCache:
    """Disk cache keyed by document, each with its own age."""

    def __init__(self, path):
        self.path = path
        self.entries = {}

    def load(self):
        try:
            with open(self.path, "r") as fh:
                stored = json.load(fh)
            if isinstance(stored, dict):
                self.entries = stored
        except FileNotFoundError:
            pass
        except (ValueError, OSError) as e:
            log.warning("weewxha: ignoring unreadable NWS cache %s: %s", self.path, e)
        return self

    def get(self, key, ttl, now):
        """Return (data, is_stale), or (None, False) if nothing is cached."""
        entry = self.entries.get(key)
        if not entry or "data" not in entry:
            return None, False
        fetched = entry.get("fetched", 0)
        return entry["data"], (now - fetched) > ttl

    def set(self, key, data, now):
        self.entries[key] = {"fetched": now, "data": data}

    def save(self):
        directory = os.path.dirname(self.path) or "."
        try:
            os.makedirs(directory, exist_ok=True)
            fd, tmp_path = tempfile.mkstemp(dir=directory, prefix=".weewxha-nws-", suffix=".tmp")
            try:
                with os.fdopen(fd, "w") as fh:
                    json.dump(self.entries, fh)
                os.replace(tmp_path, self.path)
            except BaseException:
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass
                raise
        except OSError as e:
            log.warning("weewxha: could not write NWS cache %s: %s", self.path, e)
        return self


class NwsClient:
    """Fetches and caches the NWS documents the skin displays."""

    def __init__(self, latitude, longitude, cache_path, user_agent=DEFAULT_USER_AGENT,
                 timeout=DEFAULT_TIMEOUT, forecast_ttl=FORECAST_TTL, alerts_ttl=ALERTS_TTL,
                 radar_station=None, condition_for_icon=None,
                 radar_zoom=DEFAULT_RADAR_ZOOM):
        self.latitude = latitude
        self.longitude = longitude
        self.user_agent = user_agent or DEFAULT_USER_AGENT
        self.timeout = timeout
        self.forecast_ttl = forecast_ttl
        self.alerts_ttl = alerts_ttl
        self.configured_radar = radar_station
        # Injected so this module stays free of presentation concerns.
        self.condition_for_icon = condition_for_icon
        self.radar_zoom = radar_zoom
        self.cache = NwsCache(cache_path).load()

    def _cached(self, key, ttl, url, now):
        """Fetch `url`, or fall back to whatever is cached if that fails.

        Returns (data, stale). Stale data is still returned: an hour-old
        forecast is worth more than a blank panel.
        """
        cached, expired = self.cache.get(key, ttl, now)
        if cached is not None and not expired:
            return cached, False

        try:
            fresh = _get_json(url, self.user_agent, self.timeout)
            self.cache.set(key, fresh, now)
            return fresh, False
        except NwsError as e:
            if cached is not None:
                log.warning("weewxha: %s; using the cached copy", e)
                return cached, True
            log.warning("weewxha: %s", e)
            return None, False

    def snapshot(self, now=None):
        """Everything the dashboard and the feed need, in one call."""
        now = int(now if now is not None else time.time())
        result = {
            "point": None,
            "days": [],
            "alerts": [],
            "radar": None,
            "forecast_updated": None,
            "forecast_text": "",
            "narrative": [],
            "stale": False,
            "office": None,
        }

        point_url = "%s/points/%s,%s" % (API_ROOT, self.latitude, self.longitude)
        point, _ = self._cached("point", POINT_TTL, point_url, now)
        if not point:
            self.cache.save()
            return result

        properties = point.get("properties") or {}
        result["point"] = {
            "office": properties.get("gridId"),
            "radar_station": properties.get("radarStation"),
            "forecast_zone": properties.get("forecastZone"),
            "city": ((properties.get("relativeLocation") or {}).get("properties") or {}).get("city"),
            "state": ((properties.get("relativeLocation") or {}).get("properties") or {}).get("state"),
        }
        result["office"] = properties.get("gridId")

        station = self.configured_radar or properties.get("radarStation")
        if station:
            result["radar"] = {
                "station": station,
                "loop_url": RADAR_LOOP_URL % station,
                "page_url": RADAR_PAGE_URL % station,
                # Centred on the station's own coordinates rather than the
                # radar site, which can be tens of miles away.
                "enhanced_url": enhanced_radar_url(
                    self.latitude, self.longitude, station, self.radar_zoom),
                "station_url": RADAR_ENHANCED_URL % station,
                # The default view, centred on the station rather than
                # wherever the viewer's browser decides.
                "default_url": centred_radar_url(
                    self.latitude, self.longitude, self.radar_zoom),
                "plain_url": RADAR_DEFAULT_URL,
            }

        forecast_url = properties.get("forecast")
        if forecast_url:
            forecast, stale = self._cached("forecast", self.forecast_ttl, forecast_url, now)
            if forecast:
                forecast_properties = forecast.get("properties") or {}
                periods = forecast_properties.get("periods") or []
                result["days"] = to_days(periods, self.condition_for_icon)
                result["forecast_text"] = to_forecast_text(periods)
                result["narrative"] = to_narrative(periods)
                result["forecast_updated"] = forecast_properties.get("updateTime")
                result["stale"] = result["stale"] or stale

        alerts_url = "%s/alerts/active?point=%s,%s" % (
            API_ROOT, self.latitude, self.longitude
        )
        alerts, stale = self._cached("alerts", self.alerts_ttl, alerts_url, now)
        if alerts:
            result["alerts"] = to_alerts(alerts.get("features"))
            result["stale"] = result["stale"] or stale

        self.cache.save()
        return result
