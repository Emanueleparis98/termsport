from __future__ import annotations

import asyncio
import webbrowser
from datetime import date, datetime
from pathlib import Path
from urllib.parse import urlsplit

from rich.text import Text
from textual import on, work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Checkbox, DataTable, Footer, Input, Label, Select, Static

from .catalog import update_catalog
from .models import SPORTS, Event, Source, Stream, event_sort, plain
from .net import FetchError
from .player import Player


class SourcesScreen(ModalScreen[str | None]):
    BINDINGS = [("escape", "dismiss(None)", "Chiudi"), ("b", "browser", "Apri sito")]

    def __init__(self, sources: list[Source], statuses: dict[str, str]):
        super().__init__()
        self.sources = sources
        self.statuses = statuses
        self.visible_sources = []

    def compose(self) -> ComposeResult:
        with Vertical(id="source-modal", classes="modal-box"):
            yield Static("SITI LIVE TV / SPORT", classes="modal-title")
            yield Static("Seleziona una fonte per cercare i suoi eventi. ‘Browser’ apre il sito originale.", classes="muted")
            yield Input(placeholder="Filtra per nome o dominio…", id="source-search")
            yield DataTable(id="source-table", cursor_type="row", zebra_stripes=True)
            with Horizontal(classes="modal-actions"):
                yield Button("Cerca qui", variant="primary", id="choose-source")
                yield Button("Browser", id="source-browser")
                yield Button("Chiudi", id="close-source")

    def on_mount(self):
        self.query_one("#source-table", DataTable).add_columns("Sito", "Sezione", "Lettura", "Ultimo controllo")
        self.fill()
        self.query_one("#source-search").focus()

    @on(Input.Changed, "#source-search")
    def fill(self):
        query = self.query_one("#source-search", Input).value.casefold()
        self.visible_sources = [s for s in self.sources if query in (s.name+" "+s.url).casefold()]
        table = self.query_one("#source-table", DataTable)
        table.clear()
        for source in self.visible_sources:
            table.add_row(Text(source.name), Text(" / ".join(source.sections)),
                          "Dedicata" if source.adapter != "generic" else "Standard / browser",
                          self.statuses.get(source.id, "Da verificare"), key=source.id)

    def selected(self) -> Source | None:
        row = self.query_one("#source-table", DataTable).cursor_row
        return self.visible_sources[row] if 0 <= row < len(self.visible_sources) else None

    @on(DataTable.RowSelected, "#source-table")
    @on(Button.Pressed, "#choose-source")
    def choose(self):
        source = self.selected()
        if source:
            self.dismiss(source.id)

    @on(Button.Pressed, "#source-browser")
    def action_browser(self):
        source = self.selected()
        if source:
            webbrowser.open(source.url)

    @on(Button.Pressed, "#close-source")
    def close(self):
        self.dismiss(None)


