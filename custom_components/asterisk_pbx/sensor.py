from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.components.sensor import SensorEntity, SensorEntityDescription
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfTime
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import DOMAIN
from .coordinator import AsteriskCoordinator
from .entity import AsteriskEntity


@dataclass(frozen=True, kw_only=True)
class AsteriskSensorDescription(SensorEntityDescription):
    value_fn: Callable[[dict[str, Any]], Any]


DESCRIPTIONS = (
    AsteriskSensorDescription(key="version", name="Versão", icon="mdi:asterisk", value_fn=lambda d: d.get("version")),
    AsteriskSensorDescription(key="active_calls", name="Chamadas ativas", icon="mdi:phone-in-talk", value_fn=lambda d: d.get("active_calls", 0)),
    AsteriskSensorDescription(key="active_channels", name="Canais ativos", icon="mdi:call-split", value_fn=lambda d: d.get("active_channels", 0)),
    AsteriskSensorDescription(key="calls_processed", name="Chamadas processadas", icon="mdi:phone-log", value_fn=lambda d: d.get("calls_processed", 0)),
    AsteriskSensorDescription(key="extensions_total", name="Extensões", icon="mdi:phone-classic", value_fn=lambda d: d.get("extensions_total", 0)),
    AsteriskSensorDescription(key="extensions_registered", name="Extensões registadas", icon="mdi:phone-check", value_fn=lambda d: d.get("extensions_registered", 0)),
    AsteriskSensorDescription(key="extensions_unregistered", name="Extensões offline", icon="mdi:phone-off", value_fn=lambda d: d.get("extensions_unregistered", 0)),
    AsteriskSensorDescription(key="ivrs_total", name="IVRs", icon="mdi:menu", value_fn=lambda d: d.get("ivrs_total", 0)),
    AsteriskSensorDescription(key="ivrs_enabled", name="IVRs ativos", icon="mdi:menu-open", value_fn=lambda d: d.get("ivrs_enabled", 0)),
    AsteriskSensorDescription(key="ivr_active_channels", name="Canais em IVR", icon="mdi:account-voice", value_fn=lambda d: d.get("ivr_active_channels", 0)),
    AsteriskSensorDescription(key="sip_trunks_total", name="Trunks SIP", icon="mdi:transit-connection-variant", value_fn=lambda d: d.get("sip_trunks_total", 0)),
    AsteriskSensorDescription(key="gsm_dongles_total", name="Dongles GSM", icon="mdi:sim", value_fn=lambda d: d.get("gsm_dongles_total", 0)),
    AsteriskSensorDescription(key="gsm_dongles_connected", name="Dongles GSM ligados", icon="mdi:signal", value_fn=lambda d: d.get("gsm_dongles_connected", 0)),
    AsteriskSensorDescription(key="ht503_rtt", name="HT503 RTT", icon="mdi:timer-outline", native_unit_of_measurement=UnitOfTime.MILLISECONDS, value_fn=lambda d: (d.get("ht503") or {}).get("rtt_ms")),
    AsteriskSensorDescription(key="sipcord_rtt", name="SIPcord RTT", icon="mdi:timer-outline", native_unit_of_measurement=UnitOfTime.MILLISECONDS, value_fn=lambda d: (d.get("sipcord") or {}).get("rtt_ms")),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    coordinator: AsteriskCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(AsteriskSensor(coordinator, entry.entry_id, description) for description in DESCRIPTIONS)


class AsteriskSensor(AsteriskEntity, SensorEntity):
    entity_description: AsteriskSensorDescription

    def __init__(self, coordinator: AsteriskCoordinator, entry_id: str, description: AsteriskSensorDescription) -> None:
        super().__init__(coordinator, entry_id)
        self.entity_description = description
        self._attr_unique_id = f"{entry_id}_{description.key}"

    @property
    def native_value(self):
        return self.entity_description.value_fn(self.coordinator.data or {})

    @property
    def extra_state_attributes(self):
        data = self.coordinator.data or {}
        if self.entity_description.key == "gsm_dongles_total":
            return {"devices": data.get("gsm_dongles", [])}
        if self.entity_description.key == "extensions_total":
            return {"extensions": data.get("extensions", [])}
        if self.entity_description.key == "ivrs_total":
            return {"ivrs": data.get("ivrs", [])}
        return None
