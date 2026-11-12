"""Test the actual release installer in a disposable uv environment on each OS."""
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def main():
    public = "--public" in sys.argv
    wheel = None if public else next((ROOT/"dist/release").glob("termsport-*-py3-none-any.whl"))
    uv = shutil.which("uv") or str(Path(sys.executable).parent / ("uv.exe" if os.name == "nt" else "uv"))
    with tempfile.TemporaryDirectory(prefix="termsport install ") as directory:
        base = Path(directory)
        installer = ROOT/("install.ps1" if os.name == "nt" else "install.sh")
        env = {**os.environ, "TERMSPORT_UV": uv, "UV_TOOL_DIR": str(base/"tools"),
               "UV_TOOL_BIN_DIR": str(base/"bin"), "UV_CACHE_DIR": str(base/"cache"),
               "TERMSPORT_STATE_DIR": str(base/"state")}
        if public:
            manifest = json.load(urllib.request.urlopen("https://github.com/Emanueleparis98/termsport/releases/latest/download/latest.json", timeout=30))
            version = manifest["version"]
            assert re.fullmatch(r"\d+\.\d+\.\d+", version)
            wheel = base/f"termsport-{version}-py3-none-any.whl"
            url = f"https://github.com/Emanueleparis98/termsport/releases/download/v{version}/"
            wheel.write_bytes(urllib.request.urlopen(url+wheel.name, timeout=60).read())
            installer = base/installer.name
            installer.write_bytes(urllib.request.urlopen(url+installer.name, timeout=30).read())
        if os.name == "nt":
            command = ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(installer),
                       "-Python", sys.executable, "-NoPath"]
            wheel_flag = "-Wheel"
        else:
            command = ["sh", str(installer), "--python", sys.executable, "--no-path"]
            wheel_flag = "--wheel"
        subprocess.run(command + ([] if public else [wheel_flag, str(wheel)]), env=env, check=True, timeout=240)
        executable = base/"bin"/("termsport.exe" if os.name == "nt" else "termsport")
        subprocess.run([str(executable), "--version"], env=env, check=True, timeout=30)
        data = json.loads(subprocess.check_output([str(executable), "sources", "--json"], env=env, timeout=30))
        assert len(data) >= 80
        installed_python = base/"tools/termsport"/("Scripts/python.exe" if os.name == "nt" else "bin/python")
        code = '''import asyncio, tempfile
from pathlib import Path
from termsport.app import TermSportApp
from termsport.service import SportsService
from termsport.net import Network
from termsport.catalog import load_catalog
async def run():
 with tempfile.TemporaryDirectory() as folder:
  app=TermSportApp(SportsService(Network(),load_catalog()),Path(folder)/"sources.json",autoload=False)
  async with app.run_test(size=(120,40)) as pilot:
   await pilot.pause()
asyncio.run(run())
'''
        subprocess.run([str(installed_python), "-c", code], env=env, cwd=base, check=True, timeout=30)
        # Reject a damaged release before invoking any installer/dependency download.
        corrupted = base/"bad"/wheel.name
        corrupted.parent.mkdir()
        corrupted.write_bytes(wheel.read_bytes()+b"corrupted")
        (corrupted.parent/"SHA256SUMS").write_text(hashlib.sha256(wheel.read_bytes()).hexdigest()+"  "+wheel.name+"\n")
        bad = command + [wheel_flag, str(corrupted)]
        result = subprocess.run(bad, check=False, env=env, capture_output=True, text=True, timeout=30)
        assert result.returncode != 0 and "Checksum" in result.stdout+result.stderr
        print("PASS: release installed, termsport command, catalog and installed TUI work; corrupted wheel rejected.")


if __name__ == "__main__":
    main()