class StreamsScreen(ModalScreen):
    BINDINGS = [("escape", "dismiss", "Chiudi")]

    def __init__(self, event: Event):
        super().__init__()
        self.event = event
        self.streams: list[Stream] = []

    def compose(self) -> ComposeResult:
        with Vertical(id="streams-modal", classes="modal-box"):
            yield Static(Text(self.event.title), classes="modal-title")
            yield Static(Text(self.event.source_name+" · "+self.event.sport), classes="muted")
            yield Static("Cerco i player disponibili…", id="stream-status", markup=False)
            yield DataTable(id="stream-table", cursor_type="row", zebra_stripes=True)
            with Horizontal(classes="modal-actions"):
                yield Button("Riproduci", id="play-stream", variant="primary")
                yield Button("Apri evento nel browser", id="event-browser")
                yield Button("Chiudi", id="close-streams")
            yield Static("L’avvio diretto dipende dalla fonte. Accessi e restrizioni restano quelli del sito.", classes="muted")

    def on_mount(self):
        self.query_one("#stream-table", DataTable).add_columns("Fonte", "Tipo", "Host")
        self.load_choices()

    def on_unmount(self):
        # Closing the modal must not leave background work running or start a
        # player after the user has already returned to the event list.
        self.workers.cancel_group(self, "streams")
        self.workers.cancel_group(self, "play")

    @work(exclusive=True, group="streams")
    async def load_choices(self):
        try:
            streams = await self.app.service.choices(self.event)
            if not self.is_mounted:
                return
            self.streams = streams
            table = self.query_one("#stream-table", DataTable)
            for index, stream in enumerate(self.streams):
                table.add_row(Text(stream.label), stream.kind.upper() if stream.kind != "page" else "Pagina", Text(urlsplit(stream.url).hostname or ""), key=str(index))
            self.query_one("#stream-status", Static).update(f"{len(self.streams)} fonti. Le pagine richiedono un tentativo di estrazione.")
            table.focus()
        except (FetchError, ValueError, TypeError, KeyError, AttributeError):
            if self.is_mounted:
                self.query_one("#stream-status", Static).update("Non riesco a leggere i player. Puoi verificare l’evento nel browser.")

    @on(DataTable.RowSelected, "#stream-table")
    @on(Button.Pressed, "#play-stream")
    def play_selected(self):
        row = self.query_one("#stream-table", DataTable).cursor_row
        if 0 <= row < len(self.streams):
            self.resolve_and_play(self.streams[row])

    @work(exclusive=True, group="play")
    async def resolve_and_play(self, stream: Stream):
        status = self.query_one("#stream-status", Static)
        status.update("Verifico la sorgente e preparo il player…")
        button = self.query_one("#play-stream", Button)
        button.disabled = True
        try:
            resolved = await self.app.service.resolve(stream)
            if not self.is_mounted:
                return
            if not resolved:
                status.update("Nessun flusso diretto estraibile. Il sito può richiedere il browser, un accesso o un player non supportato.")
                return
            if len(resolved) > 1:
                self.streams = resolved
                table = self.query_one("#stream-table", DataTable)
                table.clear()
                for index, item in enumerate(resolved):
                    table.add_row(Text(item.label), item.kind.upper(), Text(urlsplit(item.url).hostname or ""), key=str(index))
                status.update("Più flussi disponibili: seleziona quello da avviare.")
                return
            if not self.is_mounted:
                return
            await self.app.player.play(resolved[0])
            if not self.is_mounted:
                await self.app.player.stop()
                return
            status.update("Player avviato. Verifica il video nella finestra di riproduzione; S lo interrompe dalla schermata principale.")
            self.app.query_one("#playback", Static).update("● Player attivo · S interrompi")
        except (RuntimeError, FetchError, ValueError, OSError, TimeoutError) as error:
            if self.is_mounted:
                status.update(str(error) if isinstance(error, (RuntimeError, FetchError)) else "Impossibile avviare questa fonte. Puoi verificarla nel browser.")
        finally:
            if self.is_mounted:
                button.disabled = False

    @on(Button.Pressed, "#event-browser")
    def browser(self):
        row = self.query_one("#stream-table", DataTable).cursor_row
        # Open the selected web player, otherwise the actual event; never a media CDN.
        url = self.streams[row].url if 0 <= row < len(self.streams) and self.streams[row].kind == "page" else self.event.url
        webbrowser.open(url)

    @on(Button.Pressed, "#close-streams")
    def close(self):
        self.dismiss()


