"""Decode a generated local video through the real player command, headlessly.

Run with .venv/bin/python scripts/check-player.py. Requires ffmpeg and mpv.
No external video, sports broadcast, account or credentials are used.
"""

import asyncio
import shutil
import subprocess
import tempfile
import threading
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from termsport.models import Stream
from termsport.player import Player


class QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, *_):
        pass


async def check(url, log):
    player = Player()
    command = player.command(Stream(url, kind="video"))
    command[1:1] = ["--vo=null", "--ao=null", "--no-terminal", "--log-file="+str(log), "--msg-level=all=v"]
    process = await asyncio.create_subprocess_exec(*command, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL)
    try:
        await asyncio.wait_for(process.wait(), 15)
    except TimeoutError:
        process.kill(); await process.wait(); raise
    text = log.read_text()
    assert process.returncode == 0, "mpv failed"
    assert "VO: [null]" in text, "No decoded video output"
    assert "EOF code: 1" in text, "Playback did not reach EOF"
    print("PASS real mpv command decoded local HTTP video and reached EOF; no external content used.")


def main():
    if not shutil.which("ffmpeg") or not shutil.which("mpv"):
        raise SystemExit("This optional check requires ffmpeg and mpv.")
    with tempfile.TemporaryDirectory(prefix="termsport-player-") as directory:
        root = Path(directory)
        subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i", "testsrc2=size=320x180:rate=25", "-t", "2", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-y", str(root/"test.mp4")], check=True)
        server = ThreadingHTTPServer(("127.0.0.1", 0), partial(QuietHandler, directory=directory))
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            asyncio.run(check(f"http://127.0.0.1:{server.server_port}/test.mp4", root/"mpv.log"))
        finally:
            server.shutdown(); server.server_close(); thread.join(timeout=2)


if __name__ == "__main__":
    main()
