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

GATEWAYS = ["auto", "usb_gsm", "sim800"]
FIXED_GATEWAYS = ["usb_gsm", "sim800"]

SERVICE_SEND_SMS = "send_sms"
SERVICE_SEND_USSD = "send_ussd"
SERVICE_SET_GSM_PRIORITY = "set_gsm_priority"

SEND_SMS_SCHEMA = vol.Schema(
    {
        vol.Required("number"): cv.string,
        vol.Required("message"): cv.string,
        vol.Optional("gateway", default="auto"): vol.In(GATEWAYS),
        vol.Optional("device", default=""): cv.string,
    }
)

SEND_USSD_SCHEMA = vol.Schema(
    {
        vol.Required("code"): cv.string,
        vol.Optional("gateway", default="auto"): vol.In(GATEWAYS),
        vol.Optional("device", default=""): cv.string,
    }
)

SET_GSM_PRIORITY_SCHEMA = vol.Schema(
    {
        vol.Required("sms_preferred", default="usb_gsm"): vol.In(FIXED_GATEWAYS),
        vol.Required("ussd_preferred", default="usb_gsm"): vol.In(FIXED_GATEWAYS),
        vol.Required("fallback", default=True): cv.boolean,
    }
)


def _first_coordinator(hass: HomeAssistant) -> AsteriskCoordinator:
    coordinators = hass.data.get(DOMAIN, {})
    if not coordinators:
        raise HomeAssistantError("Asterisk PBX não está configurado")
    return next(iter(coordinators.values()))


def _attempt_detail(result: dict) -> str:
    attempts = result.get("attempts") or []
    if attempts:
        return "; ".join(
            f"{item.get('gateway')}: {item.get('output') or 'falhou'}"
            for item in attempts
        )
    return str(result.get("output") or result.get("error") or "Falha desconhecida")


async def _async_handle_send_sms(hass: HomeAssistant, call: ServiceCall) -> None:
    coordinator = _first_coordinator(hass)
    try:
        result = await coordinator.api.async_send_sms(
            call.data["number"],
            call.data["message"],
            call.data.get("gateway", "auto"),
            call.data.get("device", ""),
        )
    except Exception as err:
        raise HomeAssistantError(
            f"Falha ao enviar SMS pelo Asterisk PBX: {err}"
        ) from err

    if not result.get("ok"):
        raise HomeAssistantError(f"SMS não enviado: {_attempt_detail(result)}")
    hass.async_create_task(coordinator.async_request_refresh())


async def _async_handle_send_ussd(hass: HomeAssistant, call: ServiceCall) -> None:
    coordinator = _first_coordinator(hass)
    try:
        result = await coordinator.api.async_send_ussd(
            call.data["code"],
            call.data.get("gateway", "auto"),
            call.data.get("device", ""),
        )
    except Exception as err:
        raise HomeAssistantError(
            f"Falha ao executar USSD pelo Asterisk PBX: {err}"
        ) from err

    if not result.get("ok"):
        raise HomeAssistantError(f"USSD falhou: {_attempt_detail(result)}")
    hass.async_create_task(coordinator.async_request_refresh())


async def _async_handle_set_gsm_priority(
    hass: HomeAssistant, call: ServiceCall
) -> None:
    coordinator = _first_coordinator(hass)
    try:
        result = await coordinator.api.async_set_gsm_priority(
            call.data["sms_preferred"],
            call.data["ussd_preferred"],
            call.data["fallback"],
        )
    except Exception as err:
        raise HomeAssistantError(
            f"Falha ao guardar prioridade GSM: {err}"
        ) from err

    if not result.get("ok"):
        raise HomeAssistantError(
            f"Prioridade GSM não guardada: {_attempt_detail(result)}"
        )
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

    if not hass.services.has_service(DOMAIN, SERVICE_SEND_USSD):
        async def handle_send_ussd(call: ServiceCall) -> None:
            await _async_handle_send_ussd(hass, call)

        hass.services.async_register(
            DOMAIN,
            SERVICE_SEND_USSD,
            handle_send_ussd,
            schema=SEND_USSD_SCHEMA,
        )

    if not hass.services.has_service(DOMAIN, SERVICE_SET_GSM_PRIORITY):
        async def handle_set_gsm_priority(call: ServiceCall) -> None:
            await _async_handle_set_gsm_priority(hass, call)

        hass.services.async_register(
            DOMAIN,
            SERVICE_SET_GSM_PRIORITY,
            handle_set_gsm_priority,
            schema=SET_GSM_PRIORITY_SCHEMA,
        )
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        hass.data.get(DOMAIN, {}).pop(entry.entry_id, None)
        if not hass.data.get(DOMAIN):
            for service in (
                SERVICE_SEND_SMS,
                SERVICE_SEND_USSD,
                SERVICE_SET_GSM_PRIORITY,
            ):
                if hass.services.has_service(DOMAIN, service):
                    hass.services.async_remove(DOMAIN, service)
    return unloaded