class TermSportApp(App):
    TITLE = "TermSport"
    SUB_TITLE = "Trova l’evento. Scegli la fonte. Guarda la diretta."
    CSS_PATH = "app.tcss"
    BINDINGS = [
        Binding("ctrl+q", "quit", "Esci"), Binding("slash", "search_focus", "Cerca"),
        Binding("r", "reload", "Ricarica"), Binding("i", "sources", "Siti"),
        Binding("p", "streams", "Flussi"), Binding("b", "browser", "Browser"), Binding("s", "stop", "Stop"),
    ]

    def __init__(self, service, catalog_path: Path, *, autoload=True):
        super().__init__()
        self.service = service
        self.catalog_path = catalog_path
        self.player = Player()
        self.autoload = autoload
        self.results = []
        self.events = []
        self.current_event = None
        self.statuses = {}
        self.search_generation = 0

    def compose(self) -> ComposeResult:
        with Horizontal(id="masthead"):
            yield Static("[bold]TERM[/bold][#a8ee78 bold]SPORT[/]", id="brand")
            yield Static("IL TUO SPORT, DAL TERMINALE", id="tagline")
            yield Static("LIVE DESK  /  01", id="edition")
        with Horizontal(id="workspace"):
            with Vertical(id="sidebar"):
                yield Label("ESPLORA", classes="eyebrow")
                yield Label("Sport", classes="field-label")
                yield Select([("Tutti gli sport", "all"), *[(s.capitalize(), s) for s in SPORTS]], value="all", allow_blank=False, id="sport")
                yield Label("Fonte", classes="field-label")
                yield Select([("Fonti integrate", "all"), *[(s.name, s.id) for s in self.service.sources]], value="all", allow_blank=False, id="source")
                yield Label("Data · vuota = tutte", classes="field-label")
                yield Input(value=date.today().isoformat(), placeholder="AAAA-MM-GG", id="date")
                yield Checkbox("Solo in diretta", id="live-only")
                yield Checkbox("Tutti i siti", id="all-sites")
                yield Static("‘Tutti i siti’ estende la ricerca alle pagine pubbliche dell’elenco FMHY.", classes="sidebar-note")
                yield Button("Indice dei siti", id="sources")
                yield Button("Aggiorna elenco FMHY", id="update-catalog")
                yield Static(f"{len(self.service.sources)} siti nel catalogo", id="catalog-count", classes="sidebar-note")
                yield Static("mpv / VLC / ffplay\nNessun torrent", id="player-info")
            with Vertical(id="content"):
                yield Label("CERCA LA PROSSIMA DIRETTA", classes="eyebrow")
                with Horizontal(id="search-bar"):
                    yield Input(placeholder="Sport, squadra, competizione…", id="search")
                    yield Button("Cerca", variant="primary", id="search-button")
                with Horizontal(id="summary"):
                    yield Static("Eventi", id="result-count")
                    yield Static("", id="playback")
                yield DataTable(id="events", cursor_type="row", zebra_stripes=True)
                with Vertical(id="detail"):
                    yield Static("Seleziona un evento", id="event-title", markup=False)
                    yield Static("Le fonti con orario non dichiarato restano visibili; gli orari del sito non vengono convertiti per ipotesi.", id="event-meta", markup=False)
                    with Horizontal(id="detail-actions"):
                        yield Button("Flussi  ↗", variant="primary", id="open-streams")
                        yield Button("Apri evento nel browser", id="open-browser")
                        yield Button("Interrompi player", id="stop-player")
                yield Static("Pronto. Premi Cerca per aggiornare gli eventi.", id="status", markup=False)
        yield Footer()

    def on_mount(self):
        self.theme = "textual-dark"
        table = self.query_one("#events", DataTable)
        for label, width in [("Stato", 7), ("Ora", 12), ("Sport", 12), ("Evento / canale", 49), ("Fonte", 13)]:
            table.add_column(label, width=width)
        if self.autoload:
            self.load_events()
            self.set_interval(300, self.action_reload)

    @on(Button.Pressed, "#search-button")
    @on(Input.Submitted, "#search")
    @on(Input.Submitted, "#date")
    def action_reload(self):
        self.load_events()

    def action_search_focus(self):
        self.query_one("#search", Input).focus()

    @work(exclusive=True, group="search")
    async def load_events(self):
        self.search_generation += 1
        generation = self.search_generation
        text = self.query_one("#date", Input).value.strip()
        try:
            day = date.fromisoformat(text) if text else None
        except ValueError:
            self.notify("Data non valida. Usa AAAA-MM-GG oppure lascia vuoto.", severity="warning")
            return
        table = self.query_one("#events", DataTable)
        table.loading = True
        source_id = self.query_one("#source", Select).value
        all_sites = self.query_one("#all-sites", Checkbox).value
        self.query_one("#status", Static).update("Aggiorno le fonti…")

        def progress(result, done, total):
            if generation == self.search_generation:
                self.query_one("#status", Static).update(f"{done}/{total} fonti · {result.source.name} · {len(result.events)} risultati")
        try:
            result = await self.service.search(day=day, source_id=source_id, all_sites=all_sites, progress=progress)
            if generation != self.search_generation:
                return
            self.results = result.events
            self.statuses = {r.source.id: {"ok": "Letto", "browser": "Browser", "unavailable": "Non disponibile"}[r.status] for r in result.sources}
            self.render_events()
            errors = sum(r.status == "unavailable" for r in result.sources)
            suffix = " · ricerca parziale" if getattr(result, "partial", False) else ""
            self.query_one("#status", Static).update(f"Aggiornato alle {datetime.now():%H:%M} · {len(result.sources)} fonti consultate · {errors} non disponibili{suffix} · orari non dichiarati indicati con —")
        except asyncio.CancelledError:
            raise
        except Exception:
            self.query_one("#status", Static).update("Ricerca interrotta. Riprova o scegli una singola fonte dall’indice.")
        finally:
            if generation == self.search_generation:
                table.loading = False

    @on(Input.Changed, "#search")
    @on(Select.Changed, "#sport")
    @on(Checkbox.Changed, "#live-only")
    def render_events(self):
        if not self.is_mounted:
            return
        query = self.query_one("#search", Input).value
        sport = self.query_one("#sport", Select).value
        live = self.query_one("#live-only", Checkbox).value
        self.events = [e for e in self.results if e.matches(query, sport) and (not live or e.live)]
        table = self.query_one("#events", DataTable)
        table.clear()
        for event in self.events:
            status = Text("● LIVE", style="#a8ee78") if event.live else Text("CANALE" if event.kind == "channel" else "EVENTO", style="#8e9aa8")
            when = event.start.astimezone().strftime("%d/%m %H:%M") if event.start else event.time_label.split(" · ")[0] if event.time_label else "—"
            table.add_row(status, Text(when), Text(event.sport.capitalize()), Text(event.title), Text(event.source_name), key=event.id)
        self.query_one("#result-count", Static).update(f"{len(self.events)} RISULTATI")
        self.current_event = self.events[0] if self.events else None
        self.show_detail()

    @on(DataTable.RowHighlighted, "#events")
    def highlight(self, event: DataTable.RowHighlighted):
        self.current_event = next((e for e in self.events if e.id == event.row_key.value), None)
        self.show_detail()

    def show_detail(self):
        event = self.current_event
        self.query_one("#event-title", Static).update(event.title if event else "Nessun evento selezionato")
        self.query_one("#event-meta", Static).update(" · ".join(filter(None, [event.source_name, event.sport, event.competition, event.time_label])) if event else "Prova un altro sport, svuota la ricerca o consulta l’indice dei siti. Le fonti non disponibili sono indicate nell’indice.")
        self.query_one("#open-streams", Button).disabled = event is None
        self.query_one("#open-browser", Button).disabled = event is None

    @on(DataTable.RowSelected, "#events")
    @on(Button.Pressed, "#open-streams")
    def action_streams(self):
        if self.current_event:
            self.push_screen(StreamsScreen(self.current_event))

    @on(Button.Pressed, "#open-browser")
    def action_browser(self):
        if self.current_event:
            webbrowser.open(self.current_event.url)

    @on(Button.Pressed, "#sources")
    def action_sources(self):
        def choose(source_id):
            if source_id:
                self.query_one("#source", Select).value = source_id
                self.action_reload()
        self.push_screen(SourcesScreen(self.service.sources, self.statuses), choose)

    @on(Button.Pressed, "#update-catalog")
    @work(exclusive=True, group="catalog")
    async def refresh_catalog(self):
        try:
            sources = await update_catalog(self.service.network, self.catalog_path)
            self.service.sources = sources
            selector = self.query_one("#source", Select)
            current = selector.value
            selector.set_options([("Fonti integrate", "all"), *[(s.name, s.id) for s in sources]])
            selector.value = current if any(s.id == current for s in sources) else "all"
            self.query_one("#catalog-count", Static).update(f"{len(sources)} siti nel catalogo")
            clear_cache = getattr(self.service, "clear_cache", None)
            if clear_cache:
                clear_cache()
            self.notify("Elenco FMHY aggiornato.")
        except (FetchError, ValueError, OSError):
            self.notify("Non riesco ad aggiornare FMHY. L’elenco precedente resta disponibile.", severity="warning")

    @on(Button.Pressed, "#stop-player")
    @work(exclusive=True, group="stop")
    async def action_stop(self):
        await self.player.stop()
        self.query_one("#playback", Static).update("Player fermato")

    async def on_unmount(self):
        await self.player.stop()
        await self.service.close()
