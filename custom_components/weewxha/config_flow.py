"""Config flow for weewxha."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import voluptuous as vol
from aiohttp import ClientError
from homeassistant import config_entries
from homeassistant.const import CONF_SCAN_INTERVAL, CONF_URL
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import CONF_VERIFY_SSL, DEFAULT_SCAN_INTERVAL, DOMAIN

_LOGGER = logging.getLogger(__name__)

STEP_USER_DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_URL): str,
        vol.Optional(CONF_SCAN_INTERVAL, default=DEFAULT_SCAN_INTERVAL): vol.All(
            vol.Coerce(int), vol.Range(min=30)
        ),
        vol.Optional(CONF_VERIFY_SSL, default=True): bool,
    }
)


class CannotConnect(Exception):
    """Could not reach or parse the given URL."""


class InvalidData(Exception):
    """The URL responded but doesn't look like a weewxha feed."""


async def _validate_feed(hass, url: str, verify_ssl: bool = True) -> dict[str, Any]:
    session = async_get_clientsession(hass, verify_ssl=verify_ssl)
    try:
        async with asyncio.timeout(15):
            response = await session.get(url)
            response.raise_for_status()
            data = await response.json(content_type=None)
    except (ClientError, TimeoutError, ValueError) as err:
        raise CannotConnect from err

    if not isinstance(data, dict) or "current" not in data:
        raise InvalidData

    return data


class WeewxHaConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for weewxha."""

    VERSION = 1

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        errors: dict[str, str] = {}

        if user_input is not None:
            url = user_input[CONF_URL]
            try:
                data = await _validate_feed(
                    self.hass, url, user_input.get(CONF_VERIFY_SSL, True))
            except CannotConnect:
                errors["base"] = "cannot_connect"
            except InvalidData:
                errors["base"] = "invalid_data"
            else:
                await self.async_set_unique_id(url)
                self._abort_if_unique_id_configured()
                title = (data.get("station") or {}).get("name") or "WeeWX"
                return self.async_create_entry(title=title, data=user_input)

        return self.async_show_form(
            step_id="user", data_schema=STEP_USER_DATA_SCHEMA, errors=errors
        )
