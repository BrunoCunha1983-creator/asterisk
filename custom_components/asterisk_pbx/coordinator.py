from __future__ import annotations

from datetime import timedelta

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import AsteriskApi, AsteriskApiError


class AsteriskCoordinator(DataUpdateCoordinator[dict]):
    def __init__(self, hass: HomeAssistant, api: AsteriskApi, scan_interval: int) -> None:
        super().__init__(
            hass,
            logger=__import__("logging").getLogger(__name__),
            name="Asterisk PBX",
            update_interval=timedelta(seconds=max(5, int(scan_interval))),
        )
        self.api = api

    async def _async_update_data(self) -> dict:
        try:
            return await self.api.async_get_state()
        except AsteriskApiError as err:
            raise UpdateFailed(f"Asterisk add-on unavailable: {err}") from err
