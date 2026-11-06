import asyncio
from datetime import date, datetime, timezone
from pathlib import Path

import httpx
import pytest

from termsport.catalog import load_catalog, parse_fmhy, update_catalog
from termsport.models import Event, Source, Stream, plain, sport_name, timestamp, web_url
from termsport.net import FetchError, Network
from termsport.player import Player
from termsport.providers import fetch_source, livetv_events, structured_events, tim_channels, tim_events, tim_streams
from termsport.resolver import page_streams, resolve_page, stream_kind
from termsport.service import SportsService


@pytest.fixture
def source():
    return Source("test", "Fonte di prova", "https://sport.example/", ["Live Sports"])


@pytest.mark.parametrize("text,expected", [("Soccer", "calcio"), ("NBA", "basket"), ("American Football", "football americano"), ("MotoGP", "motori"), ("Tennis", "tennis")])
def test_sports(text, expected):
    assert sport_name(text) == expected


def test_untrusted_text_is_inert():
    assert plain("\x1b[31m[red]Evento\x00\n") == "[red]Evento"


@pytest.mark.parametrize("url", ["javascript:alert(1)", "file:///etc/passwd", "https://user:secret@site.test/", "http://127.0.0.1/", "http://169.254.169.254/", "http://192.168.1.1/", "https://site.test/a\nx"])
def test_unsafe_urls(url):
    with pytest.raises(ValueError):
        web_url(url)


def test_time_requires_declared_timezone():
    assert timestamp("2026-11-06T10:30:00") is None
    assert timestamp("2026-11-06T10:30:00Z").tzinfo is not None
    assert timestamp(1793961000000).year == 2026
    assert timestamp("bad") is None


def test_filter_alias_and_stable_event_ids(source):
    first = Event("Alpha - Beta", "Soccer", source.id, source.name, source.url)
    second = Event("Gamma - Delta", "Soccer", source.id, source.name, source.url)
    assert first.id == second.id  # Scores, countdowns and title changes cannot break CLI playback IDs.
    assert first.matches("football") and first.matches("calcio")
    assert not first.matches("tennis")
    assert first.matches("alpha", "calcio")


def test_catalog_all_sections_and_mirrors():
    rows = "".join(f'<li><a href="https://site{i}.test/">Sito {i}</a>, <a href="https://mirror{i}.test/">2</a> / <a href="https://status.test/">Status</a></li>' for i in range(10))
    html = f'<h2 id="live-tv-sports">Live TV / Sports</h2><h3>Live TV</h3><ul>{rows}</ul><h3>Live Sports</h3><ul><li><a href="https://site0.test/">Sito 0</a></li></ul><h3>Sports Replays</h3><ul><li><a href="https://replay.test/">Replay</a></li></ul>'
    sources = parse_fmhy(html)
    assert len(sources) == 10
    assert sources[0].sections == ["Live TV", "Live Sports"]
    assert sources[0].mirrors == ["https://mirror0.test/"]
    redirected = html.replace('<a href="https://site0.test/">Sito 0</a>', '<a href="/redirect">Sito 0</a><a href="https://site0.test/">2</a>', 1)
    assert parse_fmhy(redirected)[0].name == "Sito 0"
    with pytest.raises(ValueError):
        parse_fmhy("<html>Schema cambiato</html>")


def test_bundled_catalog_is_complete_and_unique():
    sources = load_catalog()
    assert len(sources) == 81
    assert len({s.id for s in sources}) == 81
    assert any(s.adapter == "livetv" for s in sources)
    assert any(s.adapter == "timstreams" for s in sources)
    assert all(web_url(s.url) for s in sources)


async def test_failed_catalog_update_preserves_old_file(tmp_path, respx_mock):
    target = tmp_path / "sources.json"
    target.write_text("old")
    respx_mock.get("https://fmhy.net/video").respond(text="no headings")
    network = Network()
    try:
        with pytest.raises(ValueError):
            await update_catalog(network, target)
        assert target.read_text() == "old"
    finally:
        await network.close()


