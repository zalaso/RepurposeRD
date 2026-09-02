# Registro delle modifiche

Il formato segue [Keep a Changelog](https://keepachangelog.com/it/1.1.0/).
Le versioni seguono [SemVer](https://semver.org/lang/it/).

## [0.1.0] — non ancora rilasciata

Prima versione. Genera ipotesi di riposizionamento terapeutico per malattie rare
monogeniche, in locale, da sole fonti aperte.

### Cosa fa

- **Pipeline completa**: dalla stringa in input al report Markdown, passando per
  identificatore Mondo, gene causale curato da Orphanet, pathway Reactome,
  interazioni farmaco-gene DGIdb, coerenza direzionale, letteratura PubMed e
  conferma regolatoria openFDA.
- **Due strategie di ricerca**. Il ramo meccanicistico trova i farmaci che
  agiscono sullo stesso processo alterato. Il **ponte fenotipico** trova quelli
  che agiscono su una conseguenza a valle, passando per malattie clinicamente
  somiglianti — un caso che il primo ramo non puo' vedere per costruzione.
- **Coerenza direzionale** come componente di prima classe: `unknown` non e' un
  esito neutro e abbassa il punteggio, perche' non sapere se un farmaco
  correggerebbe o aggraverebbe il difetto e' un difetto dell'evidenza.
- **Punteggio deterministico** a pesi dichiarati in `config/scoring.yaml`, con
  ogni componente visibile nel report. Nessun modello appreso.
- **Layer linguistico locale** con tre backend (Ollama, server compatibili con
  l'API OpenAI, generatore deterministico) e un validatore anti-allucinazione
  che verifica ogni PMID, gene, farmaco e identificatore contro cio' che al
  modello e' stato effettivamente mostrato.
- **Banco di prova** con 22 coppie malattia-farmaco a esito noto, verificate
  contro i dati prima di essere ammesse. Baseline in `docs/BENCHMARK_BASELINE.md`:
  17/21 trovati, posizione mediana 2, di cui 7/10 riposizionamenti veri.
- **Controllo negativo** che sostituisce entrambi gli ingressi biologici — gene
  causale e profilo fenotipico — con dati casuali.

### Vincoli rispettati

- **Nessuna dipendenza da API cloud a pagamento** per il funzionamento core.
  L'inferenza linguistica e' locale, ed e' opzionale.
- **Nessun dato ridistribuito.** Il repository distribuisce il codice ETL; le
  fonti si scaricano sulla macchina di chi lo usa, con licenza, versione, data
  di accesso e checksum registrati in `data/raw/manifest.json`.
- **Nessuna dipendenza con codice nativo non firmato**, cosi' che Smart App
  Control su Windows non blocchi l'installazione.
- **Nessuna affermazione di efficacia clinica** puo' comparire negli output: e'
  presidiata dal validatore e da test di regressione costruiti su formule
  realmente prodotte dai modelli.

### Fonti integrate

HGNC (CC0), Mondo (CC BY 4.0), Orphanet (CC BY 4.0), Reactome (CC0), DGIdb v5,
HPO (licenza propria, stato dichiarato in `DATA_SOURCES.md`), openFDA (pubblico
dominio), PubMed E-utilities.

Deliberatamente escluse, con motivazione: DisGeNET (CC BY-NC-SA, clausole
incompatibili), KEGG (ridistribuzione ristretta), dati grezzi OMIM.

### Limiti noti al rilascio

Elencati per esteso in `docs/LIMITATIONS.md`. I tre che contano:

1. **La farmacocinetica e' assente.** Un candidato direzionalmente corretto puo'
   essere inutile perche' non raggiunge il tessuto interessato. Non esiste una
   fonte aperta utilizzabile: e' un limite del dominio.
2. **La curazione direzionale copre 2 malattie.** Il banco mostra che
   l'ordinamento regge lo stesso, ma il livello di evidenza resta
   sistematicamente sottostimato dove il meccanismo non e' annotato.
3. **Nessuno all'infuori degli autori ha ancora eseguito lo strumento** su una
   malattia che non abbiano scelto loro. Nessun test colma questa lacuna.

### Cosa questa versione non dichiara

Che lo strumento funzioni. Ventidue casi di banco sono pochi, sono tutti
riposizionamenti gia' noti e quindi gia' studiati, e la componente di
letteratura li favorisce per costruzione: la copertura misurata e' una stima
ottimistica. Il banco serve a confrontare due configurazioni fra loro.
