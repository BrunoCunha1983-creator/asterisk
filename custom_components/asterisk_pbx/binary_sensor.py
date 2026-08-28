from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.components.binary_sensor import BinarySensorDeviceClass, BinarySensorEntity, BinarySensorEntityDescription
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import DOMAIN
from .coordinator import AsteriskCoordinator
from .entity import AsteriskEntity


@dataclass(frozen=True, kw_only=True)
class AsteriskBinaryDescription(BinarySensorEntityDescription):
    value_fn: Callable[[dict[str, Any]], bool]


DESCRIPTIONS = (
    AsteriskBinaryDescription(
        key="online",
        name="PBX online",
        icon="mdi:server-network",
        device_class=BinarySensorDeviceClass.CONNECTIVITY,
        value_fn=lambda d: bool(d.get("online")),
    ),
    AsteriskBinaryDescription(
        key="ht503",
        name="HT503 FXO",
        icon="mdi:phone-incoming-outgoing",
        device_class=BinarySensorDeviceClass.CONNECTIVITY,
        value_fn=lambda d: bool((d.get("ht503") or {}).get("reachable")),
    ),
    AsteriskBinaryDescription(
        key="sipcord",
        name="SIPcord",
        icon="mdi:discord",
        device_class=BinarySensorDeviceClass.CONNECTIVITY,
        value_fn=lambda d: bool((d.get("sipcord") or {}).get("reachable")),
    ),
    AsteriskBinaryDescription(
        key="ivr_in_use",
        name="IVR em utilização",
        icon="mdi:account-voice",
        value_fn=lambda d: bool(d.get("ivr_in_use")),
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    coordinator: AsteriskCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(AsteriskStatusBinarySensor(coordinator, entry.entry_id, d) for d in DESCRIPTIONS)

    known_extensions: set[str] = set()
    known_ivrs: set[str] = set()

    @callback
    def add_dynamic_entities() -> None:
        new_entities = []
        for ext in (coordinator.data or {}).get("extensions", []):
            number = str(ext.get("extension") or "").strip()
            if number and number not in known_extensions:
                known_extensions.add(number)
                new_entities.append(AsteriskExtensionBinarySensor(coordinator, entry.entry_id, number))
        for ivr in (coordinator.data or {}).get("ivrs", []):
            ivr_id = str(ivr.get("id") or "").strip()
            if ivr_id and ivr_id not in known_ivrs:
                known_ivrs.add(ivr_id)
                new_entities.append(AsteriskIVRBinarySensor(coordinator, entry.entry_id, ivr_id))
        if new_entities:
            async_add_entities(new_entities)

    add_dynamic_entities()
    entry.async_on_unload(coordinator.async_add_listener(add_dynamic_entities))


class AsteriskStatusBinarySensor(AsteriskEntity, BinarySensorEntity):
    entity_description: AsteriskBinaryDescription

    def __init__(self, coordinator: AsteriskCoordinator, entry_id: str, description: AsteriskBinaryDescription) -> None:
        super().__init__(coordinator, entry_id)
        self.entity_description = description
        self._attr_unique_id = f"{entry_id}_{description.key}"

    @property
    def available(self) -> bool:
        if self.entity_description.key == "online":
            return True
        return super().available

    @property
    def is_on(self) -> bool:
        if self.entity_description.key == "online":
            return bool(self.coordinator.last_update_success and (self.coordinator.data or {}).get("online"))
        return self.entity_description.value_fn(self.coordinator.data or {})

    @property
    def extra_state_attributes(self):
        data = self.coordinator.data or {}
        if self.entity_description.key == "ht503":
            return data.get("ht503") or {}
        if self.entity_description.key == "sipcord":
            info = dict(data.get("sipcord") or {})
            info.pop("password", None)
            return info
        if self.entity_description.key == "ivr_in_use":
            return {"ivrs": data.get("ivrs", [])}
        return None


class AsteriskExtensionBinarySensor(AsteriskEntity, BinarySensorEntity):
    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY
    _attr_icon = "mdi:phone"

    def __init__(self, coordinator: AsteriskCoordinator, entry_id: str, extension: str) -> None:
        super().__init__(coordinator, entry_id)
        self.extension = extension
        self._attr_unique_id = f"{entry_id}_extension_{extension}"
        self._attr_name = f"Extensão {extension}"

    def _data(self) -> dict[str, Any]:
        for item in (self.coordinator.data or {}).get("extensions", []):
            if str(item.get("extension")) == self.extension:
                return item
        return {}

    @property
    def is_on(self) -> bool:
        return bool(self._data().get("registered"))

    @property
    def extra_state_attributes(self):
        item = dict(self._data())
        item.pop("registered", None)
        return item


class AsteriskIVRBinarySensor(AsteriskEntity, BinarySensorEntity):
    _attr_icon = "mdi:menu-open"

    def __init__(self, coordinator: AsteriskCoordinator, entry_id: str, ivr_id: str) -> None:
        super().__init__(coordinator, entry_id)
        self.ivr_id = ivr_id
        self._attr_unique_id = f"{entry_id}_ivr_{ivr_id}"

    def _data(self) -> dict[str, Any]:
        for item in (self.coordinator.data or {}).get("ivrs", []):
            if str(item.get("id")) == self.ivr_id:
                return item
        return {}

    @property
    def name(self) -> str:
        item = self._data()
        return f"IVR {item.get('name') or self.ivr_id}"

    @property
    def is_on(self) -> bool:
        return bool(self._data().get("active"))

    @property
    def extra_state_attributes(self):
        item = dict(self._data())
        item.pop("active", None)
        return item
