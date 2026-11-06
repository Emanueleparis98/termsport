"""Resolve explicit public video tags/links. Never execute obfuscated scripts."""

import asyncio
import json
import re
import shutil
from pathlib import Path
from urllib.parse import urljoin, urlsplit

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
                mime = node.get("type", "").casefold()
                kind = "hls" if "mpegurl" in mime else "dash" if "dash" in mime else "video"
            media[url] = Stream(url, plain(node.get("label")) or "Video pubblico", kind, page_url)
    # Plain media URLs in player configuration are data, not executable JavaScript.
    for script in soup.find_all("script"):
        for match in re.finditer(r'''["'](https?://[^\s"'<>]+?\.(?:m3u8|mpd|mp4)(?:\?[^\s"'<>]*)?)["']''', script.get_text().replace("\\/", "/")):
            try:
                raw = json.loads('"'+match[1]+'"') if "\\" in match[1] else match[1]
                url = web_url(raw)
                media.setdefault(url, Stream(url, "Sorgente player", stream_kind(url), page_url))
            except ValueError:
                continue
    for frame in soup.select("iframe[src]"):
        raw = frame.get("src", "")
        if re.search(r"(?:advert|doubleclick|adserver|popunder|recaptcha|(?:[./])ads[./])", raw, re.I):
            continue
        if str(frame.get("width", "")) in {"0", "1"} or str(frame.get("height", "")) in {"0", "1"}:
            continue
        try:
            frames.append(web_url(urljoin(page_url, raw)))
        except ValueError:
            continue
    # LiveTV explicitly links public player windows (no arbitrary onclick execution).
    for match in re.finditer(r'''(?:href=["']|window\.open\(["'])([^"']*webplayer[^"']*)["']''', html, re.I):
        try:
            frames.append(web_url(urljoin(page_url, match[1].replace("&amp;", "&"))))
        except ValueError:
            continue
    return list(media.values())[:30], list(dict.fromkeys(frames))[:5]


async def resolve_page(network, stream: Stream, *, max_pages: int = 8, candidates: list[str] | None = None) -> list[Stream]:
    if stream.kind != "page":
        return [stream]
    queue = [(stream.url, 0)]
    seen = set()
    result: dict[str, Stream] = {}
    while queue and len(seen) < max_pages:
        url, depth = queue.pop(0)
        if url in seen:
            continue
        seen.add(url)
        try:
            html, final_url = await network.get(url)
        except FetchError:
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
        if depth < 2 and not media:
            queue.extend((url, depth+1) for url in frames if url not in seen)
    return list(result.values())


async def streamlink_url(url: str) -> str | None:
    """Optional standard plugins. No authentication or browser bypass flags."""
    executable = shutil.which("streamlink")
    if not executable:
        sibling = Path(__import__("sys").executable).parent / "streamlink"
        executable = str(sibling) if sibling.exists() else None
    if not executable:
        return None
    # Disable both default config and saved plugin credentials/cookies. Browser
    # automation is not used as an implicit fallback for a protected player.
    options = [executable, "--no-config", "--no-plugin-cache", "--webbrowser", "false", "--loglevel", "none"]
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
