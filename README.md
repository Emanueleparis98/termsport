# TermSport

Cerca sport, squadre ed eventi, seleziona una fonte e apri la diretta dal terminale.
Interfaccia Python/Textual ispirata al flusso di lavoro di [Torrra](https://github.com/stabldev/torrra),
con codice indipendente e senza componenti torrent, Jackett, Prowlarr o Real-Debrid.

## Avvio

```bash
cd "/home/emanuelep/Scrivania/Progetti AI/TermSPort"
./avvia.sh
```

Python 3.11 o successivo. Il primo avvio crea un ambiente virtuale locale se manca.
Per il video serve **mpv**, oppure VLC o ffplay. Nel computer di sviluppo mpv è già presente.
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
./avvia.sh search calcio
./avvia.sh search tennis --source livetv --date all
./avvia.sh search "Inter" --all-sites --json
./avvia.sh sources motori
./avvia.sh play ID_EVENTO --source livetv --date all
./avvia.sh open 'https://esempio.it/diretta.m3u8'
./avvia.sh refresh-sources
./avvia.sh doctor
```

Gli ID delle fonti sono mostrati da `sources`. Per `play` usa fonte e data della
ricerca originale. `--browser` apre la pagina invece del player.

Streamlink è incluso nelle dipendenze. L’app lo tenta quando il lettore HTML non trova un flusso. Non usa credenziali
del browser o di altri programmi. I processi vengono avviati tramite argomenti,
senza shell, e i contenuti dei siti sono mostrati come testo inerte.

## Sviluppo e verifica

```bash
.venv/bin/python -m pip install -e '.[dev]'
.venv/bin/python -m pytest
```

I test usano rete e player simulati, più prove locali separate quando disponibili.
L’indice viene salvato in `.local` dallo script di avvio, oppure nella cartella
di configurazione XDG per l’installazione come comando. `TERMSPORT_STATE_DIR`
permette di scegliere un’altra cartella. Nessuna chiave personale è necessaria.

Il progetto è locale e autonomo da CineMatch. Non è stato creato o pubblicato un
nuovo repository GitHub. Per associare questa chat alla cartella anche nella barra
laterale di Codex, aggiungi `TermSPort` come progetto e sposta qui la chat: la sola
creazione dei file non modifica l’associazione del progetto nell’app.
