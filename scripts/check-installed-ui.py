"""Run from an unrelated directory to verify a system-installed package."""
import asyncio
import tempfile
from pathlib import Path

from termsport.app import TermSportApp
from termsport.catalog import load_catalog
from termsport.net import Network
from termsport.service import SportsService


async def main():
    with tempfile.TemporaryDirectory() as directory:
        app = TermSportApp(SportsService(Network(), load_catalog()), Path(directory)/"sources.json", autoload=False)
        async with app.run_test(size=(120,40)) as pilot:
            await pilot.pause()
    print("Installed TUI and packaged resources verified")


asyncio.run(main())
