"""Binary sensor platform for weewxha: battery/status flags from WeeWX."""

from __future__ import annotations

from homeassistant.components.binary_sensor import BinarySensorDeviceClass, BinarySensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, FIELD_LABELS
from .coordinator import WeewxHaCoordinator
from .units import BINARY_FIELDS

SECTION = "current"


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    coordinator: WeewxHaCoordinator = hass.data[DOMAIN][entry.entry_id]
    known: set[str] = set()

    @callback
    def _discover_new_entities() -> None:
        data = coordinator.data or {}
        new_entities = []
        for field in data.get(SECTION) or {}:
            if field not in BINARY_FIELDS or field in known:
                continue
            known.add(field)
            new_entities.append(WeewxHaBatteryStatus(coordinator, entry, field))
        if new_entities:
            async_add_entities(new_entities)

    entry.async_on_unload(coordinator.async_add_listener(_discover_new_entities))
    _discover_new_entities()


class WeewxHaBatteryStatus(CoordinatorEntity[WeewxHaCoordinator], BinarySensorEntity):
    """True (problem) when WeeWX reports a non-zero battery status flag."""

    _attr_has_entity_name = True
    _attr_device_class = BinarySensorDeviceClass.BATTERY

    def __init__(self, coordinator: WeewxHaCoordinator, entry: ConfigEntry, field: str) -> None:
        super().__init__(coordinator)
        self._field = field
        self._attr_unique_id = f"{entry.entry_id}_{SECTION}_{field}"
        self._attr_name = FIELD_LABELS.get(field, field)
        self._attr_device_info = DeviceInfo(identifiers={(DOMAIN, entry.entry_id)})

    @property
    def _raw(self) -> dict | None:
        data = self.coordinator.data or {}
        return (data.get(SECTION) or {}).get(self._field)

    @property
    def available(self) -> bool:
        return super().available and self._raw is not None

    @property
    def is_on(self) -> bool | None:
        raw = self._raw
        if raw is None or raw.get("value") is None:
            return None
        return bool(int(raw["value"]))
