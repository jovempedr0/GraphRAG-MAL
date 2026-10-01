"""Cliente da API oficial do MyAnimeList (v2) com rate limit, retry com backoff e cache em disco.

Para dados públicos basta o header X-MAL-CLIENT-ID (sem OAuth).
Crie o Client ID em https://myanimelist.net/apiconfig.
"""

import json
import logging
import os
import time
from pathlib import Path
from urllib.parse import urlencode

import httpx

log = logging.getLogger(__name__)

BASE_URL = "https://api.myanimelist.net/v2"
# 307: o MAL redireciona para uma página HTML quando limita o acesso por um tempo
RETRYABLE_STATUS = {307, 429, 500, 502, 503, 504}


class MalError(Exception):
    def __init__(self, path, status, message=""):
        super().__init__(f"{path}: HTTP {status} {message}".strip())
        self.path = path
        self.status = status


class MalClient:
    def __init__(
        self,
        client_id=None,
        cache_dir="data/raw",
        min_interval=1.0,  # o MAL não documenta o limite; 1 req/s é conservador
        max_retries=5,
        backoff_base=2.0,
        timeout=30.0,
        transport=None,
        clock=time.monotonic,
        sleep=time.sleep,
    ):
        client_id = client_id or os.environ.get("MAL_CLIENT_ID")
        if not client_id:
            raise ValueError("defina MAL_CLIENT_ID (ex.: em config/.env)")

        self.cache_dir = Path(cache_dir)
        self.min_interval = min_interval
        self.max_retries = max_retries
        self.backoff_base = backoff_base
        self._clock = clock
        self._sleep = sleep
        self._last_request = None
        self._http = httpx.Client(
            base_url=BASE_URL,
            headers={"X-MAL-CLIENT-ID": client_id},
            timeout=timeout,
            transport=transport,
        )

    def cache_path(self, path, params=None):
        # "fields" fica fora do nome do arquivo (seria longo demais).
        # Se mudar os fields pedidos, apague o cache para buscar de novo.
        params = {k: v for k, v in (params or {}).items() if k != "fields"}
        name = path.strip("/")
        if params:
            name += "/" + urlencode(sorted(params.items()))
        return self.cache_dir / f"{name}.json"

    def get(self, path, params=None):
        cached = self.cache_path(path, params)
        if cached.exists():
            return json.loads(cached.read_text())

        data = self._fetch(path, params)
        cached.parent.mkdir(parents=True, exist_ok=True)
        cached.write_text(json.dumps(data, ensure_ascii=False))
        return data

    def _fetch(self, path, params):
        for attempt in range(self.max_retries):
            self._wait_rate_limit()
            try:
                resp = self._http.get(path, params=params)
            except httpx.TransportError as e:
                status, retry_after = None, None
                log.warning("%s: erro de rede (%s)", path, e)
            else:
                if resp.status_code == 200:
                    return resp.json()
                status = resp.status_code
                retry_after = resp.headers.get("Retry-After")
                if status not in RETRYABLE_STATUS:
                    raise MalError(path, status, resp.text[:200])
                log.warning("%s: HTTP %s (tentativa %d)", path, status, attempt + 1)

            if attempt == self.max_retries - 1:
                break
            self._sleep(self._retry_delay(attempt, retry_after))

        raise MalError(path, status, "após retries")

    def _retry_delay(self, attempt, retry_after):
        try:
            return float(retry_after)
        except (TypeError, ValueError):  # ausente ou em formato de data
            return self.backoff_base * 2**attempt

    def _wait_rate_limit(self):
        if self._last_request is not None:
            wait = self._last_request + self.min_interval - self._clock()
            if wait > 0:
                self._sleep(wait)
        self._last_request = self._clock()
