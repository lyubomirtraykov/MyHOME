# MyHOME — Roadmap

Stato al 2026-07-21 · versione corrente **0.9.83** (OWNd **v1.0.10**)

---

## Fatto (baseline consolidata)

Ciclo di hardening e riprogettazione completato e validato sul campo:

- **Connessione robusta**: nessun leak di descrittori, riconnessione con back-off e anti-flood,
  keepalive TCP, watchdog di inattività, grazia di disponibilità (nessun flap delle entità
  durante il riciclo di sessione orario del gateway).
- **Listener a prova di errore**: un frame anomalo o un bug in un handler non uccide più
  l'ascolto del bus.
- **Architettura**: `entry.runtime_data` tipizzato + routing eventi via dispatcher pub/sub
  (eliminata la struttura dati condivisa in `hass.data` e con essa un'intera classe di bug).
- **Qualità**: `ruff` e `mypy` a zero segnalazioni su entrambi i progetti.

Validato con 5 giorni di soak su impianto reale (MH201): zero errori, 113 riconnessioni di
routine tutte silenziose, recupero automatico anche da saturazione degli slot di sessione.

---

## P1 — Eventi scenario (WHO=0) ⭐ priorità massima

**Obiettivo:** usare le placche scenario a muro come telecomandi per **qualsiasi** entità di
Home Assistant (luci Hue, Sonos, automazioni generiche, ...), senza doverle riconfigurare
fisicamente come moduli CEN/CEN+.

**Perché è prioritario:** l'app *Home + Project* consente di creare **scenari**, ma non espone
la configurazione CEN+. Gli scenari sono quindi la via praticabile per intercettare le
pressioni dei pulsanti fisici su questo impianto.

**Punto di partenza favorevole:** OWNd già riconosce e parsa questi frame
(`OWNScenarioEvent`, con `scenario` e `control_panel`). Manca solo il lato integrazione:
oggi finiscono nel ramo "Unsupported message type".

Da implementare:

1. **Dispatch nel gateway** — riconoscere `OWNScenarioEvent` e pubblicare l'evento HA
   `myhome_scenario_event` con payload `scenario` + `control_panel`.
2. **Auto-registrazione dei moduli scenario** nel device registry alla prima pressione
   (nessuna configurazione manuale in `myhome.yaml`).
3. **Device triggers** (`device_trigger.py`) — i pulsanti diventano trigger selezionabili dal
   **menù a tendina dell'UI automazioni** ("Pulsante 1 premuto"), senza scrivere YAML né
   ascoltare eventi grezzi.

**Attenzione al pruning:** i moduli scenario sono dispositivi *stateless* (nessuna entità).
La logica di pulizia del registry va adattata perché non li cancelli a ogni riavvio.

**Test preliminare (prima di scrivere codice):** premere un pulsante scenario e verificare nei
log la comparsa di un frame WHO=0. Se non arriva nulla, l'impianto non ha moduli scenario
attivi e la feature non ha bersaglio.

---

## P2 — Discovery / auto-apprendimento dispositivi

**Obiettivo:** ridurre (o eliminare) la compilazione manuale di `myhome.yaml`.

Da implementare:

1. **Scansione attiva** — interrogare un intervallo di indirizzi per un dato WHO e registrare
   chi risponde con uno **stato valido**.
   ⚠️ Un `ACK` di protocollo **non** è prova di esistenza del dispositivo: senza questo
   accorgimento si popolano decine di dispositivi fantasma.
2. **Sniffing passivo** — ascoltare il bus per un intervallo e dedurre i dispositivi dal
   traffico reale.
3. **Servizi HA**: `scan_bus` (scoperta) ed `export_to_yaml` (generazione/aggiornamento della
   configurazione).

**Vincolo non negoziabile:** la scansione deve rispettare i limiti del gateway MH201 — slot di
sessione limitati e nessun flood di connessioni. Va costruita sopra il nostro layer di
connessione hardened (sessione comando riusata, ritmo controllato), **non** aprendo sessioni
in rapida successione.

---

## P3 — CI su GitHub

**Obiettivo:** validazione automatica a ogni push/PR, senza controlli manuali.

1. **hassfest** — il validatore ufficiale di Home Assistant: verifica `manifest.json`
   (chiavi obbligatorie, versione, requirements, dichiarazioni SSDP) e la struttura
   dell'integrazione.
2. **HACS validate** — verifica che il repository sia conforme ai requisiti HACS
   (release, struttura, `hacs.json`).
3. **Qualità del codice** — eseguire in CI `ruff` e `mypy`, già configurati localmente in
   `pyproject.toml`: impedisce che regressioni di stile/tipi entrino nel repo.

Costo minimo (due workflow YAML), beneficio permanente.

---

## P4 — Estensioni dipendenti dall'hardware

Da valutare **solo se e quando** l'hardware corrispondente è presente in impianto: ognuna
aggiunge superficie di codice da mantenere.

- **Diffusione sonora (WHO=22)** — piattaforma `media_player` per zone/amplificatori.
- **Transizioni software sui dimmer** — fade in/out simulato a step sul bus, per i moduli che
  non supportano nativamente la transizione.
- **Auto-rinnovo del broadcast di potenza istantanea (WHO=18)** — rinnovo periodico
  automatico (~55 min) della richiesta di invio, per non doverlo fare con un'automazione
  oraria manuale.
- **Gestione carichi (WHO=3)** — supporto esplorativo: intercettare gli eventi e aiutare la
  mappatura degli attuatori.

---

## P5 — Polishing residuo

- `CONF_ENTITY` in `const.py` è definita ma non più utilizzata dopo la migrazione a
  `runtime_data`: rimuovibile.
- Valutare un'opzione di configurazione per **non creare** le entità pulsante Lock/Unlock
  (comando WHO=14) per chi non usa quella funzione, oggi disattivabili solo a mano una per una.
- Valutare la sostituzione dei due pulsanti Lock/Unlock con un'unica entità `lock`
  (semanticamente più corretta), tenendo presente che il protocollo **non** consente di
  interrogare lo stato di blocco: sarebbe uno stato ottimistico, non verificato.
