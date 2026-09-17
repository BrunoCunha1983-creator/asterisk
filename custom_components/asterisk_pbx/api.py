from __future__ import annotations

from typing import Any

from aiohttp import ClientError, ClientSession, ClientTimeout


class AsteriskApiError(Exception):
    """Raised when the Asterisk add-on API cannot be reached or parsed."""


class AsteriskApi:
    def __init__(self, session: ClientSession, host: str, port: int) -> None:
        self._session = session
        self._host = host.strip().rstrip("/")
        self._port = int(port)

    @property
    def base_url(self) -> str:
        host = self._host
        if host.startswith("http://") or host.startswith("https://"):
            if "://" in host and host.rsplit(":", 1)[-1].isdigit():
                return host
            return f"{host}:{self._port}"
        return f"http://{host}:{self._port}"

    async def _async_request(
        self,
        method: str,
        path: str,
        *,
        payload: dict[str, Any] | None = None,
        allow_http_error: bool = False,
    ) -> dict[str, Any]:
        url = f"{self.base_url}{path}"
        try:
            async with self._session.request(
                method,
                url,
                json=payload,
                timeout=ClientTimeout(total=35),
            ) as response:
                try:
                    data = await response.json(content_type=None)
                except ValueError as err:
                    raise AsteriskApiError(f"Resposta JSON inválida de {url}") from err
                if response.status >= 400 and not allow_http_error:
                    detail = ""
                    if isinstance(data, dict):
                        detail = str(
                            data.get("output") or data.get("error") or ""
                        ).strip()
                    suffix = f": {detail}" if detail else ""
                    raise AsteriskApiError(
                        f"HTTP {response.status} de {url}{suffix}"
                    )
        except (ClientError, TimeoutError) as err:
            raise AsteriskApiError(str(err)) from err

        if not isinstance(data, dict):
            raise AsteriskApiError("Resposta JSON inválida")
        data.setdefault("http_status", response.status)
        return data

    async def async_get_state(self) -> dict[str, Any]:
        return await self._async_request("GET", "/api/ha-state")

    async def async_get_pbx(self) -> dict[str, Any]:
        return await self._async_request("GET", "/api/pbx")

    async def async_get_gsm_status(self) -> dict[str, Any]:
        return await self._async_request("GET", "/api/gsm/status")

    async def async_send_sms(
        self,
        number: str,
        message: str,
        gateway: str = "auto",
        device: str = "",
    ) -> dict[str, Any]:
        return await self._async_request(
            "POST",
            "/api/gsm/sms",
            payload={
                "number": str(number or ""),
                "message": str(message or ""),
                "gateway": str(gateway or "auto"),
                "device": str(device or ""),
            },
            allow_http_error=True,
        )

    async def async_send_ussd(
        self,
        code: str,
        gateway: str = "auto",
        device: str = "",
    ) -> dict[str, Any]:
        return await self._async_request(
            "POST",
            "/api/gsm/ussd",
            payload={
                "code": str(code or ""),
                "gateway": str(gateway or "auto"),
                "device": str(device or ""),
            },
            allow_http_error=True,
        )

    async def async_set_gsm_priority(
        self,
        sms_preferred: str,
        ussd_preferred: str,
        fallback: bool,
    ) -> dict[str, Any]:
        return await self._async_request(
            "POST",
            "/api/gsm/priority",
            payload={
                "sms_preferred": str(sms_preferred),
                "ussd_preferred": str(ussd_preferred),
                "fallback": bool(fallback),
            },
            allow_http_error=True,
        )
