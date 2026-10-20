# STREAM RADAR — web app installabile per iPhone

## Cosa è pronto
Interfaccia PWA in italiano: giorni, filtri per sette piattaforme, mini-locandine, voto TMDb, trame espandibili, filtro audio italiano. Funziona con `data.json`. Non serve una build.

## Pubblicazione gratuita con GitHub Pages
1. Crea un **repository GitHub pubblico** chiamato `stream-radar`. Carica il contenuto di questa cartella (non la cartella esterna).
2. In **Settings > Pages > Build and deployment**, seleziona **GitHub Actions**.
3. In **Settings > Secrets and variables > Actions**, aggiungi il repository secret `TMDB_READ_ACCESS_TOKEN`, ottenuto gratuitamente da https://www.themoviedb.org/settings/api (richiede account TMDb). NON inserire il token in `app.js`, `data.json` o file pubblici.
4. Apri **Actions > Stream Radar - refresh and publish > Run workflow**. Il sito pubblicato sarà indicativamente `https://TUOUSERNAME.github.io/stream-radar/` e sarà accessibile pubblicamente.
5. Aprilo con **Safari su iPhone**, premi **Condividi > Aggiungi alla schermata Home** e scegli Stream Radar.

## Limiti IMPORTANTI della versione automatica
- Il workflow aggiorna `data.json` con **candidati** per uscite recenti: confronta date di pubblicazione del *titolo* in TMDb e presenza del provider in Italia tramite dati JustWatch. Questo NON dimostra che il film o la stagione sia entrato proprio quel giorno nel catalogo italiano.
- Non ricava in modo attendibile **nuovi episodi** di serie già avviate, né **doppiaggio italiano**, perciò imposta esplicitamente `Audio da verificare`. Non inventa date/voti/audio. Puoi correggerli manualmente in `data.json` solo con fonti verificate.
- TMDb non espone voti IMDb da questa ricerca: viene visualizzato il voto **TMDb** se ha almeno 10 valutazioni.
- Se non configuri il token TMDb l'app resterà vuota, ma è navigabile.
- I trigger programmati di GitHub Actions non garantiscono esecuzione al minuto e possono essere ritardati. Il workflow prevede due trigger UTC e salta quello che non corrisponde alle 20:00 italiane, tenendo conto dell’ora legale. Le esecuzioni possono comunque subire ritardi della piattaforma.
- La programmazione ChatGPT delle 20:00 **non modifica automaticamente** questa web app: sono sistemi indipendenti.
- GitHub Pages pubblica un sito web: non inserire dati privati nei file.
- L'attribuzione delle disponibilità streaming è a JustWatch tramite TMDb; ricordare i loro requisiti di attribuzione quando si amplia il progetto.

## Verifica in locale
Avvia `python3 -m http.server 8000` nella cartella e apri `http://localhost:8000/`.

## Uso con una fonte migliori
Per riportare esattamente date di arrivo, nuovi episodi e doppiaggio stagionale serve un fornitore dati con copertura italiana e licenza adeguata o una revisione editoriale quotidiana. La struttura `data.json` supporta tali campi, perciò si può integrare senza rifare l'interfaccia.
