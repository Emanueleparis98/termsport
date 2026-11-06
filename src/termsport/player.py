import asyncio
import shutil
from urllib.parse import urlsplit

from .models import Stream, web_url


class Player:
    def __init__(self):
        self.process: asyncio.subprocess.Process | None = None

    @staticmethod
    def available() -> str | None:
        return shutil.which("mpv") or shutil.which("vlc") or shutil.which("ffplay")

    def command(self, stream: Stream) -> list[str]:
        executable = self.available()
        if not executable:
            raise RuntimeError("Installa mpv, VLC o ffplay per riprodurre i flussi.")
        url = web_url(stream.url, allow_local=True)
        referer = web_url(stream.referer) if stream.referer else None
        name = executable.rsplit("/", 1)[-1].casefold()
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
            self.process.terminate()
            try:
                await asyncio.wait_for(self.process.wait(), 3)
            except TimeoutError:
                self.process.kill()
                await self.process.wait()
        self.process = None
