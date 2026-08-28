"""Sensor platform for weewxha.

Entities are discovered dynamically from whatever fields actually appear in
weewxha.json, so a station without a UV or solar sensor simply doesn't get
those entities instead of showing them stuck at unavailable.
"""

from __future__ import annotations

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util

from .const import DOMAIN, FIELD_ICONS, FIELD_LABELS, MAX_STATE_LENGTH
from .coordinator import WeewxHaCoordinator
from .units import (
    BINARY_FIELDS,
    CM_SCALE_TOKENS,
    CURRENT_FIELD_SPECS,
    DAY_FIELD_SPECS,
    FIELD_OPTIONS,
    FORECAST_FIELD_SPECS,
)

SECTION_SPECS = {
    "current": CURRENT_FIELD_SPECS,
    "day": DAY_FIELD_SPECS,
    "forecast": FORECAST_FIELD_SPECS,
}


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    coordinator: WeewxHaCoordinator = hass.data[DOMAIN][entry.entry_id]
    known: set[tuple[str, str]] = set()

    @callback
    def _discover_new_entities() -> None:
        data = coordinator.data or {}
        new_entities = []
        for section, specs in SECTION_SPECS.items():
            for field, value in (data.get(section) or {}).items():
                # Sections also carry plain scalars (e.g. "dateTime"), which
                # aren't observations and have no unit to go with them.
                if not isinstance(value, dict):
                    continue
                if field in BINARY_FIELDS or (section, field) in known:
                    continue
                known.add((section, field))
                new_entities.append(
                    WeewxHaSensor(coordinator, entry, section, field, specs.get(field))
                )
        # The National Weather Service data is lists and prose rather than
        # readings, so it cannot come out of the loop above -- a forecast is
        # not a {value, unit} pair. Each gets a purpose-built entity.
        nws = data.get("nws") or {}
        # The alerts sensor exists whenever the NWS is configured at all, not
        # only when something is in force. An automation watching for "more
        # than zero alerts" needs an entity sitting at zero to watch; one that
        # blinks into existence with the first warning is no use.
        nws_active = bool(nws.get("days") or nws.get("alerts") or nws.get("radar"))
        for key, present, factory in (
            ("alerts", nws_active, lambda: WeewxHaAlerts(coordinator, entry)),
            ("forecast_text", bool(nws.get("days")),
             lambda: WeewxHaForecastText(coordinator, entry)),
            ("radar", bool(nws.get("radar")), lambda: WeewxHaRadar(coordinator, entry)),
        ):
            if present and ("nws", key) not in known:
                known.add(("nws", key))
                new_entities.append(factory())

        # When WeeWX last built the report, which is not the same as when we
        # last fetched it: a stalled skin keeps serving the same file happily,
        # and without this there is no way to see that from Home Assistant.
        if data.get("generated_at") and ("feed", "generated_at") not in known:
            known.add(("feed", "generated_at"))
            new_entities.append(WeewxHaGeneratedAt(coordinator, entry))

        if new_entities:
            async_add_entities(new_entities)

    entry.async_on_unload(coordinator.async_add_listener(_discover_new_entities))
    _discover_new_entities()


class WeewxHaSensor(CoordinatorEntity[WeewxHaCoordinator], SensorEntity):
    """A single WeeWX observation, numeric."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: WeewxHaCoordinator,
        entry: ConfigEntry,
        section: str,
        field: str,
        spec: tuple | None,
    ) -> None:
        super().__init__(coordinator)
        self._section = section
        self._field = field
        device_class, state_class, unit_table = spec or (None, None, {})
        self._unit_table = unit_table
        self._attr_device_class = device_class
        self._attr_state_class = state_class
        self._attr_options = FIELD_OPTIONS.get(field)
        self._attr_unique_id = f"{entry.entry_id}_{section}_{field}"
        self._attr_name = FIELD_LABELS.get(field, field)
        self._attr_icon = FIELD_ICONS.get(field)
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=entry.title,
            manufacturer="WeeWX",
            model="weewxha skin",
        )

    @property
    def _raw(self) -> dict | None:
        data = self.coordinator.data or {}
        return (data.get(self._section) or {}).get(self._field)

    @property
    def available(self) -> bool:
        return super().available and self._raw is not None

    @property
    def native_value(self):
        raw = self._raw
        if raw is None:
            return None
        value = raw.get("value")
        if value is not None and raw.get("unit") in CM_SCALE_TOKENS:
            value = value * 10
        return value

    @property
    def native_unit_of_measurement(self):
        raw = self._raw
        if raw is None:
            return None
        return self._unit_table.get(raw.get("unit"))


class WeewxHaGeneratedAt(CoordinatorEntity[WeewxHaCoordinator], SensorEntity):
    """When the skin generated the feed we are reading.

    The timestamp comes from the report cycle, so it also answers "is WeeWX
    still running?" -- an automation can compare it against now and complain
    when the feed stops moving, which a poll that keeps succeeding on a stale
    file will never reveal.
    """

    _attr_has_entity_name = True
    _attr_name = "Report Generated"
    _attr_icon = "mdi:clock-check-outline"
    _attr_device_class = SensorDeviceClass.TIMESTAMP

    def __init__(self, coordinator: WeewxHaCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.entry_id}_generated_at"
        self._attr_device_info = DeviceInfo(identifiers={(DOMAIN, entry.entry_id)})

    @property
    def native_value(self):
        raw = (self.coordinator.data or {}).get("generated_at")
        if not isinstance(raw, str):
            return None
        parsed = dt_util.parse_datetime(raw)
        if parsed is None:
            return None
        # The skin stamps local time with an offset. Should a feed ever arrive
        # without one, read it as the Home Assistant server's local time
        # rather than dropping the reading: a timestamp entity is rejected
        # outright if it is naive.
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=dt_util.DEFAULT_TIME_ZONE)
        return parsed


class WeewxHaNwsEntity(CoordinatorEntity[WeewxHaCoordinator], SensorEntity):
    """Shared plumbing for the National Weather Service entities."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: WeewxHaCoordinator, entry: ConfigEntry, key: str) -> None:
        super().__init__(coordinator)
        self._key = key
        self._attr_unique_id = f"{entry.entry_id}_nws_{key}"
        self._attr_device_info = DeviceInfo(identifiers={(DOMAIN, entry.entry_id)})

    @property
    def _nws(self) -> dict:
        return (self.coordinator.data or {}).get("nws") or {}