async def test_http_bounds_status_and_redirects(respx_mock):
    network = Network()
    try:
        respx_mock.get("https://site.test/large").respond(text="x"*100)
        with pytest.raises(FetchError, match="grande"):
            await network.get("https://site.test/large", limit=10)
        respx_mock.get("https://site.test/private").respond(status_code=451, text="secret-token")
        with pytest.raises(FetchError) as failure:
            await network.get("https://site.test/private")
        assert "451" in str(failure.value) and "secret" not in str(failure.value)
        respx_mock.get("https://site.test/redirect").respond(status_code=302, headers={"location":"http://127.0.0.1/private"})
        with pytest.raises(ValueError):
            await network.get("https://site.test/redirect")
    finally:
        await network.close()


def test_livetv_extracts_sport_live_and_site_time(source):
    html = '<table><tr><td><img alt="Tennis. ATP"/></td><td><a class="live" href="/enx/eventinfo/11_test/">Alpha vs Beta</a><a class="live" href="/enx/eventinfo/11_test/"><img/></a><span class="evdesc">15:30 (ATP Test)</span></td></tr></table>'
    events = livetv_events(html, source, source.url)
    assert len(events) == 1
    assert events[0].live and events[0].sport == "tennis"
    assert events[0].start is None
    assert events[0].time_label.endswith("ora del sito")


def test_structured_schedule_uses_real_dates(source):
    html = '<script type="application/ld+json">{"@graph":[{"@type":"SportsEvent","name":"Alpha vs Beta","sport":"Tennis","startDate":"2026-11-06T19:00:00Z","url":"/event/alpha"}]}</script>'
    events = structured_events(html, source, source.url)
    assert len(events) == 1 and events[0].start.hour == 19
    assert events[0].matches("tennis", day=date(2026,11,6))
    assert not events[0].matches("tennis", day=date(2026,11,7))


def test_same_page_jsonld_can_describe_distinct_events(source):
    html='<script type="application/ld+json">[{"@type":"SportsEvent","name":"Alpha Beta","sport":"Tennis"},{"@type":"SportsEvent","name":"Gamma Delta","sport":"Tennis"}]</script>'
    events=structured_events(html,source,source.url)
    assert len(events)==2 and events[0].id!=events[1].id


def test_matchora_metadata_ticker_and_completed_cards(source):
    html='''<a class="tk" href="/match/a">Alpha Beta 2-1 LIVE</a>
    <section data-sport="Soccer" data-lg="Premier League">
      <a class="evc lcard lc2 lc2up" href="/match/a"><span data-ts="1793995200">20:00</span><span class="lc2t"><b>Alpha</b></span><span class="lc2t"><b>Beta</b></span></a>
      <a class="evc lc2ft" href="/match/b">Completed game</a>
    </section>'''
    events=structured_events(html,source,source.url)
    assert len(events)==1
    event=events[0]
    assert event.title=='Alpha – Beta' and event.sport=='calcio' and event.competition=='Premier League'
    assert event.start is not None and event.start.tzinfo is not None


def test_falcon_heading_timezone_and_category(source):
    html='''<a href="/live/nhl/match/alpha/1"><div>Countdown 01:23</div><h3>Alpha vs Beta</h3><time datetime="2026-11-06T20:00:00Z">23:00</time></a>'''
    event=structured_events(html,source,source.url)[0]
    assert event.title=='Alpha vs Beta' and event.sport=='hockey'
    assert event.start.hour==20 and event.competition=='nhl'


def test_timstreams_handles_null_events_and_only_sports_channels(source):
    assert tim_events({"events":None,"genres":[]}, source) == []
    channels = {"genres":[{"id":1,"name":"Sports"},{"id":2,"name":"News"}], "channels":[{"name":"Sport Test","url":"sport","genre":1},{"name":"News","url":"news","genre":2}]}
    result = tim_channels(channels, source)
    assert len(result) == 1 and result[0].kind == "channel"


async def test_timstreams_access_required_is_not_bypassed(source, respx_mock):
    event = Event("Test", "tennis", source.id, source.name, source.url+"watch/test")
    respx_mock.get("https://sport.example/api/watch/test").respond(json={"item":{"vip":True,"streams":[{"url":"https://cdn.example/secret.m3u8"}]}})
    network = Network()
    try:
        result = await tim_streams(network, event, source)
        assert len(result) == 1 and result[0].kind == "page" and result[0].url == event.url
    finally:
        await network.close()


