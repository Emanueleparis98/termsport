"""Public catalog adapters. A directory entry is not a playback guarantee."""

import json
import hashlib
import re
from urllib.parse import quote, urljoin, urlsplit

from bs4 import BeautifulSoup

from .models import SPORTS, Event, Source, SourceResult, Stream, plain, sport_name, timestamp, web_url
from .net import FetchError


def base_url(source: Source) -> str:
    parts = urlsplit(source.url)
    return f"{parts.scheme}://{parts.netloc}"


def structured_events(html: str, source: Source, page_url: str) -> list[Event]:
    soup = BeautifulSoup(html, "html.parser")
    events = {}

    def walk(item, depth=0):
        if depth > 20:
            return
        if isinstance(item, list):
            for child in item[:1500]:
                walk(child, depth + 1)
        elif isinstance(item, dict):
            types = item.get("@type", [])
            if isinstance(types, str):
                types = [types]
            if not isinstance(types, list):
                types = []
            if any(t in {"SportsEvent", "Event", "BroadcastEvent"} for t in types) and item.get("name"):
                try:
                    url = web_url(urljoin(page_url, item.get("url") or page_url))
                    sport = item.get("sport") or item.get("description") or item["name"]
                    if isinstance(sport, dict):
                        sport = sport.get("name", "Altro")
                    event = Event(item["name"], plain(sport), source.id, source.name, url,
                                  start=timestamp(item.get("startDate")),
                                  live=item.get("isLiveBroadcast") is True,
                                  competition=plain(item.get("superEvent", {}).get("name", "") if isinstance(item.get("superEvent"), dict) else ""))
                    if not item.get("url"):
                        identity = f"{source.id}:{page_url}:{item.get('@id') or item['name']}:{item.get('startDate', '')}"
                        event.id = hashlib.sha256(identity.encode()).hexdigest()[:12]
                    events[event.id] = event
                except (ValueError, TypeError):
                    pass
            for value in item.values():
                if isinstance(value, (list, dict)):
                    walk(value, depth + 1)

    for script in soup.select('script[type="application/ld+json"]'):
        try:
            walk(json.loads(script.string or script.get_text()))
        except (ValueError, RecursionError):
            continue
    # HTML-only schedules: accept specific event URLs, not every navigation link.
    for link in soup.select("a[href]")[:4000]:
        href = link["href"]
        classes = link.get("class", [])
        if "tk" in classes or "lc2ft" in classes:
            # Matchora's duplicated live ticker and completed cards are not a schedule.
            continue
        title = plain(link.get_text(" ", strip=True) or link.get("title"))
        if not (re.search(r"/(?:eventinfo|events?|matches|match|fixture|game)/[^/?#]+", href, re.I) and len(title) >= 7):
            continue
        try:
            url = web_url(urljoin(page_url, href))
            if urlsplit(url).hostname != urlsplit(page_url).hostname:
                continue
        except ValueError:
            continue
        heading = link.find(["h2", "h3", "h4"])
        team_names = link.select(".lc2t b")
        if heading:
            title = plain(heading.get_text(" ", strip=True))
        elif team_names:
            title = " – ".join(plain(t.get_text()) for t in team_names)
        row = link.find_parent(attrs={"data-sport": True}) or link.find_parent("article") or link.find_parent("tr") or link.parent
        time_node = link.select_one("time[datetime], [data-ts], [data-start], [data-soonko]")
        if time_node is None and row:
            time_node = row.select_one("time[datetime], [data-start]")
        start_value = next((time_node.get(k) for k in ["datetime", "data-ts", "data-start", "data-soonko"] if time_node.get(k)), None) if time_node else None
        sport = link.get("data-sport") or (row.get("data-sport") if row else None)
        competition = (row.get("data-lg", "") if row else "")
        if not sport:
            league = re.search(r"/live/([^/]+)/", href)
            league_name = league[1].replace("-", " ") if league else ""
            league_map = {"premier league": "Soccer", "la liga": "Soccer", "laliga": "Soccer", "serie a": "Soccer", "bundesliga": "Soccer", "ligue 1": "Soccer", "champions league": "Soccer", "europa league": "Soccer", "f1": "Motorsports", "motogp": "Motorsports", "euroleague": "Basketball"}
            sport = league_map.get(league_name, league_name) or ("Cricket" if "crichd" in (urlsplit(source.url).hostname or "") else "Altro")
            category_node = link.select_one("p span")
            if sport_name(sport) not in SPORTS and category_node:
                category = plain(category_node.get_text(" ", strip=True))
                sport = league_map.get(category.casefold(), category)
            if sport_name(sport) not in SPORTS:
                sport = "Altro"
            competition = competition or league_name
        live = "lc2live" in classes or any(plain(node.get_text()).upper() == "LIVE" for node in link.find_all(["span", "div"], recursive=True) if not node.find(["span", "div"]))
        event = Event(title, sport, source.id, source.name, url, start=timestamp(start_value), live=live, competition=competition)
        events.setdefault(event.id, event)
    return list(events.values())


