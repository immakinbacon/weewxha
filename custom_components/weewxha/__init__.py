"""The weewxha integration: Home Assistant entities from a WeeWX weewxha.json feed."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_SCAN_INTERVAL, CONF_URL, Platform
from homeassistant.core import HomeAssistant

from .const import CONF_VERIFY_SSL, DEFAULT_SCAN_INTERVAL, DOMAIN
from .coordinator import WeewxHaCoordinator

PLATFORMS = [Platform.SENSOR, Platform.BINARY_SENSOR, Platform.WEATHER]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    scan_interval = entry.data.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)
    coordinator = WeewxHaCoordinator(
        hass,
        entry.data[CONF_URL],
        scan_interval,
        verify_ssl=entry.data.get(CONF_VERIFY_SSL, True),
    )
    await coordinator.async_config_entry_first_refresh()

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id)
    return unload_ok
