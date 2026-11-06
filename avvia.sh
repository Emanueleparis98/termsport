#!/usr/bin/env bash
set -euo pipefail
termsport_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
cd "$termsport_dir"
if [[ ! -x .venv/bin/python ]]; then
  python3 -m venv .venv
fi
if [[ ! -x .venv/bin/termsport ]]; then
  .venv/bin/python -m pip install -e .
fi
export TERMSPORT_STATE_DIR="$termsport_dir/.local"
exec .venv/bin/python -m termsport "$@"