def livetv_events(html: str, source: Source, page_url: str) -> list[Event]:
    soup = BeautifulSoup(html, "html.parser")
    events = {}
    for link in soup.select('a[href*="/eventinfo/"]'):
        title = plain(link.get_text(" ", strip=True))
        if not title:
            continue
        table = link.find_parent("table")
        icon = table.find("img", alt=True) if table else None
        details = table.select_one(".evdesc") if table else None
        raw = plain(details.get_text(" ", strip=True)) if details else ""
        is_live = "live" in link.get("class", [])
        try:
            event = Event(title, (icon.get("alt") or "").split(".")[0] if icon else "Altro",
                          source.id, source.name, web_url(urljoin(page_url, link["href"])),
                          live=is_live, competition=raw[raw.find("(")+1:raw.rfind(")")] if "(" in raw else "",
                          time_label=(raw.split("(")[0].strip() + " · ora del sito") if raw else "")
            events.setdefault(event.id, event)
        except ValueError:
            continue
    return list(events.values())


def tim_events(data: dict, source: Source) -> list[Event]:
    genres = {str(g["id"]): g.get("name", "Altro") for g in data.get("genres", []) if isinstance(g, dict) and "id" in g}
    events = []
    for item in (data.get("events") or []):
        if not isinstance(item, dict) or not item.get("name") or not (item.get("url") or item.get("id")):
            continue
        slug = str(item.get("url") or item["id"])
        event = Event(item["name"], genres.get(str(item.get("genre")), "Altro"), source.id, source.name,
                      base_url(source) + "/watch/" + quote(slug, safe=""), start=timestamp(item.get("time")),
                      live=item.get("live") is True or item.get("status") == "live")
        events.append(event)
    return events


def tim_channels(data: dict, source: Source) -> list[Event]:
    sports_ids = {str(g["id"]) for g in data.get("genres", []) if isinstance(g, dict) and "sport" in g.get("name", "").casefold()}
    events = []
    for item in (data.get("channels") or []):
        if not isinstance(item, dict) or str(item.get("genre")) not in sports_ids or not item.get("url") or not item.get("name"):
            continue
        events.append(Event(item["name"], "Canale sport", source.id, source.name,
                            base_url(source) + "/channel/" + quote(str(item["url"]), safe=""), kind="channel"))
    return events


async def fetch_source(network, source: Source) -> SourceResult:
    try:
        if source.adapter == "timstreams":
            import asyncio
            data, channels = await asyncio.gather(
                network.json(base_url(source)+"/api/live-upcoming"),
                network.json(base_url(source)+"/api/channels"),
                return_exceptions=True,
            )
            if not isinstance(data, dict) and not isinstance(channels, dict):
                raise FetchError("API TimStreams non raggiungibile o formato cambiato.")
            events = []
            if isinstance(data, dict):
                events.extend(tim_events(data, source))
            if isinstance(channels, dict):
                events.extend(tim_channels(channels, source))
        else:
            url = base_url(source) + "/enx/" if source.adapter == "livetv" else source.url
            html, final_url = await network.get(url)
            events = livetv_events(html, source, final_url) if source.adapter == "livetv" else structured_events(html, source, final_url)
        return SourceResult(source, events, "ok" if events else "browser", "Nessun evento leggibile automaticamente; sito disponibile nel browser." if not events else "")
    except (FetchError, ValueError, KeyError, TypeError, AttributeError):
        # Provider failures are isolated. Do not echo arbitrary exception URLs/tokens.
        return SourceResult(source, [], "unavailable", "Sito non raggiungibile, accesso limitato o formato non supportato. Apri nel browser per verificare.")


async def tim_streams(network, event: Event, source: Source) -> list[Stream]:
    if event.kind == "channel":
        data = await network.json(base_url(source)+"/api/channels")
        if not isinstance(data, dict) or not isinstance(data.get("channels"), list):
            raise FetchError("Formato dei canali cambiato. Verifica la fonte nel browser.")
        slug = urlsplit(event.url).path.rsplit("/", 1)[-1]
        item = next((i for i in data.get("channels", []) if quote(str(i.get("url", "")), safe="") == slug), {})
    else:
        slug = urlsplit(event.url).path.rsplit("/", 1)[-1]
        data = await network.json(base_url(source)+"/api/watch/"+slug)
        if not isinstance(data, dict):
            raise FetchError("Formato evento cambiato. Verifica la fonte nel browser.")
        item = data.get("item") or {}
    if not isinstance(item, dict) or not isinstance(item.get("streams", []), list):
        raise FetchError("Formato dei player cambiato. Verifica la fonte nel browser.")
    if item.get("vip"):
        return [Stream(event.url, "Apri nel browser · accesso richiesto")]
    streams = []
    from .resolver import stream_kind
    for index, stream in enumerate((item.get("streams") or [])[:30]):
        if not isinstance(stream, dict) or stream.get("vip"):
            continue
        try:
            url = web_url(stream.get("url", ""))
            streams.append(Stream(url, plain(stream.get("name")) or f"Fonte {index+1}", stream_kind(url), event.url))
        except ValueError:
            continue
    return streams or [Stream(event.url, "Pagina evento")]
