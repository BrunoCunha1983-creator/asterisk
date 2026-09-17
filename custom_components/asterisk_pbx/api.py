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
                timeout=ClientTimeout(total=30),
            ) as response:
                try:
                    data = await response.json(content_type=None)
                except ValueError as err:
                    raise AsteriskApiError(f"Invalid JSON payload from {url}") from err
                if response.status >= 400 and not allow_http_error:
                    detail = ""
                    if isinstance(data, dict):
                        detail = str(data.get("output") or data.get("error") or "").strip()
                    suffix = f": {detail}" if detail else ""
                    raise AsteriskApiError(f"HTTP {response.status} from {url}{suffix}")
        except (ClientError, TimeoutError) as err:
            raise AsteriskApiError(str(err)) from err

        if not isinstance(data, dict):
            raise AsteriskApiError("Invalid JSON payload")
        data.setdefault("http_status", response.status)
        return data

    async def async_get_state(self) -> dict[str, Any]:
        return await self._async_request("GET", "/api/ha-state")

    async def async_get_pbx(self) -> dict[str, Any]:
        return await self._async_request("GET", "/api/pbx")

    @staticmethod
    def _result_ok(result: dict[str, Any]) -> bool:
        if not bool(result.get("ok")):
            return False
        text = str(result.get("output") or "").lower()
        failure_markers = (
            "no such command",
            "no such module",
            "not connected",
            "not found",
            "unable to",
            "failed",
            "failure",
            "+cms error",
            "+cme error",
        )
        return not any(marker in text for marker in failure_markers)

    async def _async_send_sms_usb(
        self,
        pbx: dict[str, Any],
        number: str,
        message: str,
        device: str = "",
    ) -> dict[str, Any]:
        dongles = [x for x in (pbx.get("gsm_dongles") or []) if isinstance(x, dict)]
        selected = str(device or "").strip()
        if not selected:
            for dongle in dongles:
                name = str(dongle.get("name") or "").strip()
                if name:
                    selected = name
                    break
        if not selected:
            return {
                "ok": False,
                "gateway": "usb_gsm",
                "output": "Nenhum modem USB/GSM ativo estÃ¡ configurado.",
            }

        result = await self._async_request(
            "POST",
            "/api/action",
            payload={
                "action": "sms",
                "device": selected,
                "number": number,
                "message": message,
            },
            allow_http_error=True,
        )
        result["ok"] = self._result_ok(result)
        result["gateway"] = "usb_gsm"
        result["device"] = selected
        return result

    async def _async_send_sms_sim800(
        self,
        pbx: dict[str, Any],
        number: str,
        message: str,
    ) -> dict[str, Any]:
        cfg = pbx.get("sim800c") or {}
        if not isinstance(cfg, dict) or not bool(cfg.get("enabled")):
            return {
                "ok": False,
                "gateway": "sim800",
                "output": "SIM800C estÃ¡ desativado na configuraÃ§Ã£o do PBX.",
            }

        result = await self._async_request(
            "POST",
            "/api/sim800c-action",
            payload={"action": "sms", "number": number, "text": message},
            allow_http_error=True,
        )
        result["ok"] = self._result_ok(result)
        result["gateway"] = "sim800"
        result["device"] = str(cfg.get("port") or "SIM800C")
        return result

    async def async_send_sms(
        self,
        number: str,
        message: str,
        gateway: str = "auto",
        device: str = "",
    ) -> dict[str, Any]:
        number = str(number or "").strip()
        message = str(message or "").replace("\x1a", "").strip()
        gateway = str(gateway or "auto").strip().lower()
        device = str(device or "").strip()

        if not number or not message:
            raise AsteriskApiError("NÃºmero e mensagem sÃ£o obrigatÃ³rios")
        if gateway not in {"auto", "usb_gsm", "sim800"}:
            raise AsteriskApiError( ‰…Ñ•Ý…ä¥¹Û…±¥‘¼èÕÍ”…ÕÑ¼°ÕÍ‰}Í´½ÔÍ¥´àÀÀˆ¤((€€€€€€€Á‰à€ô…Ý…¥ÐÍ•±˜¹…Íå¹}•Ñ}Á‰à ¤(€€€€€€€Í¡…É•€ôÁ‰à¹•Ð ‰Íµ}Í¡…É•ˆ¤½Èíô(€€€€€€€¥˜¹½Ð¥Í¥¹ÍÑ…¹”¡Í¡…É•°‘¥Ð¤è(€€€€€€€€€€€Í¡…É•€ôíô((€€€€€€€ÁÉ•™•ÉÉ•€ôÍÑÈ¡Í¡…É•¹•Ð ‰ÁÉ•™•ÉÉ•‘}…Ñ•Ý…äˆ¤½È€‰ÕÍ‰}Í´ˆ¤¹ÍÑÉ¥À ¤¹±½Ý•È ¤(€€€€€€€¥˜ÁÉ•™•ÉÉ•¹½Ð¥¸ì‰ÕÍ‰}Í´ˆ°€‰Í¥´àÀÀ‰ôè(€€€€€€€€€€€ÁÉ•™•ÉÉ•€ô€‰ÕÍ‰}Í´ˆ(€€€€€€€™…±±‰…­}•¹…‰±•€ô‰½½°¡Í¡…É•¹•Ð ‰™…±±‰…¬ˆ°QÉÕ”¤¤((€€€€€€€¥˜…Ñ•Ý…ä€ôô€‰…ÕÑ¼ˆè(€€€€€€€€€€€½É‘•È€ômÁÉ•™•ÉÉ•‘t(€€€€€€€€€€€…±Ñ•É¹…Ñ”€ô€‰Í¥´àÀÀˆ¥˜ÁÉ•™•ÉÉ•€ôô€‰ÕÍ‰}Í´ˆ•±Í”€‰ÕÍ‰}Í´ˆ(€€€€€€€€€€€¥˜™…±±‰…­}•¹…‰±•è(€€€€€€€€€€€€€€€½É‘•È¹…ÁÁ•¹¡…±Ñ•É¹…Ñ”¤(€€€€€€€•±Í”è(€€€€€€€€€€€½É‘•È€ôm…Ñ•Ý…åt((€€€€€€€…ÑÑ•µÁÑÌè±¥ÍÑm‘¥ÑmÍÑÈ°¹åut€ômt(€€€€€€€™½È…¹‘¥‘…Ñ”¥¸½É‘•Èè(€€€€€€€€€€€ÑÉäè(€€€€€€€€€€€€€€€¥˜…¹‘¥‘…Ñ”€ôô€‰Í¥´àÀÀˆè(€€€€€€€€€€€€€€€€€€€É•ÍÕ±Ð€ô…Ý…¥ÐÍ•±˜¹}…Íå¹}Í•¹‘}ÍµÍ}Í¥´àÀÀ¡Á‰à°¹Õµ‰•È°µ•ÍÍ…”¤(€€€€€€€€€€€€€€€•±Í”è(€€€€€€€€€€€€€€€€€€€É•ÍÕ±Ð€ô…Ý…¥ÐÍ•±˜¹}…Íå¹}Í•¹‘}ÍµÍ}ÕÍˆ¡Á‰à°¹Õµ‰•È°µ•ÍÍ…”°‘•Ù¥”¤(€€€€€€€€€€€•á•ÁÐÍÑ•É¥Í­Á¥ÉÉ½È…Ì•ÉÈè(€€€€€€€€€€€€€€€É•ÍÕ±Ð€ôì‰½¬ˆè…±Í”°€‰…Ñ•Ý…äˆè…¹‘¥‘…Ñ”°€‰½ÕÑÁÕÐˆèÍÑÈ¡•ÉÈ¥ô((€€€€€€€€€€€…ÑÑ•µÁÑÌ¹…ÁÁ•¹ (€€€€€€€€€€€€€€€ì(€€€€€€€€€€€€€€€€€€€€‰…Ñ•Ý…äˆèÉ•ÍÕ±Ð¹•Ð ‰…Ñ•Ý…äˆ°…¹‘¥‘…Ñ”¤°(€€€€€€€€€€€€€€€€€€€€‰‘•Ù¥”ˆèÉ•ÍÕ±Ð¹•Ð ‰‘•Ù¥”ˆ°€ˆˆ¤°(€€€€€€€€€€€€€€€€€€€€‰½¬ˆè‰½½°¡É•ÍÕ±Ð¹•Ð ‰½¬ˆ¤¤°(€€€€€€€€€€€€€€€€€€€€‰½ÕÑÁÕÐˆèÍÑÈ¡É•ÍÕ±Ð¹•Ð ‰½ÕÑÁÕÐˆ¤½È€ˆˆ¤°(€€€€€€€€€€€€€€€ô(€€€€€€€€€€€€¤(€€€€€€€€€€€¥˜É•ÍÕ±Ð¹•Ð ‰½¬ˆ¤è(€€€€€€€€€€€€€€€É•ÑÕÉ¸ì(€€€€€€€€€€€€€€€€€€€€¨©É•ÍÕ±Ð°(€€€€€€€€€€€€€€€€€€€€‰½¬ˆèQÉÕ”°(€€€€€€€€€€€€€€€€€€€€‰ÁÉ•™•ÉÉ•‘}…Ñ•Ý…äˆèÁÉ•™•ÉÉ•°(€€€€€€€€€€€€€€€€€€€€‰™…±±‰…­}•¹…‰±•ˆè™…±±‰…­}•¹…‰±•°(€€€€€€€€€€€€€€€€€€€€‰…ÑÑ•µÁÑÌˆè…ÑÑ•µÁÑÌ°(€€€€€€€€€€€€€€€ô((€€€€€€€½ÕÑÁÕÐ€ô…ÑÑ•µÁÑÍl´Åul‰½ÕÑÁÕÐ‰t¥˜…ÑÑ•µÁÑÌ•±Í”€‰;¼™½¤Á½ÍÏµÙ•°•¹Ù¥…È¼M5L¸ˆ(€€€€€€€É•ÑÕÉ¸ì(€€€€€€€€€€€€‰½¬ˆè…±Í”°(€€€€€€€€€€€€‰…Ñ•Ý…äˆè…ÑÑ•µÁÑÍl´Åul‰…Ñ•Ý…ä‰t¥˜…ÑÑ•µÁÑÌ•±Í”ÁÉ•™•ÉÉ•°(€€€€€€€€€€€€‰½ÕÑÁÕÐˆè½ÕÑÁÕÐ°(€€€€€€€€€€€€‰ÁÉ•™•ÉÉ•‘}…Ñ•Ý…äˆèÁÉ•™•ÉÉ•°(€€€€€€€€€€€€‰™…±±‰…­}•¹…‰±•ˆè™…±±‰…­}•¹…‰±•°(€€€€€€€€€€€€‰…ÑÑ•µÁÑÌˆè…ÑÑ•µÁÑÌ°(€€€€€€€ô(