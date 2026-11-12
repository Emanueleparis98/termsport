import asyncio
from unittest.mock import AsyncMock

from textual.widgets import DataTable, Input, Select, Static
from textual.worker import WorkerCancelled

from termsport.app import SourcesScreen, StreamsScreen, TermSportApp
from termsport.models import Event, Source, SourceResult, Stream
from termsport.service import SearchResult


async def wait_for_workers(app):
    # Exclusive search workers can be cancelled by a newer reload; Textual's
    # wait_for_complete raises for those. Wait for all workers to settle but
    # still surface genuine failures.
    while True:
        workers = list(app.workers)
        if not workers:
            return
        results = await asyncio.gather(*(worker.wait() for worker in workers), return_exceptions=True)
        for result in results:
            if isinstance(result, BaseException) and not isinstance(result, WorkerCancelled):
                raise result
        await asyncio.sleep(0)


async def wait_until(pilot, condition):
    async with asyncio.timeout(5):
        while not condition():
            await pilot.pause(0.01)
    await pilot.pause()


class FakeService:
    def __init__(self):
        self.sources=[Source("test","Fonte di prova","https://source.test/",["Live Sports"],adapter="livetv")]
        self.search=AsyncMock(return_value=SearchResult([
            Event("Alpha vs Beta","Tennis","test","Fonte di prova","https://source.test/event/1",live=True),
            Event("Gamma vs Delta","Soccer","test","Fonte di prova","https://source.test/event/2"),
        ],[SourceResult(self.sources[0])]))
        self.choices=AsyncMock(return_value=[Stream("https://cdn.test/live.m3u8","Fonte 1","hls")])
        self.resolve=AsyncMock(return_value=[Stream("https://cdn.test/live.m3u8","Fonte 1","hls")])
        self.close=AsyncMock()


async def test_app_search_filter_sources_and_play(tmp_path,monkeypatch):
    service=FakeService()
    app=TermSportApp(service,tmp_path/'sources.json',autoload=False)
    app.player.available=lambda:'/usr/bin/mpv'
    app.player.play=AsyncMock()
    app.player.stop=AsyncMock()
    async with app.run_test(size=(140,45)) as pilot:
        await pilot.click('#search-button');await wait_for_workers(app);await pilot.pause()
        assert app.query_one('#events',DataTable).row_count==2
        app.query_one('#sport',Select).value='tennis';await pilot.pause()
        assert app.query_one('#events',DataTable).row_count==1
        await pilot.click('#open-streams');await wait_for_workers(app);await pilot.pause()
        assert isinstance(app.screen,StreamsScreen)
        assert app.screen.query_one('#stream-table',DataTable).row_count==1
        await pilot.click('#play-stream');await wait_for_workers(app);await pilot.pause()
        app.player.play.assert_awaited_once()
        await pilot.press('escape');await pilot.pause()
        app.action_sources();await pilot.pause()
        assert isinstance(app.screen,SourcesScreen)
        assert app.screen.query_one('#source-table',DataTable).row_count==1
        await pilot.press('escape')
    service.close.assert_awaited_once()


async def test_failed_resolution_shows_recovery_without_opening_browser(tmp_path,monkeypatch):
    service=FakeService();service.resolve.return_value=[]
    app=TermSportApp(service,tmp_path/'sources.json',autoload=False)
    app.player.available=lambda:'/usr/bin/mpv'
    app.player.play=AsyncMock()
    opened=[];monkeypatch.setattr('webbrowser.open',opened.append)
    async with app.run_test(size=(120,40)) as pilot:
        app.current_event=Event('Test event','tennis','test','Fonte','https://source.test/event/1')
        app.action_streams();await wait_for_workers(app);await pilot.pause()
        await pilot.click('#play-stream');await wait_for_workers(app);await pilot.pause()
        assert 'Nessun flusso diretto' in str(app.screen.query_one('#stream-status',Static).render())
        assert not opened and app.player.play.await_count==0