def test_resolver_keeps_media_and_filters_ad_frames():
    html = '<video><source src="/live.m3u8" type="application/x-mpegURL"/></video><iframe src="https://ads.example/banner"></iframe><iframe src="/embed/test"></iframe><script>player({file:"https://cdn.test/live.mpd?sig=x"})</script><a href="javascript:alert(1)">play</a>'
    streams, frames = page_streams(html, "https://site.test/event")
    assert {s.kind for s in streams} == {"hls","dash"}
    assert frames == ["https://site.test/embed/test"]


def test_media_query_escapes_are_decoded_as_data():
    media,_=page_streams('<script>p({file:"https://cdn.test/live.m3u8?x=1\\u0026y=2"})</script>','https://site.test/')
    assert media[0].url=='https://cdn.test/live.m3u8?x=1&y=2'


def test_protocol_relative_p2p_manifest_is_read_without_running_scripts():
    html='''<script>window.__p2pPlayer = {"stream":"//cdn.test/hls/live/index.m3u8?cst=public-test-token","tracker":"wss://tracker.test/"};</script>'''
    media,frames=page_streams(html,'https://embed.test/p2p/?id=123')
    assert len(media)==1 and media[0].kind=='hls'
    assert media[0].url=='https://cdn.test/hls/live/index.m3u8?cst=public-test-token'
    assert media[0].referer=='https://embed.test/p2p/?id=123'
    assert frames==[]


def test_player_links_exclude_share_queries_and_ad_frames():
    html='''<a href="/webplayer2.php?t=test&amp;c=123">Play</a>
    <a href="https://facebook.com/share.php?u=https%3A%2F%2Fsite.test%2Fwebplayer2.php">Share</a>
    <iframe src="//ad.example/getbanner.php?zone_id=1"></iframe>
    <iframe src="https://embed.test/p2p/?id=123"></iframe>'''
    _,frames=page_streams(html,'https://site.test/event/123')
    assert frames==['https://embed.test/p2p/?id=123','https://site.test/webplayer2.php?t=test&c=123']


async def test_livetv_wrapper_to_p2p_config_resolves_hls(respx_mock):
    root='https://site.test/webplayer2.php?t=tvope&c=123'
    embed='https://embed.test/p2p/?id=123'
    respx_mock.get(root).respond(text=f'<iframe src="{embed}"></iframe><a href="https://facebook.com/share.php?u=webplayer">Share</a>')
    respx_mock.get(embed).respond(text='<script>window.__p2pPlayer={"stream":"//cdn.test/hls/live/index.m3u8?cst=test"};</script><iframe src="//ad.example/getbanner.php"></iframe>')
    network=Network()
    try:
        candidates=[]
        result=await resolve_page(network,Stream(root),candidates=candidates)
        assert len(result)==1 and result[0].kind=='hls'
        assert result[0].referer==embed
        assert candidates==[root,embed]
        assert len(respx_mock.calls)==2
    finally:await network.close()


async def test_nested_streamlink_fallback_uses_the_actual_player_page(monkeypatch,respx_mock,source):
    import termsport.service as module
    from unittest.mock import AsyncMock
    respx_mock.get(source.url).respond(text='<iframe src="https://supported.test/embed/1"></iframe>')
    respx_mock.get('https://supported.test/embed/1').respond(text='<html>Custom player</html>')
    extractor=AsyncMock(return_value='https://cdn.test/live.m3u8')
    monkeypatch.setattr(module,'streamlink_url',extractor)
    service=SportsService(Network(),[source])
    try:
        result=await service.resolve(Stream(source.url))
        assert result[0].url=='https://cdn.test/live.m3u8'
        assert extractor.await_args.args==('https://supported.test/embed/1',)
    finally:await service.close()


async def test_nested_player_resolves_without_executing_javascript(respx_mock):
    respx_mock.get("https://site.test/event").respond(text='<iframe src="/embed/test"></iframe>')
    respx_mock.get("https://site.test/embed/test").respond(text='<video src="https://cdn.test/live.m3u8"></video>')
    network = Network()
    try:
        result = await resolve_page(network, Stream("https://site.test/event"))
        assert result[0].url == "https://cdn.test/live.m3u8"
        assert result[0].referer == "https://site.test/embed/test"
    finally:
        await network.close()


