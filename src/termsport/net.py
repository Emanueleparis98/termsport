"""Bounded, cancellable public HTTP reads. No scripts are executed."""

import asyncio
import json
from urllib.parse import urljoin

import httpx

from .models import web_url


class FetchError(Exception):
    pass


class Network:
    def __init__(self, client: httpx.AsyncClient | None = None, concurrency: int = 8):
        self.client = client or httpx.AsyncClient(
            timeout=httpx.Timeout(12, connect=5), follow_redirects=False, max_redirects=4,
            headers={"User-Agent": "TermSport/0.1 (+local sports search)", "Accept": "text/html,application/json"},
        )
        self.owns_client = client is None
        self.semaphore = asyncio.Semaphore(concurrency)

    async def get(self, url: str, *, limit: int = 3_000_000) -> tuple[str, str]:
        url = web_url(url)
        try:
            async with self.semaphore, asyncio.timeout(16):
                for _ in range(5):
                    async with self.client.stream("GET", url, follow_redirects=False) as response:
                        if response.is_redirect:
                            url = web_url(urljoin(url, response.headers.get("location", "")))
                            continue
                        if response.status_code in (401, 403, 451):
                            raise FetchError(f"Accesso limitato dal sito (HTTP {response.status_code}); apri nel browser.")
                        if response.status_code == 429:
                            raise FetchError("Limite di richieste del sito; riprova più tardi.")
                        response.raise_for_status()
                        length = response.headers.get("content-length", "")
                        if length.isdigit() and int(length) > limit:
                            raise FetchError("Risposta del sito troppo grande.")
                        body = bytearray()
                        async for chunk in response.aiter_bytes():
                            body.extend(chunk)
                            if len(body) > limit:
                                raise FetchError("Risposta del sito troppo grande.")
                        try:
                            text = body.decode(response.encoding or "utf-8", errors="replace")
                        except LookupError:
                            text = body.decode("utf-8", errors="replace")
                        return text, web_url(str(response.url))
                raise FetchError("Troppi reindirizzamenti del sito.")
        except (httpx.HTTPError, TimeoutError) as error:
            if isinstance(error, httpx.HTTPStatusError):
                raise FetchError(f"Il sito ha risposto HTTP {error.response.status_code}.") from None
            raise FetchError("Sito non raggiungibile o risposta troppo lenta.") from None

    async def json(self, url: str):
        text, _ = await self.get(url)
        try:
            return json.loads(text)
        except (ValueError, RecursionError):
            raise FetchError("Il sito non ha restituito JSON valido.") from None

    async def close(self):
        if self.owns_client:
            await self.client.aclose()
