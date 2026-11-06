import argparse
import asyncio
import json
import os
import sys
import webbrowser
from datetime import date
from pathlib import Path

from platformdirs import user_config_path
from rich.console import Console
from rich.table import Table
from rich.text import Text

from . import __version__
from .catalog import FMHY_URL, load_catalog, update_catalog
from .models import Stream, web_url
from .net import FetchError, Network
from .player import Player
from .resolver import stream_kind
from .service import SportsService


def state_path() -> Path:
    return Path(os.environ.get("TERMSPORT_STATE_DIR", user_config_path("termsport")))


def parser():
    root = argparse.ArgumentParser(prog="termsport", description="Cerca eventi sportivi e apri le dirette dal terminale.")
    root.add_argument("--version", action="version", version=f"TermSport {__version__}")
    commands = root.add_subparsers(dest="command")
    commands.add_parser("tui", help="Apri l’interfaccia interattiva (predefinita)")
    search = commands.add_parser("search", help="Cerca eventi e canali")
    search.add_argument("query", nargs="?", default="")
    for command in [search, commands.add_parser("play", help="Apri un evento dal suo ID")]:
        if command is not search:
            command.add_argument("event_id")
            command.add_argument("--stream", type=int, default=1, help="Indice della fonte, a partire da 1")
            command.add_argument("--browser", action="store_true", help="Apri la pagina evento nel browser")
        command.add_argument("--source", default="all", help="ID della fonte, visibile in sources")
        command.add_argument("--all-sites", action="store_true", help="Interroga anche i lettori generici di tutti i siti")
        command.add_argument("--date", default=date.today().isoformat(), help="AAAA-MM-GG; all include ogni data")
    search.add_argument("--sport", default="all")
    search.add_argument("--live", action="store_true")
    search.add_argument("--json", action="store_true")
    sources = commands.add_parser("sources", help="Elenco completo dei siti FMHY")
    sources.add_argument("query", nargs="?", default="")
    sources.add_argument("--json", action="store_true")
    commands.add_parser("refresh-sources", help="Aggiorna l’elenco dalla pagina FMHY")
    commands.add_parser("doctor", help="Verifica installazione e player")
    direct = commands.add_parser("open", help="Risolvi e riproduci un URL pubblico")
    direct.add_argument("url")
    direct.add_argument("--browser", action="store_true")
    return root


async def play_stream(service, stream, console):
    resolved = await service.resolve(stream)
    if not resolved:
        console.print("Nessun flusso diretto disponibile. Apri la pagina con --browser per verificare accesso e player.", style="yellow")
        return 2
    player = Player()
    try:
        await player.play(resolved[0])
        console.print("Player avviato. Ctrl+C interrompe la riproduzione.", style="green")
        await player.process.wait()
        return 0 if player.process.returncode == 0 else 2
    finally:
        await player.stop()


async def command(args, catalog_path, sources, console):
    service = SportsService(Network(), sources)
    try:
        if args.command == "refresh-sources":
            updated = await update_catalog(service.network, catalog_path)
            console.print(f"Catalogo aggiornato: {len(updated)} siti.", style="green")
            return 0
        if args.command == "open":
            url = web_url(args.url, allow_local=True)
            if args.browser:
                webbrowser.open(url)
                return 0
            return await play_stream(service, Stream(url, kind=stream_kind(url)), console)
        if args.source != "all" and not any(s.id == args.source for s in sources):
            raise ValueError("Fonte sconosciuta. Usa termsport sources per trovare l’ID.")
        day = None if args.date == "all" else date.fromisoformat(args.date)
        result = await service.search(getattr(args, "query", ""), getattr(args, "sport", "all"), day,
                                      args.source, all_sites=args.all_sites)
        if args.command == "play":
            event = next((e for e in result.events if e.id == args.event_id), None)
            if not event:
                console.print("Evento non presente nei risultati aggiornati. Ripeti search usando la stessa fonte e data.", style="yellow")
                return 2
            if args.browser:
                webbrowser.open(event.url)
                return 0
            streams = await service.choices(event)
            if not 1 <= args.stream <= len(streams):
                raise ValueError(f"La fonte deve essere fra 1 e {len(streams)}.")
            return await play_stream(service, streams[args.stream-1], console)
        events = [e for e in result.events if not args.live or e.live]
        if args.json:
            print(json.dumps({"events": [e.to_dict() for e in events], "sources": [{"id": r.source.id, "status": r.status, "detail": r.detail} for r in result.sources]}, ensure_ascii=False, indent=2))
        else:
            table = Table(title=f"TermSport · {len(events)} risultati", expand=True)
            for name in ["ID", "Ora", "Sport", "Evento / canale", "Fonte"]:
                table.add_column(name)
            for event in events:
                table.add_row(event.id, Text("LIVE" if event.live else event.start.astimezone().strftime("%d/%m %H:%M") if event.start else event.time_label or "—"),
                              Text(event.sport), Text(event.title), Text(event.source_name))
            console.print(table)
            unavailable = sum(r.status != "ok" for r in result.sources)
            console.print(f"{len(result.sources)} fonti consultate; {unavailable} richiedono verifica nel browser. Gli orari non dichiarati restano indicati con —.", style="dim")
            console.print("Enter e scelta dei flussi: termsport tui · Tutti i siti: termsport sources", style="dim")
        return 0
    finally:
        await service.close()


def main(argv=None):
    root = parser()
    args = root.parse_args(argv)
    console = Console()
    catalog_path = state_path() / "sources.json"
    sources = load_catalog(catalog_path)
    if not args.command or args.command == "tui":
        from .app import TermSportApp
        TermSportApp(SportsService(Network(), sources), catalog_path).run()
        return 0
    if args.command == "doctor":
        console.print(f"TermSport {__version__} · Python {sys.version.split()[0]}")
        console.print(f"Player: {Player.available() or 'non trovato (installa mpv)'}", markup=False)
        console.print(f"Catalogo: {len(sources)} siti · origine {FMHY_URL}", markup=False)
        console.print(f"Impostazioni: {catalog_path.parent}", markup=False)
        return 0 if Player.available() else 2
    if args.command == "sources":
        found = [s for s in sources if args.query.casefold() in (s.name+" "+s.url+" "+s.notes).casefold()]
        if args.json:
            print(json.dumps([s.to_dict() for s in found], ensure_ascii=False, indent=2))
        else:
            table = Table(title=f"FMHY · {len(found)} siti")
            for name in ["ID", "Sito", "Lettura", "Indirizzo"]:
                table.add_column(name)
            for source in found:
                table.add_row(Text(source.id), Text(source.name), "Dedicata" if source.adapter != "generic" else "Standard / browser", Text(source.url))
            console.print(table)
        return 0
    try:
        return asyncio.run(command(args, catalog_path, sources, console))
    except KeyboardInterrupt:
        return 130
    except (FetchError, ValueError, RuntimeError, OSError) as error:
        console.print(str(error) if isinstance(error, (ValueError, FetchError, RuntimeError)) else "Operazione non riuscita. Controlla rete, cartella e player.", style="red", markup=False)
        return 2