class WeewxHaAlerts(WeewxHaNwsEntity):
    """Active watches, warnings and advisories.

    The state is the count, so automations can trigger on "more than zero"
    without parsing anything; the alerts themselves are attributes, since a
    state is limited to 255 characters and a warning headline alone can
    exceed that.
    """

    _attr_name = "Weather Alerts"
    _attr_icon = "mdi:alert"
    _attr_native_unit_of_measurement = "alerts"

    def __init__(self, coordinator: WeewxHaCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry, "alerts")

    @property
    def native_value(self):
        return len(self._nws.get("alerts") or [])

    @property
    def extra_state_attributes(self):
        alerts = self._nws.get("alerts") or []
        # Worst first from the skin, so the head of the list is the one that
        # matters. Its details are hoisted alongside the full list: a
        # notification template wants "what should I do about this", and
        # reaching into alerts[0] for every field is both wordy and prone to
        # blowing up on an empty list.
        worst = alerts[0] if alerts else {}
        return {
            "alerts": alerts,
            "highest_severity": worst.get("severity"),
            "events": [a.get("event") for a in alerts],
            "event": worst.get("event"),
            "headline": worst.get("headline"),
            # The forecaster's full write-up, and the "what to do" that the
            # NWS attaches to it -- the part a spoken or pushed alert needs.
            "description": worst.get("description"),
            "instruction": worst.get("instruction"),
            "area": worst.get("area"),
            "urgency": worst.get("urgency"),
            "certainty": worst.get("certainty"),
            "effective": worst.get("effective"),
            "expires": worst.get("expires"),
            "ends": worst.get("ends"),
            # The skin's own rendering of those two ("6 PM", "Tue 9 AM"),
            # which reads better in a spoken alert than an ISO timestamp.
            "effective_label": worst.get("effective_label"),
            "expires_label": worst.get("expires_label"),
            "url": worst.get("url"),
        }


class WeewxHaForecastText(WeewxHaNwsEntity):
    """The forecast as the forecaster wrote it.

    The state holds the current period's narrative, truncated to what Home
    Assistant allows; the full text of every period is an attribute, which is
    what a notification or a spoken briefing wants.
    """

    _attr_name = "Forecast Text"
    _attr_icon = "mdi:text-long"

    def __init__(self, coordinator: WeewxHaCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry, "forecast_text")

    @property
    def _first_period(self) -> dict:
        days = self._nws.get("days") or []
        return days[0] if days and isinstance(days[0], dict) else {}

    @property
    def native_value(self):
        detail = self._first_period.get("detailed") or self._first_period.get("short")
        if not detail:
            return None
        if len(detail) <= MAX_STATE_LENGTH:
            return detail
        # Cut on a word boundary rather than mid-sentence.
        return detail[: MAX_STATE_LENGTH - 1].rsplit(" ", 1)[0] + "\u2026"

    @property
    def extra_state_attributes(self):
        # Every period separately as well as the whole thing, so a template
        # can pull out one night's forecast without splitting a long string.
        narrative = self._nws.get("narrative") or []
        return {
            "period": self._first_period.get("name"),
            "detailed": self._first_period.get("detailed"),
            "short": self._first_period.get("short"),
            "periods": narrative,
            "period_names": [p.get("name") for p in narrative],
            "forecast_text": self._nws.get("forecast_text"),
            "updated": self._nws.get("forecast_updated"),
            "office": self._nws.get("office"),
            "stale": self._nws.get("stale"),
        }


class WeewxHaRadar(WeewxHaNwsEntity):
    """The radar site covering the station, and where to see it."""

    _attr_name = "Radar"
    _attr_icon = "mdi:radar"

    def __init__(self, coordinator: WeewxHaCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry, "radar")

    @property
    def _radar(self) -> dict:
        radar = self._nws.get("radar")
        return radar if isinstance(radar, dict) else {}

    @property
    def native_value(self):
        return self._radar.get("station")

    @property
    def extra_state_attributes(self):
        radar = self._radar
        return {
            "mode": radar.get("mode"),
            "loop_url": radar.get("loop_url"),
            "page_url": radar.get("page_url"),
            "enhanced_url": radar.get("enhanced_url"),
            "entity_picture": radar.get("loop_url"),
            "cached_label": radar.get("cached_label"),
        }
