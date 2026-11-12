"""Create universal release artifacts. No platform-specific executable required."""
import hashlib
import json
import shutil
import subprocess
import sys
import tarfile
import tomllib
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DIST = ROOT / "dist" / "release"


def main():
    if DIST.exists():
        shutil.rmtree(DIST)
    DIST.mkdir(parents=True)
    subprocess.run([sys.executable, "-m", "build", "--wheel", "--sdist", "--outdir", str(DIST)], cwd=ROOT, check=True)
    for name in ["install.sh", "install.ps1"]:
        shutil.copy2(ROOT/name, DIST/name)
    version = tomllib.loads((ROOT/"pyproject.toml").read_text())["project"]["version"]
    (DIST/"latest.json").write_text(json.dumps({"version": version}, indent=2)+"\n")
    wheel = next(DIST.glob("*.whl"))
    scoop_zip = DIST/f"TermSport-{version}-scoop.zip"
    with zipfile.ZipFile(scoop_zip, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        info = zipfile.ZipInfo(wheel.name, (2020,1,1,0,0,0))
        info.create_system = 3
        info.external_attr = 0o100644 << 16
        archive.writestr(info, wheel.read_bytes())
    scoop = {
        "version": version,
        "description": "Sports search and live stream playback in your terminal",
        "homepage": "https://github.com/Emanueleparis98/termsport",
        "license": "MIT", "depends": "main/uv",
        "url": f"https://github.com/Emanueleparis98/termsport/releases/download/v{version}/{scoop_zip.name}",
        "hash": hashlib.sha256(scoop_zip.read_bytes()).hexdigest(),
        "installer": {"script": [
            '& uv venv --python 3.13 "$dir\\venv"',
            "if ($LASTEXITCODE -ne 0) { throw 'Cannot create TermSport environment' }",
            f'& uv pip install --python "$dir\\venv\\Scripts\\python.exe" "$dir\\{wheel.name}"',
            "if ($LASTEXITCODE -ne 0) { throw 'Cannot install TermSport' }",
        ]},
        "bin": "venv\\Scripts\\termsport.exe",
        "notes": "Install mpv or VLC for video playback. Run: termsport",
        "checkver": {"github": "https://github.com/Emanueleparis98/termsport"},
    }
    bucket = ROOT/"bucket"
    bucket.mkdir(exist_ok=True)
    (bucket/"termsport.json").write_text(json.dumps(scoop, indent=2)+"\n")
    source = DIST/f"termsport-{version}.tar.gz"
    recipe = (ROOT/"packaging/arch/PKGBUILD.in").read_text().replace("@VERSION@", version).replace("@SOURCE_SHA256@", hashlib.sha256(source.read_bytes()).hexdigest())
    arch_dir = ROOT/"build/arch"
    arch_dir.mkdir(parents=True, exist_ok=True)
    (arch_dir/"PKGBUILD").write_text(recipe)
    with tarfile.open(DIST/f"termsport-{version}-arch-build.tar.gz", "w:gz") as archive:
        archive.add(arch_dir/"PKGBUILD", arcname="termsport/PKGBUILD")
    shutil.copy2(arch_dir/"PKGBUILD", DIST/"PKGBUILD")
    lines = [hashlib.sha256(p.read_bytes()).hexdigest()+"  "+p.name for p in sorted(DIST.iterdir()) if p.is_file()]
    (DIST/"SHA256SUMS").write_text("\n".join(lines)+"\n", encoding="utf-8")
    print(f"Release: {DIST}")


if __name__ == "__main__":
    main()
