from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import AsteriskCoordinator


class AsteriskEntity(CoordinatorEntity[AsteriskCoordinator]):
    _attr_has_entity_name = True

    def __init__(self, coordinator: AsteriskCoordinator, entry_id: str) -> None:
        super().__init__(coordinator)
        self._entry_id = entry_id

    @property
    def device_info(self) -> DeviceInfo:
        version = str((self.coordinator.data or {}).get("version") or "Asterisk 22")
        return DeviceInfo(
            identifiers={(DOMAIN, self._entry_id)},
            name="Asterisk PBX",
            manufacturer="Asterisk / Home Assistant Add-on",
            model="Asterisk 22 PBX + GSM",
            sw_version=version,
        )