async def test_extensionless_embedded_manifest_is_a_stream(respx_mock):
    respx_mock.get('https://site.test/player').respond(text='<iframe src="/playlist?id=1"></iframe>')
    respx_mock.get('https://site.test/playlist?id=1').respond(text='#EXTM3U\n#EXT-X-TARGETDURATION:6\nsegment.ts')
    network=Network()
    try:
        result=await resolve_page(network,Stream('https://site.test/player'))
        assert result[0].url=='https://site.test/playlist?id=1' and result[0].kind=='hls'
    finally:await network.close()


async def test_provider_failure_isolated_and_cancelled(monkeypatch, source):
    import termsport.service as module
    from termsport.models import SourceResult
    other = Source("other","Other","https://other.example/",adapter="livetv")
    source.adapter = "livetv"
    async def fetch(network, src):
        if src.id == "other":
            return SourceResult(src, [], "unavailable")
        return SourceResult(src, [Event("Alpha Beta","tennis",src.id,src.name,src.url)])
    monkeypatch.setattr(module,"fetch_source",fetch)
    service=SportsService(None,[source,other])
    result=await service.search("tennis")
    assert len(result.events)==1 and len(result.sources)==2


async def test_search_cancellation_stops_all_children(monkeypatch, source):
    import termsport.service as module
    source.adapter="livetv"
    cancelled=[]
    started=asyncio.Event()
    async def fetch(network,src):
        started.set()
        try:
            await asyncio.sleep(100)
        finally:
            cancelled.append(src.id)
    monkeypatch.setattr(module,"fetch_source",fetch)
    service=SportsService(None,[source])
    task=asyncio.create_task(service.search())
    await started.wait();task.cancel()
    with pytest.raises(asyncio.CancelledError):await task
    assert cancelled==[source.id]


def test_player_uses_arguments_not_shell(monkeypatch):
    monkeypatch.setattr(Player,"available",staticmethod(lambda:"/usr/bin/mpv"))
    command=Player().command(Stream("https://cdn.test/video.m3u8?x=$(touch-test)",kind="hls",referer="https://site.test/event"))
    assert command[-2]=="--"
    assert "$(touch-test)" in command[-1]
    assert "--referrer=https://site.test/event" in command


@pytest.mark.parametrize('executable,expected',[
    (r'C:\Program Files\mpv\mpv.exe','--referrer=https://site.test/'),
    (r'C:\Program Files\VideoLAN\VLC\vlc.exe','--http-referrer=https://site.test/'),
])
def test_windows_player_paths_select_the_correct_arguments(monkeypatch,executable,expected):
    monkeypatch.setattr(Player,'available',staticmethod(lambda:executable))
    command=Player().command(Stream('https://cdn.test/live.m3u8',kind='hls',referer='https://site.test/'))
    assert command[0]==executable and expected in command


def test_windows_vlc_discovery_does_not_require_path(monkeypatch,tmp_path):
    import termsport.player as module
    folder=tmp_path/'Program Files'
    executable=folder/'VideoLAN/VLC/vlc.exe'
    executable.parent.mkdir(parents=True);executable.touch()
    monkeypatch.delenv('TERMSPORT_PLAYER',raising=False)
    monkeypatch.setattr(module.sys,'platform','win32')
    monkeypatch.setattr(module.shutil,'which',lambda name:None)
    monkeypatch.setenv('ProgramFiles',str(folder))
    assert Player.available()==str(executable)


async def test_streamlink_runs_in_the_installed_python_environment(monkeypatch):
    import sys
    import termsport.resolver as module
    from unittest.mock import AsyncMock
    probe=type('Probe',(),{'returncode':0,'wait':AsyncMock(return_value=0)})()
    process=type('Process',(),{'returncode':0,'communicate':AsyncMock(return_value=(b'https://cdn.test/live.m3u8\n',b''))})()
    spawn=AsyncMock(side_effect=[probe,process])
    monkeypatch.setattr(module.asyncio,'create_subprocess_exec',spawn)
    result=await module.streamlink_url('https://supported.test/watch/1')
    assert result=='https://cdn.test/live.m3u8'
    assert spawn.call_args_list[0].args[:3]==(sys.executable,'-m','streamlink')
    assert '--no-config' in spawn.call_args_list[1].args
