# Contribuire a RepurposeRD


*[English](CONTRIBUTING.en.md) · **Italiano***

## Prima di tutto: il principio che tiene in piedi il progetto

**Ogni affermazione deve poter essere ricondotta a una fonte reale, e ogni output deve essere onesto sul proprio grado di incertezza.**

Un contributo che migliora i risultati indebolendo la tracciabilita' o l'onesta' degli output non e' un miglioramento. Se una modifica rende il tool piu' utile ma meno verificabile, va discussa in una issue prima di essere scritta.

## Setup

```bash
git clone https://github.com/zalaso/RepurposeRD.git
cd RepurposeRD
uv sync --frozen --extra dev # oppure: python -m venv .venv && pip install -e ".[dev]"
repurposerd fetch            # ~180 MB di fonti aperte, una volta sola
repurposerd build            # ETL, circa 10 secondi
pytest
```

Python 3.11–3.13. Su 3.14 alcune dipendenze non hanno ancora wheel precompilate.

## Prima di aprire una pull request

```bash
ruff check src tests
ruff format --check src tests
pytest
```

Sono le stesse tre verifiche che esegue la CI, piu' una fase dedicata alle
regole non negoziabili elencate sotto: un fallimento li' non e' un test rotto,
e' una promessa infranta.

I test **non richiedono i dati scaricati**: ognuno costruisce il proprio store
sintetico o usa campioni minimi. Una suite che dipendesse dai 180 MB di fonti
reali sarebbe lenta e fallirebbe a ogni loro aggiornamento per ragioni che non
sono difetti del codice.

## Regole non negoziabili

Queste hanno test che le presidiano. Se li fai fallire, la risposta non e' aggiornare il test.

### 1. Nessun fatto senza provenienza

Ogni dato biomedico che entra nell'evidence bundle porta una `Provenance` con fonte, licenza e data di accesso. Se aggiungi un campo che asserisce qualcosa sul mondo, deve sapere da dove viene.

### 2. Il modello linguistico scrive, non cerca

L'LLM riceve l'evidence bundle e nient'altro. Non ha strumenti di ricerca, non ha accesso alla rete, non ha accesso al database. Aggiungergli capacita' di recupero significherebbe rinunciare al fatto che il validatore possa verificarne l'output, che e' la proprieta' su cui si regge la credibilita' dello strumento.

### 3. Il validatore non si indebolisce

`tests/test_validator.py` descrive la proprieta' centrale: una citazione inventata deve essere una condizione **rilevabile**. Se una modifica fa passare un PMID inesistente, e' un bug con la priorita' di un bug di sicurezza.

### 4. Il lessico dell'efficacia resta vietato, e l'elenco non e' mai finito

Nessun output puo' affermare o suggerire efficacia clinica, ne' fornire indicazioni posologiche. Non esiste un livello di evidenza chiamato "forte", e non va aggiunto: il vocabolario del report non deve offrire una parola che un lettore frettoloso possa leggere come efficacia.

**L'elenco in `validator.py` e' incompleto per costruzione.** E' stato ampliato due volte, entrambe dopo aver visto un modello reale aggirarlo:

| Modello | Formula sfuggita | Cosa mancava |
|---|---|---|
| `qwen2.5:3b` | «i dati **confermano che** l'ipotesi e' coerente e affidabile» | l'elenco aveva `conferma che`, non reggeva le flessioni |
| `qwen2.5:7b` | «il meccanismo ipotizzato per **l'efficacia** del sirolimus» | copriva l'uso predicativo, non quello nominale |

Se trovi una formula nuova:

1. **aggiungi il testo reale come test di regressione**, non una parafrasi. La formula esatta che un modello ha davvero prodotto vale piu' di dieci varianti immaginate;
2. preferisci una radice con espressione regolare a una corrispondenza letterale;
3. verifica che il generatore deterministico continui a superare la validazione — se violasse i pattern nuovi, un respingimento non avrebbe piu' dove ripiegare. C'e' un test che lo presidia.

**Non assumere che un modello piu' grande sia piu' sicuro.** Il 7B sovradichiara meno spesso del 3B, ma quando lo fa produce prosa scorrevole e plausibile, che un lettore assorbe senza attrito. La qualita' linguistica e l'affidabilita' epistemica non crescono insieme.

### 5. Un pre-filtro non puo' ignorare una componente del punteggio

La selezione dei candidati da interrogare su PubMed usa un punteggio che non
contiene ancora la componente di letteratura. Il criterio in
`bundle._literature_shortlist` include percio' tutti i candidati entro il peso
massimo di quella componente dalla soglia.

Non e' pedanteria: prima di questo criterio, miglustat — riposizionamento reale
e documentato su Niemann-Pick — veniva escluso al 253esimo posto preliminare
prima di poter mostrare l'unica evidenza che lo distingueva. Chi aggiunge una
componente di punteggio calcolata **dopo** la preselezione deve aggiornare quel
margine, altrimenti reintroduce lo stesso difetto.

### 6. `unknown` non e' neutro

Quando la direzione dell'effetto non e' determinabile, il punteggio scende. Non sapere e' un difetto dell'evidenza, non un'assenza di problema. Chi propone di trattare `unknown` come neutro deve spiegare perche' un lettore dovrebbe fidarsi allo stesso modo di un candidato verificato e di uno non verificabile.

## Aggiungere una fonte dati

