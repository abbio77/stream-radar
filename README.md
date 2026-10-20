# Stream Radar 2.0

PWA italiana pubblicata su https://abbio77.github.io/stream-radar/.
La grafica originale è conservata: sette piattaforme, filtri per data/tipo/audio,
locandine, voti e schede espandibili. Non serve una build.

## Ricerca quotidiana

`scripts/update.py` usa il secret GitHub `TMDB_READ_ACCESS_TOKEN` esclusivamente
sul runner; nessuna chiave viene inviata al browser.

- Finestra mobile di 7 giorni (oggi compreso, fuso Europe/Rome), senza archivio precedente, paginazione completa
  fino a 20 pagine per tipo. Il limite raggiunto fa fallire il controllo invece
  di pubblicare una scansione troncata come completa.
- Film: date digitali **IT** di TMDb (`release_dates`, tipo 4). Queste date non
  certificano l'arrivo su Netflix o su un altro singolo catalogo.
- Serie: ricerca `air_date` e dettagli delle stagioni correnti/recenti per includere
  serie già avviate, con stagione/episodio e data originale chiaramente indicati.
  La presenza della serie non dimostra la disponibilità di ogni nuovo episodio in Italia.
- Solo offerte `flatrate` in Italia; esclusi noleggio e acquisto. Ogni aggiornamento
  ricontrolla anche la disponibilità dei titoli in archivio.
- Metadati aggiornati dalle schede complete. Voto del titolo TMDb con almeno 10
  valutazioni e numero dei votanti. Non è un voto IMDb né un voto del singolo episodio.
- Locandine italiane preferite; ripiego su immagini senza testo, inglesi e originali.
  Se un'immagine non si carica, l'interfaccia usa l'icona locale.
- Timeout, retry con backoff e gestione 429. Se una richiesta necessaria fallisce,
  l'aggiornamento fallisce e il precedente `data.json` rimane intatto. Scrittura atomica.
- I vecchi dati senza provenienza della data restano esplicitamente etichettati
  come date del titolo, senza trasformarli in uscite italiane confermate.

L'aggiornamento parte da Actions manualmente, quando cambia il codice e ogni sera.
I due trigger UTC coprono ora legale/solare; il controllo su ora italiana e data
salta il trigger anticipato e impedisce duplicati dopo una raccolta serale riuscita.
Un aggiornamento manuale al mattino non annulla quello serale. GitHub può
ritardare le esecuzioni. Il pulsante **Aggiorna** ricarica il catalogo pubblicato;
non esegue la ricerca sul server.

## Audio italiano: controllo ufficiale e verifiche editoriali

TMDb/JustWatch documentano la disponibilità del titolo, non tutte le tracce audio.
Non si deduce il doppiaggio da `spoken_languages`, lingua originale, trama italiana,
sottotitoli o presenza del provider in Italia.

Per le schede Apple TV associate in `audio-evidence.json`, il collector rilegge
ogni giorno la pagina ufficiale italiana e separa l'elenco **Audio** da quello
**Sottotitoli**. Controlla titolo e, per le serie, stagione/episodio. Un trailer
italiano o la sola presenza dei sottotitoli non confermano il doppiaggio. Un errore,
un cambio di pagina o un elenco assente riportano lo stato a `unknown`.
Le associazioni iniziali comprendono Tenzing, Matchbox: Il film e Dark Matter S2 E7/E8.
Le associazioni titolo/fonte sono curate; la rilettura delle lingue è automatica.

Esempio di associazione automatica:

```json
{
  "Apple TV+-movie-1288069": {
    "mode": "apple_tv",
    "platform": "Apple TV+",
    "region": "IT",
    "expected_title": "Tenzing",
    "source_url": "https://tv.apple.com/it/movie/tenzing/umc.cmc.6lic0hhuxkrbem0n29vzjopii"
  }
}
```

Per le altre fonti, `audio-evidence.json` accetta verifiche editoriali riferite al preciso ID della
scheda, con fonte HTTPS, piattaforma, regione IT, data di verifica, scadenza e nota.
Le verifiche scadono entro 30 giorni dalla revisione anche se la scadenza dichiarata
è più lunga. Per una serie sono obbligatori stagione ed episodio esatti.
La scheda mostra il link alla fonte, la data e l'ambito della verifica.

Esempio di struttura (i dati seguenti sono illustrativi, non prove reali):

```json
{
  "Netflix-tv-123-s2e3": {
    "platform": "Netflix",
    "region": "IT",
    "season": 2,
    "episode": 3,
    "status": "yes",
    "checked_at": "2026-10-20",
    "expires_at": "2026-10-27",
    "source_url": "https://www.netflix.com/it/title/ID_REALE",
    "scope": "Stagione 2, episodio 3, catalogo Italia",
    "note": "Traccia audio italiana controllata nella scheda dell'episodio."
  }
}
```

`yes` significa audio italiano verificato (originale o doppiato); `sub` richiede
una verifica esplicita che siano disponibili solo sottotitoli ITA, non la mera
presenza dei sottotitoli. In ogni altro caso lo stato è `unknown` e il titolo è
escluso dal filtro audio verificato. Per estendere il controllo automatico a tutte le piattaforme serve una fonte
accessibile con copertura per territorio, stagione ed episodio; non è inclusa
nell'API TMDb. Non si trasferisce una verifica Apple TV su un'altra piattaforma.

## App installata e pubblicazione

Il service worker usa rete prima e cache come ripiego. Conserva l'ultimo catalogo
per l'uso offline anche quando la richiesta aggiunge un cache-buster. Gli errori
di aggiornamento non cancellano il catalogo già caricato; dati più vecchi di 36 ore
sono segnalati. Giorni con mese, ricerca senza accenti e filtri accessibili. Gli episodi sono
raggruppati in una sola scheda per titolo/piattaforma e raccolti in un elenco
chiuso, espandibile nella scheda. I giorni scaduti scompaiono anche dal browser
all’apertura, al cambio di data o al ritorno alla scheda; il contatore principale conta i titoli distinti.

Il sito usa GitHub Pages. I file pubblici non devono contenere dati privati.
La raccolta è serializzata con `concurrency` e testata prima della ricerca.
Un errore della raccolta è visibile in Actions e non modifica il catalogo.

## Verifica locale

```sh
python -m unittest discover -s tests -v
node --test tests/test_app.cjs
node --check app.js
node --check sw.js
python -m http.server 8000
```

Test con risposte API simulate: date digitali italiane, nuovi episodi, paginazione,
ritiro provider, noleggio escluso, outage, conservazione dati, deduplicazione,
voti, locandine, ambito/scadenza della verifica audio, filtri, sicurezza dei link,
schede espandibili e aggiornamento fallito. La raccolta effettiva richiede il secret.

Metadati: [TMDb](https://www.themoviedb.org/).
Disponibilità: [JustWatch](https://www.justwatch.com/it) tramite TMDb.
Questo prodotto utilizza l'API TMDb ma non è approvato o certificato da TMDb.
