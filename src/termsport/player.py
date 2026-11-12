import asyncio
import ntpath
import os
import shutil
import sys
from pathlib import Path

from .models import Stream, web_url


class Player:
    def __init__(self):
        self.process: asyncio.subprocess.Process | None = None

    @staticmethod
    def available() -> str | None:
        explicit = os.environ.get("TERMSPORT_PLAYER")
        if explicit and Path(explicit).is_file() and (os.name == "nt" or os.access(explicit, os.X_OK)):
            return explicit
        found = shutil.which("mpv") or shutil.which("vlc") or shutil.which("ffplay")
        if found:
            return found
        candidates = []
        if sys.platform == "win32":
            # VLC and mpv installers do not always add themselves to PATH.
            for variable, relative in [
                ("ProgramFiles", "mpv/mpv.exe"),
                ("ProgramFiles(x86)", "mpv/mpv.exe"),
                ("ProgramFiles", "mpv.net/mpvnet.exe"),
                ("LOCALAPPDATA", "Programs/mpv/mpv.exe"),
                ("LOCALAPPDATA", "Programs/mpv.net/mpvnet.exe"),
                ("ProgramFiles", "VideoLAN/VLC/vlc.exe"),
                ("ProgramFiles(x86)", "VideoLAN/VLC/vlc.exe"),
                ("USERPROFILE", "scoop/shims/mpv.exe"),
                ("USERPROFILE", "scoop/apps/mpv/current/mpv.exe"),
                ("USERPROFILE", "scoop/shims/vlc.exe"),
                ("USERPROFILE", "scoop/apps/vlc/current/vlc.exe"),
            ]:
                if os.environ.get(variable):
                    candidates.append(Path(os.environ[variable]) / relative)
        elif sys.platform == "darwin":
            candidates.extend([
                Path("/Applications/VLC.app/Contents/MacOS/VLC"),
                Path("/Applications/mpv.app/Contents/MacOS/mpv"),
            ])
        else:
            candidates.extend([
                Path("/snap/bin/mpv"),
                Path("/snap/bin/vlc"),
                Path("/var/lib/flatpak/exports/bin/io.mpv.Mpv"),
                Path("/var/lib/flatpak/exports/bin/org.videolan.VLC"),
            ])
            # WSL can launch a Windows player even when no Linux mpv is installed.
            try:
                if "microsoft" in Path("/proc/version").read_text(encoding="utf-8", errors="replace").casefold():
                    candidates.extend([
                        Path("/mnt/c/Program Files/mpv/mpv.exe"),
                        Path("/mnt/c/Program Files (x86)/mpv/mpv.exe"),
                        Path("/mnt/c/Program Files/VideoLAN/VLC/vlc.exe"),
                        Path("/mnt/c/Program Files (x86)/VideoLAN/VLC/vlc.exe"),
                    ])
            except OSError:
                pass
        for candidate in candidates:
            if candidate.is_file():
                return str(candidate)
        return None

    def command(self, stream: Stream) -> list[str]:
        executable = self.available()
        if not executable:
            raise RuntimeError("Installa mpv, VLC o ffplay per riprodurre i flussi.")
        url = web_url(stream.url, allow_local=True)
        referer = web_url(stream.referer) if stream.referer else None
        name = ntpath.basename(executable).casefold()
        if name.startswith("mpv"):
            return [executable, "--no-config", "--force-window=yes", "--title=TermSport", "--cache=yes", "--ytdl=no",
                    *(["--referrer="+referer] if referer else []), "--", url]
        if name.startswith("vlc"):
            return [executable, "--no-video-title-show", *(["--http-referrer="+referer] if referer else []), "--", url]
        return [executable, "-loglevel", "error", "-window_title", "TermSport", *(["-referer", referer] if referer else []), "-i", url]

    async def play(self, stream: Stream):
        if stream.kind == "page":
            raise RuntimeError("Questa è una pagina web, non un flusso diretto.")
        command = self.command(stream)
        await self.stop()
        self.process = await asyncio.create_subprocess_exec(*command, stdin=asyncio.subprocess.DEVNULL,
                                                           stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL)
        try:
            await asyncio.sleep(0.8)
        except asyncio.CancelledError:
            await self.stop()
            raise
        if self.process.returncode is not None:
            raise RuntimeError("Il player si è chiuso: sorgente non disponibile, formato o accesso non supportato.")

    async def stop(self):
        if self.process and self.process.returncode is None:
            try:
                self.process.terminate()
            except ProcessLookupError:
                pass
            try:
                await asyncio.wait_for(self.process.wait(), 3)
            except TimeoutError:
                try:
                    self.process.kill()
                except ProcessLookupError:
                    pass
                await self.process.wait()
        self.process = None