1. Voce in `config/sources.yaml` con **licenza e URL della licenza**, non solo l'URL di download
2. Parser in `src/repurposerd/sources/parsers.py`
3. Test in `tests/test_parsers.py` con un campione minimo che riproduca la struttura reale del file
4. Loader in `src/repurposerd/sources/build.py` — per i file tabellari usa il lettore CSV nativo di DuckDB, non `executemany` (vedi la nota in `store.bulk_insert`)
5. Propagazione della `Provenance` fino al report

Se la licenza ha clausole NonCommercial o ShareAlike, dichiara nella PR cosa comporta per i derivati. Una fonte utile ma con licenza incompatibile va nella sezione `excluded` di `sources.yaml`, con la motivazione: il progetto preferisce essere meno completo che meno chiaro.

## Aggiungere annotazioni meccanicistiche

`config/mechanism.yaml` e' il layer di conoscenza curata a mano. Ogni voce richiede:

- `rationale`: perche' l'affermazione e' vera, in una forma leggibile da un revisore
- `sources`: almeno un PMID o un identificatore di fonte. **Un'asserzione curata senza fonte non vale piu' di un'opinione**, e il progetto non la accetta.
- `curated_by`: chi la sostiene

Il meccanismo di malattia (perdita o guadagno di funzione) viene ora derivato automaticamente da Orphanet per oltre mille malattie. Una voce `disease_mechanism` scritta a mano serve solo dove Orphanet non lo dichiara **e** si dispone di una fonte solida: aggiungere a mano cio' che Orphanet gia' dice crea soltanto due verita' che possono divergere.

Questo file ha un peso sproporzionato sui risultati (vedi `docs/LIMITATIONS.md`, punto 2). Le PR che lo toccano ricevono una revisione piu' attenta di quelle che toccano il codice.

## Le due strategie di ricerca

Il progetto ha due percorsi che portano allo stesso stadio di scoring:

- **Ramo meccanicistico** (`pipeline/pathways.py`): dal gene causale della malattia ai geni che ne condividono un pathway Reactome.
- **Ponte fenotipico** (`pipeline/phenotype.py`): dalle malattie clinicamente somiglianti ai loro geni causali, come punto di ingresso aggiuntivo.

Il secondo esiste perche' il primo ha un punto cieco dimostrato: se il farmaco agisce su una conseguenza a valle del difetto e non sullo stesso processo, i due geni non condividono alcun pathway e nessuna soglia li avvicina.

**Ogni candidato che arriva dal ponte deve restare riconoscibile come tale** — nel modello (`PathwayLink.bridge`), nel punteggio (`route_directness`), nel prompt e nel report. Una modifica che rendesse indistinguibile un'ipotesi indiretta da una diretta e' una regressione, per quanto migliori il ranking.

## Contributi particolarmente utili

In ordine di impatto:

1. **Relazioni con segno derivate da Reactome a livello di reazione.** Sostituirebbe le annotazioni a mano con dati, ed e' il miglioramento singolo piu' importante ancora possibile.
2. **Ampliare il banco di prova** (`config/benchmark.yaml`). Ventidue casi sono pochi, ed e' il contributo che vale piu' di qualunque raffinamento dell'algoritmo: senza un banco piu' ampio non si puo' dimostrare che una modifica migliori qualcosa.

   Ogni voce nuova deve superare la stessa verifica delle esistenti, **prima** di essere scritta:
   - la malattia risolve in Mondo con la stringa indicata (`repurposerd resolve "..."`)
   - Orphanet le attribuisce geni causali
   - il farmaco esiste in DGIdb (attenzione alle forme saline: `LOSARTAN POTASSIUM`)
   - PubMed ha letteratura sulla coppia, e i PMID nel file sono quelli **realmente restituiti**, non ricordati

   Sono benvenuti anche nuovi `structural_miss`: i casi che il metodo non puo' trovare valgono quanto quelli che deve trovare.
3. **Una metrica di somiglianza fenotipica migliore.** L'attuale e' un Jaccard pesato per contenuto informativo; il best-match average di Resnik sarebbe piu' robusto alle differenze di numerosita' delle annotazioni, ma richiede il calcolo dell'antenato comune piu' informativo per coppia di termini. Chi lo affronta deve valutarlo su **piu** casi, non solo su quelli gia' noti: tarare la metrica sul caso che si vuole far funzionare e' il modo piu' rapido per costruire uno strumento che sembra funzionare.
4. **Un controllo negativo piu' severo** di quello attuale (vedi `docs/LIMITATIONS.md`, punto 3).
5. **Modellazione della farmacocinetica**, oggi completamente assente: un candidato direzionalmente perfetto puo' essere inutile perche' non raggiunge il tessuto interessato.
6. **Selezione della lingua del report.** Oggi i report sono solo in italiano. Non e' un lavoro di traduzione di stringhe: il validatore anti-allucinazione riconosce radici vietate specifiche di una lingua, e un report inglese ha bisogno del proprio elenco verificato prima di poter essere considerato affidabile. Un report tradotto con un validatore non tradotto sarebbe meno sicuro che nessun report inglese.

## Stile

- Commenti che spiegano **perche'**, non **cosa**. Il codice dice gia' cosa fa.
- I nomi delle funzioni descrivono l'effetto, non l'implementazione.
- Messaggi di errore che dicono all'utente cosa fare dopo.
- I test descrivono proprieta', non implementazioni: devono sopravvivere a un refactoring.

## Licenza dei contributi

Contribuendo, accetti che il tuo contributo sia distribuito sotto Apache-2.0, come il resto del progetto.