async def test_empty_narrow_layout_and_invalid_date(tmp_path):
    service=FakeService();service.search.return_value=SearchResult()
    app=TermSportApp(service,tmp_path/'sources.json',autoload=False)
    async with app.run_test(size=(100,35)) as pilot:
        await pilot.click('#search-button');await wait_for_workers(app);await pilot.pause()
        assert app.query_one('#events',DataTable).row_count==0
        app.query_one('#date',Input).value='invalid'
        before=service.search.await_count
        app.action_reload();await wait_for_workers(app);await pilot.pause()
        assert service.search.await_count==before


async def test_invalid_date_stops_loading_after_cancelled_search(tmp_path):
    service=FakeService()
    started=asyncio.Event()
    async def slow_search(**kwargs):
        started.set()
        await asyncio.sleep(10)
        return SearchResult()
    service.search=slow_search
    app=TermSportApp(service,tmp_path/'sources.json',autoload=False)
    async with app.run_test(size=(120,40)) as pilot:
        await pilot.click('#search-button')
        await wait_until(pilot, started.is_set)
        table=app.query_one('#events',DataTable)
        assert table.loading
        app.query_one('#date',Input).value='invalid'
        app.action_reload()
        await wait_until(pilot, lambda: not table.loading)
        await wait_for_workers(app)


async def test_real_service_wrapper_and_protocol_relative_stream_reach_player(tmp_path,respx_mock):
    from termsport.net import Network
    from termsport.service import SportsService
    source=Source('livetv','LiveTV','https://site.test/',adapter='livetv')
    event=Event('Evento di prova','tennis',source.id,source.name,'https://site.test/event/1')
    respx_mock.get(event.url).respond(text='<a href="/webplayer2.php?t=tvope&amp;c=123">Play</a>')
    respx_mock.get('https://site.test/webplayer2.php?t=tvope&c=123').respond(text='<iframe src="https://embed.test/p2p/?id=123"></iframe>')
    respx_mock.get('https://embed.test/p2p/?id=123').respond(text='<script>window.__p2pPlayer={"stream":"//cdn.test/live.m3u8?cst=test"};</script>')
    app=TermSportApp(SportsService(Network(),[source]),tmp_path/'sources.json',autoload=False)
    app.player.available=lambda:'/usr/bin/mpv'
    app.player.play=AsyncMock()
    async with app.run_test(size=(120,40)) as pilot:
        app.current_event=event
        app.action_streams();await wait_for_workers(app);await pilot.pause()
        assert app.screen.query_one('#stream-table',DataTable).row_count==1
        await pilot.click('#play-stream');await wait_for_workers(app);await pilot.pause()
        stream=app.player.play.await_args.args[0]
        assert stream.kind=='hls' and stream.url=='https://cdn.test/live.m3u8?cst=test'
        assert stream.referer=='https://embed.test/p2p/?id=123'


async def test_missing_player_is_reported_before_resolving(tmp_path,monkeypatch):
    service=FakeService()
    app=TermSportApp(service,tmp_path/'sources.json',autoload=False)
    monkeypatch.setattr(app.player,'available',lambda:None)
    async with app.run_test(size=(120,40)) as pilot:
        await pilot.pause()
        assert 'Nessun player' in str(app.query_one('#player-info',Static).render())
        app.current_event=Event('Test event','tennis','test','Fonte','https://source.test/event/1')
        app.action_streams()
        await pilot.pause()
        await wait_for_workers(app)
        app.screen.play_selected()
        await pilot.pause()
        await wait_for_workers(app)
        assert service.resolve.await_count == 0
        assert 'Nessun player' in str(app.screen.query_one('#stream-status',Static).render())


async def test_app_ignores_ui_updates_after_teardown(tmp_path):
    service=FakeService()
    app=TermSportApp(service,tmp_path/'sources.json',autoload=False)
    async with app.run_test(size=(120,40)) as pilot:
        await pilot.pause()
    assert not app.is_running
    app.results=[Event('Alpha Beta','tennis','test','Fonte','https://source.test/event/1')]
    app.render_events()
    app.show_detail()
    service.close.assert_awaited_once()
