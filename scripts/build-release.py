"""Create universal release artifacts. No platform-specific executable required."""
import hashlib
import shutil
import subprocess
import sys
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
    lines = [hashlib.sha256(p.read_bytes()).hexdigest()+"  "+p.name for p in sorted(DIST.iterdir()) if p.is_file()]
    (DIST/"SHA256SUMS").write_text("\n".join(lines)+"\n", encoding="utf-8")
    print(f"Release: {DIST}")


if __name__ == "__main__":
    main()
