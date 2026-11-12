"""Bounded, cancellable public HTTP reads. No scripts are executed."""

import asyncio
import json
from urllib.parse import urljoin

import httpx

from . import __version__
from .models import web_url


class FetchError(Exception):
    pass


class _Transient(Exception):
    """A response worth retrying once without exposing provider details."""


class Network:
    def __init__(self, client: httpx.AsyncClient | None = None, concurrency: int = 8):
        self.client = client or httpx.AsyncClient(
            timeout=httpx.Timeout(12, connect=5), follow_redirects=False, max_redirects=4,
            headers={"User-Agent": f"TermSport/{__version__} (+local sports search)", "Accept": "text/html,application/json"},
        )
        self.owns_client = client is None
        self.semaphore = asyncio.Semaphore(concurrency)

    async def _get(self, url: str, limit: int) -> tuple[str, str]:
        for _ in range(5):
            async with self.client.stream("GET", url, follow_redirects=False) as response:
                if response.is_redirect:
                    try:
                        target = web_url(urljoin(url, response.headers.get("location", "")))
                    except ValueError:
                        raise FetchError("Il sito ha restituito un reindirizzamento non valido.") from None
                    if url.startswith("https:") and not target.startswith("https:"):
                        raise FetchError("Il sito ha reindirizzato verso un collegamento non sicuro.")
                    url = target
                    continue
                if response.status_code in (502, 503, 504):
                    raise _Transient()
                if response.status_code in (401, 403, 451):
                    raise FetchError(f"Accesso limitato dal sito (HTTP {response.status_code}); apri nel browser.")
                if response.status_code == 429:
                    raise FetchError("Limite di richieste del sito; riprova più tardi.")
                if response.status_code >= 400:
                    raise FetchError(f"Il sito ha risposto HTTP {response.status_code}.")
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

    async def get(self, url: str, *, limit: int = 3_000_000) -> tuple[str, str]:
        url = web_url(url)
        try:
            async with self.semaphore, asyncio.timeout(20):
                for attempt in range(2):
                    try:
                        return await self._get(url, limit)
                    except _Transient:
                        if attempt:
                            raise
                    except (httpx.TransportError, httpx.TimeoutException):
                        if attempt:
                            raise
                    await asyncio.sleep(0.25)
        except _Transient:
            raise FetchError("Sito temporaneamente non disponibile; riprova fra poco.") from None
        except (httpx.HTTPError, httpx.InvalidURL, TimeoutError):
            raise FetchError("Sito non raggiungibile o risposta troppo lenta.") from None
        except FetchError:
            raise
        raise FetchError("Sito non raggiungibile o risposta troppo lenta.")

    async def json(self, url: str):
        text, _ = await self.get(url)
        try:
            return json.loads(text)
        except (ValueError, RecursionError):
            raise FetchError("Il sito non ha restituito JSON valido.") from None

    async def close(self):
        if self.owns_client:
            await self.client.aclose()
