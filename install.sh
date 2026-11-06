#!/bin/sh
# Install a verified GitHub release into an isolated uv tool environment.
set -eu
termsport_wheel=
termsport_python=3.13
termsport_modify_path=1
while [ "$#" -gt 0 ]; do
    case "$1" in
        --wheel) termsport_wheel=$2; shift 2 ;;
        --python) termsport_python=$2; shift 2 ;;
        --no-path) termsport_modify_path=0; shift ;;
        --help) echo 'Uso: sh install.sh [--wheel FILE] [--python VERSIONE] [--no-path]'; exit 0 ;;
        *) echo "Opzione sconosciuta: $1" >&2; exit 2 ;;
    esac
done
termsport_temp=$(mktemp -d)
trap 'rm -rf "$termsport_temp"' EXIT HUP INT TERM
if [ -z "$termsport_wheel" ]; then
    termsport_base=https://github.com/Emanueleparis98/termsport/releases
    curl --proto '=https' --tlsv1.2 -fsSL "$termsport_base/latest/download/latest.json" -o "$termsport_temp/latest.json"
    termsport_version=$(sed -n 's/^[[:space:]]*"version":[[:space:]]*"\([0-9.]*\)".*/\1/p' "$termsport_temp/latest.json")
    case "$termsport_version" in ''|*[!0-9.]*) echo 'Versione della release non valida.' >&2; exit 2 ;; esac
    if ! printf '%s\n' "$termsport_version" | grep -Eq '^[0-9]+\.[0-9]+\.[0-9]+$'; then
        echo 'Versione della release non valida.' >&2; exit 2
    fi
    termsport_wheel_name="termsport-$termsport_version-py3-none-any.whl"
    curl --proto '=https' --tlsv1.2 -fsSL "$termsport_base/download/v$termsport_version/$termsport_wheel_name" -o "$termsport_temp/$termsport_wheel_name"
    curl --proto '=https' --tlsv1.2 -fsSL "$termsport_base/download/v$termsport_version/SHA256SUMS" -o "$termsport_temp/SHA256SUMS"
    termsport_wheel="$termsport_temp/$termsport_wheel_name"
fi
termsport_wheel_dir=$(CDPATH= cd -- "$(dirname -- "$termsport_wheel")" && pwd)
termsport_wheel_name=$(basename -- "$termsport_wheel")
termsport_wheel="$termsport_wheel_dir/$termsport_wheel_name"
termsport_checksums="$termsport_wheel_dir/SHA256SUMS"
if [ ! -f "$termsport_checksums" ]; then
    echo 'Manca SHA256SUMS accanto al pacchetto. Scaricalo dalla stessa release.' >&2; exit 2
fi
termsport_expected=$(awk -v name="$termsport_wheel_name" '$2 == name {print $1}' "$termsport_checksums")
termsport_actual=$(sha256sum "$termsport_wheel" | awk '{print $1}')
if [ -z "$termsport_expected" ] || [ "$termsport_expected" != "$termsport_actual" ]; then
    echo 'Checksum del pacchetto non valido; installazione annullata.' >&2; exit 2
fi
termsport_uv=${TERMSPORT_UV:-}
if [ -z "$termsport_uv" ]; then
    termsport_uv=$(command -v uv || true)
fi
if [ -z "$termsport_uv" ] && [ -x "${HOME}/.local/bin/uv" ]; then
    termsport_uv="${HOME}/.local/bin/uv"
fi
if [ -z "$termsport_uv" ]; then
    echo 'Installo uv dal sito ufficiale Astral…'
    curl --proto '=https' --tlsv1.2 -fsSL https://astral.sh/uv/install.sh -o "$termsport_temp/uv-install.sh"
    UV_NO_MODIFY_PATH=1 sh "$termsport_temp/uv-install.sh"
    termsport_uv="${HOME}/.local/bin/uv"
fi
"$termsport_uv" tool install --python "$termsport_python" --force "$termsport_wheel"
if [ "$termsport_modify_path" -eq 1 ]; then
    "$termsport_uv" tool update-shell
fi
termsport_bin=$("$termsport_uv" tool dir --bin)
"$termsport_bin/termsport" --version
echo 'Installazione completata. Avvia con: termsport'
echo 'Se il comando non viene riconosciuto, riapri il terminale per aggiornare PATH.'
