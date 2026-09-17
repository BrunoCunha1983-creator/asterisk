from __future__ import annotations

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, CONF_PORT
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import AsteriskApi
from .const import CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL, DOMAIN, PLATFORMS
from .coordinator import AsteriskCoordinator

SERVICE_SEND_SMS = "send_sms"
SEND_SMS_SCHEMA = vol.Schema(
    {
        vol.Required("number"): cv.string,
        vol.Required("message"): cv.string,
        vol.Optional("gateway", default="auto"): vol.In(["auto", "usb_gsm", "sim800"]),
        vol.Optional("device", default=""): cv.string,
    }
)


async def _async_handle_send_sms(hass: HomeAssistant, call: ServiceCall) -> None:
    coordinators = hass.data.get(DOMAIN, {})
    if not coordinators:
        raise HomeAssistantError("Asterisk PBX não está configurado")

    coordinator = next(iter(coordinators.values()))
    try:
        result = await coordinator.api.async_send_sms(
            call.data["number"],
            call.data["message"],
            call.data.get("gateway", "auto"),
            call.data.get("device", ""),
        )
    except Exception as err:
        raise HomeAssistantError(f"Falha ao enviar SMS pelo Asterisk PBX: {err}") from err

    if not result.get("ok"):
        attempts = result.get("attempts") or []
        detail = str(result.get("output") or "Falha desconhecida")
        if attempts:
            summary = "; ".join(
                f"{item.get('gateway')}: {item.get('output') or 'falhou'}" for item in attempts
            )
            detail = summary or detail
        raise HomeAssistantError(f"SMS não enviado: {detail}")

    hass.async_create_task(coordinator.async_request_refresh())


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    session = async_get_clientsession(hass)
    api = AsteriskApi(session, entry.data[CONF_HOST], entry.data[CONF_PORT])
    coordinator = AsteriskCoordinator(
        hass,
        api,
        int(entry.data.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)),
    )
    await coordinator.async_config_entry_first_refresh()

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    if not hass.services.has_service(DOMAIN, SERVICE_SEND_SMS):
        async def handle_send_sms(call: ServiceCall) -> None:
            await _async_handle_send_sms(hass, call)

        hass.services.async_register(
            DOMAIN,
            SERVICE_SEND_SMS,
            handle_send_sms,
            schema=SEND_SMS_SCHEMA,
        )
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        hass.data.get(DOMAIN, {}).pop(entry.entry_id, None)
        if not hass.data.get(DOMAIN) and hass.services.has_service(DOMAIN, SERVICE_SEND_SMS):
            hass.services.async_remove(DOMAIN, SERVICE_SEND_SMS)
    return unloaded
