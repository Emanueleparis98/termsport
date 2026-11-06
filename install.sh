#!/bin/sh
# Install a verified GitHub release into an isolated uv tool environment.
set -eu
termsport_script_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
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
    set -- "$termsport_script_dir"/termsport-*-py3-none-any.whl
    if [ "$#" -eq 1 ] && [ -f "$1" ]; then
        termsport_wheel=$1
    else
        if ! command -v gh >/dev/null 2>&1; then
            echo 'Scarica wheel e SHA256SUMS dalla release privata accanto a install.sh, oppure installa GitHub CLI ed esegui gh auth login.' >&2
            exit 2
        fi
        gh release download --repo Emanueleparis98/termsport --pattern 'termsport-*-py3-none-any.whl' --pattern SHA256SUMS --dir "$termsport_temp"
        set -- "$termsport_temp"/termsport-*-py3-none-any.whl
        if [ "$#" -ne 1 ] || [ ! -f "$1" ]; then
            echo 'La release deve contenere un solo pacchetto wheel universale.' >&2; exit 2
        fi
        termsport_wheel=$1
    fi
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
