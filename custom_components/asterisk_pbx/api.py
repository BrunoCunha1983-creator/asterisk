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

    async def async_get_state(self) -> dict[str, Any]:
        url = f"{self.base_url}/api/ha-state"
        try:
            async with self._session.get(url, timeout=ClientTimeout(total=10)) as response:
                if response.status != 200:
                    raise AsteriskApiError(f"HTTP {response.status} from {url}")
                data = await response.json(content_type=None)
        except (ClientError, TimeoutError, ValueError) as err:
            raise AsteriskApiError(str(err)) from err

        if not isinstance(data, dict):
            raise AsteriskApiError("Invalid JSON payload")
        return data
