# MyHOME — Roadmap

Stato al 2026-08-07 · stabile **0.9.86** (OWNd **v1.0.10**) · in validazione
**0.9.87-beta** (OWNd **v1.0.11-beta**)

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

## 🧪 In validazione — 0.9.87-beta / OWNd 1.0.11-beta

Questa beta aggiunge il supporto ai frame di termoregolazione osservati su un impianto
BTicino 3550 / MyHomeServer1 e la relativa migrazione dei dati di configurazione:

- dimensioni 12 e 14 mantenute indipendenti (stato locale/effective e stato centrale);
- dimensione 13 esposta anche come valore grezzo, incluso lo stato `local_override`;
- dimensione 19 richiesta esplicitamente durante l'aggiornamento completo;
- migrazione compatibile del produttore della centrale dalla precedente lista al valore
  scalare atteso dal modello dati corrente.

La copertura automatica comprende sei test in OWNd e sei test in MyHOME; Ruff, mypy e tutti
i test risultano puliti localmente. Prima della promozione a OWNd v1.0.11 / MyHOME 0.9.87
restano la validazione sul gateway 3550 che ha prodotto i frame e un breve soak di regressione
sull'impianto MH201.

Il rafforzamento *fail-closed* della negoziazione autenticata resta volutamente fuori da
questa beta: interessa direttamente l'accesso al gateway e sarà sviluppato e verificato in
una beta separata.

---

## ✅ Fatto in 0.9.86 — Device trigger per CEN / CEN+ (validati sul campo)

I pulsanti a muro CEN/CEN+ sono ora usabili **dall'interfaccia automazioni**, senza YAML:
il controllo si registra come dispositivo alla prima pressione (scoperta per attivazione) ed
espone due tendine — cosa è successo (pressione breve / prolungata / rilascio) e quale
pulsante (1-8). Gli eventi `myhome_cen_event` / `myhome_cenplus_event` includono ora anche
il `mac` del gateway.

Verificato sul campo: CEN+ oggetto 1, pulsante 1 (frame `*25*21#1*21##`).

**Nota d'uso:** durante una pressione prolungata il bus ripete il frame "ancora premuto", che
genera più eventi `long_press` consecutivi. Per un'azione singola usare il trigger di
**rilascio**; il `long_press` ripetuto è invece utile per regolazioni progressive
(es. dimmerare finché si tiene premuto).

**Soak 24-29 luglio (5 giorni, 6.382 righe di log MyHOME):** zero errori, zero traceback,
zero eventi scartati dai guard. 128 riconnessioni tutte di routine (media 56.7 min, nessuna
fuori dal range atteso), zero give-up, zero periodi di indisponibilità, nessun buco di
attività. 11 auto-riparazioni della sessione comando risolte tutte al primo tentativo
(~50 ms). Controllo CEN+ sopravvissuto al riavvio: il fix del pruning dei dispositivi
stateless è confermato.

---

## P1a — Scenari memorizzati lanciabili da Home Assistant

**Obiettivo:** esporre gli scenari memorizzati nel gateway come entità `scene` di Home
Assistant, così da poterli attivare dalla UI, dalle automazioni e dagli assistenti vocali —
mantenendo la programmazione dello scenario dove l'utente la crea (app/MyHOME_Suite) e usando
HA solo come innesco.

**Punto di partenza molto favorevole: OWNd non richiede alcuna modifica.** Verificato che
funzionano già entrambe le direzioni:

- **lancio**: il frame `*17*1*N##` è già valido e accettato (oggi funziona anche solo col
  servizio `myhome.send_message`, senza codice nuovo);
- **feedback**: gli eventi WHO=17 sono già interpretati (`OWNSceneEvent`: started / stopped /
  enabled / disabled) e producono un `entity` id (`17-N`) che si innesta direttamente nel
  routing a dispatcher esistente.

Da implementare:

1. **Piattaforma `scene`** — uno scenario configurato in `myhome.yaml` diventa un'entità che
   invia il comando di attivazione.
2. **Dispatch degli eventi WHO=17** nel gateway, per il feedback di stato (oggi finirebbero
   nel ramo "Unsupported message type").

**Da verificare prima di scrivere codice** (test immediato, senza modifiche): inviare
`*17*1*N##` con `myhome.send_message` e osservare se lo scenario parte e se compare un evento
`Scene N is started`. Sull'impianto di riferimento (MH201, che da catalogo memorizza fino a 50
scenari) **non è ancora stato osservato un solo frame WHO=17 o WHO=0**: va confermato che gli
scenari creati dall'app siano effettivamente indirizzabili come scene WHO=17, altrimenti
occorre prima capire dove sono memorizzati.

