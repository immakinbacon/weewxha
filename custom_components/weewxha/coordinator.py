"""Data update coordinator for weewxha: polls the skin's weewxha.json feed."""

from __future__ import annotations

import asyncio
import logging
from datetime import timedelta

from aiohttp import ClientError
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

REQUEST_TIMEOUT = 15


class WeewxHaCoordinator(DataUpdateCoordinator[dict]):
    """Fetches and caches weewxha.json on a fixed interval."""

    def __init__(self, hass: HomeAssistant, url: str, scan_interval: int,
                 verify_ssl: bool = True) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(seconds=scan_interval),
        )
        self._url = url
        self._session = async_get_clientsession(hass, verify_ssl=verify_ssl)

    async def _async_update_data(self) -> dict:
        try:
            async with asyncio.timeout(REQUEST_TIMEOUT):
                response = await self._session.get(self._url)
                response.raise_for_status()
                return await response.json(content_type=None)
        except (ClientError, TimeoutError, ValueError) as err:
            raise UpdateFailed(f"Error fetching weewxha data from {self._url}: {err}") from err
