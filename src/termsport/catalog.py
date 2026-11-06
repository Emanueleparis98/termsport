import hashlib
import json
from importlib.resources import files
from pathlib import Path
from urllib.parse import urlsplit

from bs4 import BeautifulSoup

from .models import Source, plain, web_url

FMHY_URL = "https://fmhy.net/video#live-tv-sports"
ADAPTERS = {"tim-streams.com": "timstreams", "timstreams.co.rw": "timstreams", "livetv.sx": "livetv",
            "matchora.to": "matchora", "falconstreams.app": "falcon"}


def parse_fmhy(html: str) -> list[Source]:
    soup = BeautifulSoup(html, "html.parser")
    start = soup.find(id="live-tv-sports")
    if not start:
        raise ValueError("La sezione Live TV / Sports non è presente nella pagina FMHY.")
    if start.name != "h2":
        start = start.find_parent("h2") or start
    section = ""
    sources: dict[str, Source] = {}
    for node in start.next_siblings:
        if getattr(node, "name", None) == "h2":
            break
        if getattr(node, "name", None) == "h3":
            section = plain(node.get_text(" ", strip=True)).replace("\u200b", "").strip()
        if section not in {"Live TV", "Live Sports"} or getattr(node, "name", None) != "ul":
            continue
        for li in node.find_all("li", recursive=False):
            candidates = []
            for a in li.select("a[href]"):
                label = plain(a.get_text(" ", strip=True))
                if label.casefold() in {"status", "mirrors", "bypass blocks", "tg", "tools", "invite"}:
                    continue
                try:
                    url = web_url(a["href"])
                except ValueError:
                    continue
                if urlsplit(url).hostname in {"fmhy.net", "rentry.co", "redd.it", "www.reddit.com"}:
                    # Community/calendar links remain in the directory, never executable adapters.
                    pass
                candidates.append((label, url))
            if not candidates:
                continue
            label, url = candidates[0]
            if label.isdigit():
                # FMHY may hide the primary href behind a relative redirect;
                # keep its real name rather than calling the source "2".
                label = next((plain(a.get_text(" ", strip=True)) for a in li.find_all("a")
                              if plain(a.get_text(" ", strip=True)) and not plain(a.get_text(" ", strip=True)).isdigit()), label)
            host = (urlsplit(url).hostname or "").removeprefix("www.")
            key = host
            if key in sources:
                if section not in sources[key].sections:
                    sources[key].sections.append(section)
                for _, mirror in candidates:
                    if mirror != sources[key].url and mirror not in sources[key].mirrors:
                        sources[key].mirrors.append(mirror)
                continue
            source_id = "".join(c if c.isalnum() else "-" for c in label.casefold()).strip("-")
            if not source_id or any(s.id == source_id for s in sources.values()):
                source_id = hashlib.sha256(url.encode()).hexdigest()[:10]
            sources[key] = Source(source_id, label, url, [section], [u for _, u in candidates[1:]],
                                  plain(li.get_text(" ", strip=True), 500), ADAPTERS.get(host, "generic"))
    if len(sources) < 10:
        raise ValueError("Elenco FMHY incompleto; conservo il catalogo precedente.")
    return list(sources.values())


def load_catalog(path: Path | None = None) -> list[Source]:
    if path and path.exists():
        try:
            content = path.read_text()
            data = json.loads(content)
            result = [Source(**s) for s in data["sources"]]
            if result and all(web_url(s.url) for s in result):
                return result
        except (ValueError, KeyError, TypeError, OSError):
            pass
    data = json.loads(files("termsport.data").joinpath("sources.json").read_text())
    return [Source(**s) for s in data["sources"]]


async def update_catalog(network, path: Path) -> list[Source]:
    html, _ = await network.get(FMHY_URL)
    sources = parse_fmhy(html)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps({"source": FMHY_URL, "sources": [s.to_dict() for s in sources]}, ensure_ascii=False, indent=2))
    temporary.replace(path)
    return sources
