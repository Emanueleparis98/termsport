# TermSport

**0.2.0:** installazione come programma da terminale su Linux e Windows.
Dopo l’installazione basta `termsport` da qualsiasi cartella. Sono incluse
le correzioni dei player LiveTV della 0.1.1.

Cerca sport, squadre ed eventi, seleziona una fonte e apri la diretta dal terminale.
Interfaccia Python/Textual ispirata al flusso di lavoro di [Torrra](https://github.com/stabldev/torrra),
con codice indipendente e senza componenti torrent, Jackett, Prowlarr o Real-Debrid.

## Installazione da release

Il pacchetto `termsport-0.2.0-py3-none-any.whl` è comune a Linux e Windows.
Gli installer verificano SHA-256, usano [uv](https://docs.astral.sh/uv/guides/tools/)
per creare l’ambiente isolato e aggiungono il comando al PATH. Se manca, uv viene
installato dal [sito ufficiale Astral](https://docs.astral.sh/uv/getting-started/installation/).
Python 3.13 viene gestito automaticamente da uv; il codice supporta Python 3.11–3.14.
Non si installano pacchetti Python dentro l’ambiente di sistema della distribuzione.

Il repository e le release sono **privati**: occorre un account GitHub autorizzato.
Per il download automatico serve [GitHub CLI](https://cli.github.com/) con `gh auth login`
eseguito una volta. In alternativa scarica dal browser autenticato wheel, installer
del tuo sistema e `SHA256SUMS`, nella stessa cartella.

### Arch Linux / CachyOS

Prerequisiti disponibili nei repository Arch:

```sh
sudo pacman -S --needed uv mpv github-cli
gh auth login
gh release download --repo Emanueleparis98/termsport --pattern install.sh --clobber
sh install.sh
termsport
```

### Altre distribuzioni Linux

Installa mpv o VLC con il gestore della tua distribuzione. Con GitHub CLI autenticato:

```sh
gh release download --repo Emanueleparis98/termsport --pattern install.sh --clobber
sh install.sh
termsport
```

Se hai scaricato manualmente i tre file della release, basta `sh install.sh`.
Non serve una cartella di lavoro specifica per usare il comando dopo l’installazione.

### Windows 10 / 11

Usa PowerShell, preferibilmente dentro Windows Terminal. Installa GitHub CLI e
un player, ad esempio VLC. TermSport riconosce anche VLC nella cartella standard
`Program Files`, senza richiederne l’aggiunta al PATH.

```powershell
gh auth login
gh release download --repo Emanueleparis98/termsport --pattern install.ps1 --clobber
powershell -NoProfile -ExecutionPolicy Bypass -File .\install.ps1
termsport
```

L’opzione `ExecutionPolicy` riguarda soltanto quel processo di installazione.
Se hai scaricato manualmente i tre file della release, esegui solo il comando
PowerShell dell’installer. Se il terminale già aperto non riconosce `termsport`,
chiudilo e riaprilo per caricare il PATH aggiornato.

### Installazione diretta con uv o pipx

Avendo già scaricato il wheel:

```sh
uv tool install --python 3.13 ./termsport-0.2.0-py3-none-any.whl
termsport
```

È supportato anche `pipx install ./termsport-0.2.0-py3-none-any.whl` con Python
3.11 o successivo. Non occorrono uv o pipx per gli avvii successivi: il comando è
semplicemente `termsport`.

Per aggiornare ripeti il download e l’installer della nuova release; le impostazioni
restano nella cartella utente. Per rimuovere il programma: `uv tool uninstall termsport`.

Per verificare l’installazione:

```sh
termsport --version
termsport doctor
```

## Uso

Per il video serve **mpv**, oppure VLC o ffplay, installato nel sistema.
La riproduzione apre una finestra video separata, come è normale per un’app da terminale.

La barra di ricerca filtra sport, squadre, competizioni e fonti. Invio su un evento
mostra i suoi player. Seleziona una fonte e premi **Riproduci**. Un link HLS, DASH o
video pubblico viene aperto nel player; una pagina viene analizzata per trovare le
sorgenti dichiarate. Il pulsante **Browser** apre esplicitamente la pagina originale.

Comandi: `/` cerca, `R` aggiorna, `I` indice siti, `P` flussi, `B` browser,
`S` interrompe il player, `Ctrl+Q` esce. L’uscita interrompe il player avviato dall’app.
La ricerca viene aggiornata ogni cinque minuti; le URL video sono risolte al click,
senza essere salvate come collegamenti permanenti.

## Siti e copertura

Il catalogo iniziale contiene **81 fonti** dalle sezioni **Live TV** e **Live Sports** di
[FMHY](https://fmhy.net/video#live-tv-sports), verificate il 6 novembre 2026, con mirror
raggruppati. **Aggiorna elenco FMHY** recupera l’elenco corrente; se l’aggiornamento
fallisce resta disponibile quello precedente.

- **LiveTV:** lettura delle pagine pubbliche con eventi, sport e indicazione live.
- **TimStreams:** lettura delle API pubbliche per eventi e canali sportivi; fonti VIP
  restano apribili dal sito con il proprio accesso.
- **Matchora e FalconStreams:** lettura delle schede pubbliche degli eventi, con
  sport, competizione e data quando dichiarati. Countdown, punteggi e ticker
  duplicati non diventano eventi separati.
- **Altri siti:** lettore standard di eventi JSON-LD/HTML e directory completa. La
  casella **Tutti i siti** li include nella ricerca di rete. Nell’indice viene indicato
  se hanno restituito eventi, richiedono il browser o non sono raggiungibili.

**Catalogato non significa integrato o funzionante.** Le pagine generate soltanto con
JavaScript, i player proprietari, gli accessi richiesti e le restrizioni del sito
possono impedire ricerca o avvio automatico. Non sono implementati aggiramenti di
DRM, abbonamenti, CAPTCHA o blocchi. Il player non esegue i popup delle pagine web;
non viene garantita l’assenza di pubblicità incorporata nel video.

Gli orari con fuso dichiarato sono convertiti all’ora locale. Gli orari senza fuso
sono indicati come **ora del sito**; eventi senza data attendibile restano visibili,
senza attribuire loro una data inventata. I canali continui non costituiscono un
calendario di singoli eventi. La copertura dipende dai palinsesti pubblicati dalle fonti.

## CLI

```bash
termsport search calcio
termsport search tennis --source livetv --date all
termsport search "Inter" --all-sites --json
termsport sources motori
termsport play ID_EVENTO --source livetv --date all
termsport open 'https://esempio.it/diretta.m3u8'
termsport refresh-sources
termsport doctor
```

Gli ID delle fonti sono mostrati da `sources`. Per `play` usa fonte e data della
ricerca originale. `--browser` apre la pagina invece del player.

Streamlink è incluso nelle dipendenze. L’app lo tenta quando il lettore HTML non trova un flusso. Non usa credenziali
del browser o di altri programmi. I processi vengono avviati tramite argomenti,
senza shell, e i contenuti dei siti sono mostrati come testo inerte.

## Sviluppo e verifica

Il checkout può ancora essere avviato con `./avvia.sh` su Linux. Per uno sviluppo
portabile crea un ambiente virtuale e installa il progetto con `pip install -e '.[dev]'`.

```bash
.venv/bin/python -m pip install -e '.[dev]'
.venv/bin/python -m pytest
```

I test usano rete e player simulati, più prove locali separate quando disponibili.
L’indice viene salvato in `.local` dallo script di avvio, oppure nella cartella
di configurazione XDG per l’installazione come comando. `TERMSPORT_STATE_DIR`
permette di scegliere un’altra cartella. Nessuna chiave personale è necessaria.

Per costruire gli asset di release: installa `build`, poi esegui
`python scripts/build-release.py`. `python scripts/check-install.py` verifica
l’installer reale, il comando installato e la TUI del wheel in un ambiente temporaneo.
Gli installer accettano un wheel locale e disabilitano la modifica del PATH per i test.

Codice sorgente: [Emanueleparis98/termsport](https://github.com/Emanueleparis98/termsport).
Il progetto è autonomo da CineMatch. Ambiente virtuale, cache e pacchetti di build
sono esclusi dal repository; vengono creati localmente quando necessari.
