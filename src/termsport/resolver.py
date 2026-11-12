"""Resolve explicit public video tags/links. Never execute obfuscated scripts."""

import asyncio
import json
import re
import sys
from importlib.util import find_spec
from urllib.parse import quote, unquote, urlencode, urljoin, urlsplit

from bs4 import BeautifulSoup

from .models import Stream, plain, web_url
from .net import FetchError


def stream_kind(url: str) -> str:
    path = urlsplit(url).path.casefold()
    if path.endswith(".m3u8"):
        return "hls"
    if path.endswith(".mpd"):
        return "dash"
    if path.endswith((".mp4", ".webm", ".mkv", ".ts", ".m4v")):
        return "video"
    return "page"


async def streamfree_url(network, page_url: str, html: str) -> Stream | None:
    """Read StreamFree's public player config without executing JavaScript."""
    if "get-stream-key/" not in html:
        return None
    path = urlsplit(page_url).path.rstrip("/")
    variant = unquote(path.rsplit("/", 1)[-1])
    if not variant:
        return None
    quality_match = re.search(r"const\s+QUALITY\s*=\s*['\"]([^'\"]+)['\"]", html)
    quality = quality_match.group(1) if quality_match else ""
    suffix_match = re.search(r"const\s+SOURCE_SUFFIX\s*=\s*['\"]([^'\"]*)['\"]", html)
    source_suffix = suffix_match.group(1) if suffix_match else ""
    endpoint_match = re.search(r"get-stream-key/['\"]\s*\+\s*encodeURIComponent\(\s*['\"]([^'\"]+)['\"]", html)
    if not endpoint_match:
        endpoint_match = re.search(r"get-stream-key/([A-Za-z0-9._~-]+)", html)
    stream_key = endpoint_match.group(1) if endpoint_match else variant
    if not endpoint_match and quality and variant.endswith(quality+source_suffix):
        stream_key = variant[:-len(quality+source_suffix)]
    try:
        data = await network.json(urljoin(page_url, "/get-stream-key/"+quote(stream_key, safe="")),
                                  headers={"Referer": page_url})
    except (FetchError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    if data.get("is_external"):
        external = data.get("external_url")
        if not isinstance(external, str):
            return None
        try:
            url = web_url(urljoin(page_url, external))
        except ValueError:
            return None
        kind = stream_kind(url)
        if kind == "page":
            return None
        return Stream(url, "Stream esterno", kind, page_url)
    server = str(data.get("server_name") or "origin").casefold()
    prefix = "/live-externalcdn" if server == "externalcdn" else "/live-cdn" if server != "origin" else "/live"
    url = urljoin(page_url, f"{prefix}/{quote(variant, safe='')}/index.m3u8")
    tokens = {}
    token_match = re.search(r"const\s+_0x\s*=\s*(\{.*?\});", html, re.DOTALL)
    if token_match:
        try:
            tokens = json.loads(token_match.group(1))
        except ValueError:
            tokens = {}
    token = tokens.get(quality) if isinstance(tokens, dict) else None
    if isinstance(token, dict):
        params = {key: token[key] for key in ("_t", "_e", "_n") if isinstance(token.get(key), (str, int, float))}
        if params:
            url += "?"+urlencode(sorted(params.items()))
    try:
        playlist, _ = await network.get(url, headers={"Referer": page_url}, limit=512_000)
    except (FetchError, ValueError):
        return None
    if not playlist.lstrip().startswith("#EXTM3U"):
        return None
    return Stream(url, "HLS StreamFree", "hls", page_url)


def page_streams(html: str, page_url: str) -> tuple[list[Stream], list[str]]:
    soup = BeautifulSoup(html, "html.parser")
    media: dict[str, Stream] = {}
    frames = []
    for node in soup.select("video[src], video source[src], audio source[src], a[href]"):
        raw = node.get("src") or node.get("href")
        try:
            url = web_url(urljoin(page_url, raw))
        except (ValueError, TypeError):
            continue
        kind = stream_kind(url)
        if node.name != "a" or kind != "page":
            if kind == "page":
                mime = str(node.get("type") or "").casefold()
                kind = "hls" if "mpegurl" in mime else "dash" if "dash" in mime else "video"
            media[url] = Stream(url, plain(node.get("label")) or "Video pubblico", kind, page_url)
    # Plain media URLs in player configuration are data, not executable JavaScript.
    for script in soup.find_all("script"):
        for match in re.finditer(r'''["']((?:https?:)?//[^\s"'<>]+?\.(?:m3u8|mpd|mp4)(?:\?[^\s"'<>]*)?)["']''', script.get_text().replace("\\/", "/"), re.IGNORECASE):
            try:
                raw = json.loads('"'+match[1]+'"') if "\\" in match[1] else match[1]
                url = web_url(urljoin(page_url, raw))
                media.setdefault(url, Stream(url, "Sorgente player", stream_kind(url), page_url))
            except ValueError:
                continue
    for frame in soup.select("iframe[src]"):
        raw = frame.get("src", "")
        if not isinstance(raw, str):
            continue
        if re.search(r"(?:advert|doubleclick|adserver|popunder|recaptcha|(?:[./])ads?[./]|/getbanner\.)", raw, re.IGNORECASE):
            continue
        if str(frame.get("width", "")) in {"0", "1"} or str(frame.get("height", "")) in {"0", "1"}:
            continue
        try:
            frames.append(web_url(urljoin(page_url, raw)))
        except ValueError:
            continue
    # Only actual player paths count. A Facebook/Twitter share link may mention
    # "webplayer" in its query string, but must never be crawled as a player.
    player_links = [node["href"] for node in soup.select("a[href]")]
    player_links.extend(match[1] for match in re.finditer(r'''window\.open\(["']([^"']+)["']''', html, re.IGNORECASE))
    for href in player_links:
        if not isinstance(href, str):
            continue
        try:
            url = web_url(urljoin(page_url, href.replace("&amp;", "&")))
            if re.fullmatch(r"/webplayer\d*\.php", urlsplit(url).path, re.IGNORECASE):
                frames.append(url)
        except ValueError:
            continue
    return list(media.values())[:30], list(dict.fromkeys(frames))[:5]


async def resolve_page(network, stream: Stream, *, max_pages: int = 8, candidates: list[str] | None = None,
                    timeout: float = 20) -> list[Stream]:
    if stream.kind != "page":
        return [stream]
    queue = [(stream.url, 0)]
    seen = set()
    result: dict[str, Stream] = {}
    try:
        async with asyncio.timeout(timeout):
            while queue and len(seen) < max_pages:
                url, depth = queue.pop(0)
                if url in seen:
                    continue
                seen.add(url)
                try:
                    html, final_url = await network.get(url)
                except (FetchError, ValueError):
                    continue
                if candidates is not None and final_url not in candidates:
                    candidates.append(final_url)
                # An embedded endpoint can itself be a manifest without a file extension.
                if html.lstrip().startswith("#EXTM3U"):
                    result[final_url] = Stream(final_url, "Diretta HLS", "hls", stream.referer)
                    continue
                if re.search(r"<MPD(?:\s|>)", html[:2000]):
                    result[final_url] = Stream(final_url, "Diretta DASH", "dash", stream.referer)
                    continue
                media, frames = page_streams(html, final_url)
                result.update((item.url, item) for item in media)
                special = await streamfree_url(network, final_url, html)
                if special:
                    result[special.url] = special
                if depth < 2 and not media and not special:
                    queue.extend((url, depth+1) for url in frames if url not in seen)
    except TimeoutError:
        # Return streams found before the deadline instead of losing the whole resolution.
        pass
    return list(result.values())


async def streamlink_url(url: str) -> str | None:
    """Optional standard plugins. No authentication or browser bypass flags."""
    if find_spec("streamlink") is None:
        return None
    # Disable both default config and saved plugin credentials/cookies. Browser
    # automation is not used as an implicit fallback for a protected player.
    # Use our own environment on Linux and Windows, even when Streamlink's
    # separate console script is not exposed by uv/pipx or on PATH.
    options = [sys.executable, "-m", "streamlink", "--no-config", "--no-plugin-cache", "--webbrowser", "false", "--loglevel", "none"]
    probe = await asyncio.create_subprocess_exec(*options, "--can-handle-url-no-redirect", web_url(url),
                                               stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL)
    try:
        await asyncio.wait_for(probe.wait(), 5)
    except (TimeoutError, asyncio.CancelledError):
        if probe.returncode is None:
            probe.kill()
        await probe.wait()
        raise
    if probe.returncode != 0:
        return None
    process = await asyncio.create_subprocess_exec(*options, "--stream-url", web_url(url), "best",
                                                 stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL)
    try:
        output, _ = await asyncio.wait_for(process.communicate(), 25)
    except (TimeoutError, asyncio.CancelledError):
        if process.returncode is None:
            process.kill()
        await process.wait()
        raise
    if process.returncode == 0 and len(output) < 16000:
        try:
            return web_url(output.decode().strip())
        except (ValueError, UnicodeError):
            pass
    return None
