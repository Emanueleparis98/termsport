import asyncio
from dataclasses import dataclass, field
from datetime import date

from .cache import AsyncTTLCache
from .models import Event, Source, SourceResult, Stream, event_sort
from .providers import fetch_source, tim_streams
from .resolver import page_streams, resolve_page, streamlink_url

SEARCH_TIMEOUT = 30.0
PAGE_TIMEOUT = 20.0
STREAMLINK_TIMEOUT = 30.0


@dataclass
class SearchResult:
    events: list[Event] = field(default_factory=list)
    sources: list[SourceResult] = field(default_factory=list)
    partial: bool = False


class SportsService:
    def __init__(self, network, sources: list[Source]):
        self.network = network
        self.sources = sources
        self.last_results: list[SourceResult] = []
        self._choices_cache = AsyncTTLCache(ttl=60, maxsize=256)
        self._resolve_cache = AsyncTTLCache(ttl=120, maxsize=128)

    async def search(self, query="", sport="all", day: date | None = None, source_id="all", *, all_sites=False, progress=None):
        # Full-source scans are explicit: ~80 third-party sites are not contacted on every keystroke.
        selected = [s for s in self.sources if source_id == s.id or (source_id == "all" and (all_sites or s.adapter != "generic"))]
        tasks = [asyncio.create_task(fetch_source(self.network, source)) for source in selected]
        results = []
        partial = False
        try:
            async with asyncio.timeout(SEARCH_TIMEOUT):
                for task in asyncio.as_completed(tasks):
                    result = await task
                    results.append(result)
                    if progress:
                        progress(result, len(results), len(tasks))
        except TimeoutError:
            # Keep the sources that answered; the app can still show a useful partial list.
            partial = True
            if progress:
                progress(SourceResult(Source("timeout", "Ricerca parziale", "", []), [], "unavailable",
                                      "Alcune fonti non hanno risposto in tempo."), len(results), len(tasks))
        finally:
            for task in tasks:
                if not task.done():
                    task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
        self.last_results = results
        events = {e.id: e for r in results for e in r.events if e.matches(query, sport, day)}
        return SearchResult(sorted(events.values(), key=event_sort), results, partial)

    async def choices(self, event: Event) -> list[Stream]:
        key = (event.id, event.url, event.kind)
        return await self._choices_cache.get(key, lambda: self._load_choices(event))

    async def _load_choices(self, event: Event) -> list[Stream]:
        source = next((s for s in self.sources if s.id == event.source_id), None)
        if source and source.adapter == "timstreams":
            return await tim_streams(self.network, event, source)
        html, final_url = await self.network.get(event.url)
        direct, frames = page_streams(html, final_url)
        return direct + [Stream(url, f"Player {index+1}", referer=event.url) for index, url in enumerate(frames)] or [Stream(event.url, "Pagina evento · prova estrazione o apri nel browser")]

    async def resolve(self, stream: Stream) -> list[Stream]:
        key = (stream.url, stream.referer, stream.kind)
        return await self._resolve_cache.get(key, lambda: self._resolve(stream))

    async def _resolve(self, stream: Stream) -> list[Stream]:
        candidates = []
        direct = await resolve_page(self.network, stream, candidates=candidates, timeout=PAGE_TIMEOUT)
        if direct:
            return direct
        async with asyncio.timeout(STREAMLINK_TIMEOUT):
            for page in dict.fromkeys([*reversed(candidates), stream.url]):
                url = await streamlink_url(page)
                if url:
                    return [Stream(url, "Streamlink", "video", page)]
        return []

    def clear_cache(self) -> None:
        self._choices_cache.clear()
        self._resolve_cache.clear()

    async def close(self):
        await self.network.close()