**Nota:** l'esposizione dei *programmi del riscaldamento* come entità `select` (programma
caldo/freddo) è una funzione affine ma distinta, subordinata alla presenza di hardware di
termoregolazione: vedi P5.

---

## P1b — Device trigger per i comandi di gruppo / area / generale

**Obiettivo:** stessa ergonomia dei CEN+, estesa ai pulsanti configurati come **comandi di
gruppo** (o area/generale), che oggi generano eventi utilizzabili solo scrivendo YAML.

Questi comandi sono già riconosciuti e pubblicati come eventi
(`myhome_group_automation_event`, `myhome_area_automation_event`,
`myhome_general_automation_event` e i corrispettivi per le luci), ma:

1. non vengono loggati (nessuna traccia a INFO: la diagnostica è cieca);
2. non compaiono come dispositivi, quindi non sono selezionabili dall'UI automazioni.

Da implementare: logging coerente con gli altri eventi + registrazione come dispositivi
(alla prima pressione, come per i CEN+) + device trigger con l'azione come sottotipo
(apri / chiudi / stop, acceso / spento).

**Bersaglio reale già osservato:** un pulsante che comanda il gruppo 1 delle tapparelle
(`*2*0*#1##` seguito da `*2*2*#1##`).

---

## P2 — Moduli scenario (WHO=0)

**Cosa sono:** i *moduli/centraline scenario* (es. programmatori scenari) che annunciano sul
bus "è stato lanciato lo scenario N dal pannello X". Sono una **funzione distinta** dai
pulsanti CEN/CEN+: non li sostituiscono e non ne sono sostituiti.

**Punto di partenza favorevole:** OWNd già riconosce e parsa questi frame
(`OWNScenarioEvent`, con `scenario` e `control_panel`). Manca solo il lato integrazione: oggi
finiscono nel ramo "Unsupported message type".

Da implementare (stesso schema già collaudato con i CEN+):

1. **Dispatch nel gateway** — pubblicare l'evento HA `myhome_scenario_event` con payload
   `scenario` + `control_panel` (+ `mac`).
2. **Auto-registrazione** del modulo nel device registry alla prima attivazione.
3. **Device trigger** per i singoli scenari.

**Perché non è in cima:** sull'impianto di riferimento **non è mai stato osservato un solo
frame WHO=0** — non c'è hardware su cui verificare l'implementazione. Da riprendere se e
quando un modulo scenario entra in impianto: il test è immediato (attivare uno scenario e
cercare un frame WHO=0 nei log).

---

## P3 — Discovery / auto-apprendimento dispositivi

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

## ✅ Fatto — CI su GitHub

Validazione automatica a ogni push/PR (più un check giornaliero programmato):

1. **hassfest** (`.github/workflows/hassfest.yml`) — già presente nel repository, verifica
   `manifest.json` e la struttura dell'integrazione. Aggiornata solo la versione di
   `actions/checkout`.
2. **HACS validate** (`.github/workflows/validate.yml`) — già presente, verifica la
   conformità ai requisiti HACS. Stesso aggiornamento.
3. **Qualità del codice** (`.github/workflows/lint.yml`) — esegue `ruff`, `mypy` e i test
   unitari sulla stessa configurazione di `pyproject.toml` usata localmente. `mypy` e i test
   installano `homeassistant` (per risolvere gli import) e OWNd **dall'esatto tag pinnato
   nel manifest** (letto dinamicamente, mai hardcoded: non si disallinea quando bumpiamo
   OWNd). Tutti i workflow possono essere rilanciati manualmente dalla pagina Actions.
4. **CI OWNd** (`OWNd/.github/workflows/ci.yml`) — esegue `ruff`, `mypy` e i test della
   libreria con Python 3.14 a ogni push e pull request.

---

## P5 — Estensioni dipendenti dall'hardware

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
- **Programmi di termoregolazione come entità `select`** — esporre i programmi settimanali
  caldo/freddo della centrale di termoregolazione come tendine selezionabili in HA
  (affine a P1a, ma richiede hardware di termoregolazione in impianto).

---

## P6 — Polishing residuo

- `CONF_ENTITY` in `const.py` è definita ma non più utilizzata dopo la migrazione a
  `runtime_data`: rimuovibile.
- Valutare un'opzione di configurazione per **non creare** le entità pulsante Lock/Unlock
  (comando WHO=14) per chi non usa quella funzione, oggi disattivabili solo a mano una per una.
- Valutare la sostituzione dei due pulsanti Lock/Unlock con un'unica entità `lock`
  (semanticamente più corretta), tenendo presente che il protocollo **non** consente di
  interrogare lo stato di blocco: sarebbe uno stato ottimistico, non verificato.
