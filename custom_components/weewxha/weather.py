"""Weather platform for weewxha.

A single weather entity combining what the station measures now with the
National Weather Service's seven-day outlook, so Home Assistant's weather card
and anything that consumes forecasts get the data in the form they expect --
rather than as a wall of individual sensors.

The entity only appears when the feed carries an NWS forecast. Without one
there is nothing a weather entity can say that the observation sensors do not
already say better.
"""

from __future__ import annotations

from homeassistant.components.weather import (
    Forecast,
    WeatherEntity,
    WeatherEntityFeature,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import WeewxHaCoordinator
from .units import (
    HA_CONDITIONS,
    PRESSURE_UNITS,
    SPEED_UNITS,
    TEMPERATURE_UNITS,
)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    coordinator: WeewxHaCoordinator = hass.data[DOMAIN][entry.entry_id]
    added = False

    @callback
    def _discover() -> None:
        nonlocal added
        if added:
            return
        data = coordinator.data or {}
        if (data.get("nws") or {}).get("days"):
            added = True
            async_add_entities([WeewxHaWeather(coordinator, entry)])

    entry.async_on_unload(coordinator.async_add_listener(_discover))
    _discover()


class WeewxHaWeather(CoordinatorEntity[WeewxHaCoordinator], WeatherEntity):
    """Station observations now, NWS forecast ahead."""

    _attr_has_entity_name = True
    _attr_name = None  # the device name alone reads better on the card
    _attr_supported_features = WeatherEntityFeature.FORECAST_DAILY

    def __init__(self, coordinator: WeewxHaCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.entry_id}_weather"
        self._attr_device_info = DeviceInfo(identifiers={(DOMAIN, entry.entry_id)})

    # -- helpers ---------------------------------------------------------

    def _section(self, name: str) -> dict:
        return (self.coordinator.data or {}).get(name) or {}

    def _observation(self, field: str, unit_table: dict):
        """A current reading and the Home Assistant unit it is measured in.

        A value is only returned alongside a unit Home Assistant recognises.
        Reporting one without the other is rejected -- a number with no unit
        cannot be converted -- so an unmapped unit token yields nothing rather
        than an entity that raises on every update.
        """
        raw = self._section("current").get(field)
        if not isinstance(raw, dict):
            return None, None
        value = raw.get("value")
        if value is None:
            return None, None
        token = raw.get("unit")
        if unit_table:
            unit = unit_table.get(token)
            if unit is None:
                return None, None
            return value, unit
        # Unitless quantities, such as humidity as a bare percentage.
        return value, None

    # -- current conditions ----------------------------------------------

    @property
    def condition(self):
        """Mapped from the skin's own condition, which drives its glyph too."""
        raw = self._section("forecast").get("condition")
        if isinstance(raw, dict):
            return HA_CONDITIONS.get(raw.get("value"))
        return None

    @property
    def native_temperature(self):
        return self._observation("outTemp", TEMPERATURE_UNITS)[0]

    @property
    def native_temperature_unit(self):
        return self._observation("outTemp", TEMPERATURE_UNITS)[1]

    @property
    def humidity(self):
        return self._observation("outHumidity", {})[0]

    @property
    def native_pressure(self):
        return self._observation("barometer", PRESSURE_UNITS)[0]

    @property
    def native_pressure_unit(self):
        return self._observation("barometer", PRESSURE_UNITS)[1]

    @property
    def native_wind_speed(self):
        return self._observation("windSpeed", SPEED_UNITS)[0]

    @property
    def native_wind_speed_unit(self):
        return self._observation("windSpeed", SPEED_UNITS)[1]

    @property
    def wind_bearing(self):
        return self._observation("windDir", {})[0]

    @property
    def native_dew_point(self):
        return self._observation("dewpoint", TEMPERATURE_UNITS)[0]

    # -- forecast ---------------------------------------------------------

    @property
    def _days(self) -> list:
        return (self._section("nws") or {}).get("days") or []

    def _forecast(self) -> list[Forecast]:
        forecasts: list[Forecast] = []
        for day in self._days:
            if not isinstance(day, dict):
                continue
            entry: Forecast = {
                # The ISO string as the NWS issued it. Home Assistant's own
                # NWS integration passes startTime through unparsed, and the
                # Forecast type wants a string here, not a datetime.
                "datetime": day.get("start"),
                "condition": HA_CONDITIONS.get(day.get("condition")),
                "native_temperature": day.get("high"),
                "native_templow": day.get("low"),
                "precipitation_probability": day.get("precipitation"),
            }
            # The narrative the forecaster actually wrote, which the numbers
            # never quite capture.
            if day.get("detailed"):
                entry["detailed_description"] = day["detailed"]
            forecasts.append({k: v for k, v in entry.items() if v is not None})
        return forecasts

    async def async_forecast_daily(self) -> list[Forecast]:
        return self._forecast()

    @property
    def extra_state_attributes(self):
        """The whole forecast as prose, for notifications and announcements."""
        text = (self._section("nws") or {}).get("forecast_text")
        return {"forecast_text": text} if text else {}
