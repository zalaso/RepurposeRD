# RepurposeRD

*[English](README.en.md) · **Italiano***

[![CI](https://github.com/zalaso/RepurposeRD/actions/workflows/ci.yml/badge.svg)](https://github.com/zalaso/RepurposeRD/actions/workflows/ci.yml)
[![License](https://img.shields.io/badge/license-Apache--2.0-blue.svg)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.11%20%7C%203.12%20%7C%203.13-blue.svg)](pyproject.toml)

Generatore di **ipotesi di riposizionamento terapeutico** (drug repurposing) per malattie rare monogeniche, basato sull'analisi di pathway biologici condivisi fra il gene causale della malattia e i bersagli di farmaci gia' approvati.

**100% locale. Solo dati aperti. Ogni affermazione tracciabile a una fonte reale.**

> [!WARNING]
> **Questo strumento genera ipotesi di ricerca computazionali, non consigli medici.**
> Nessun risultato prodotto da RepurposeRD e' stato validato in vitro, in vivo o clinicamente.
> Non e' un dispositivo medico, non e' uno strumento diagnostico e non e' uno strumento prescrittivo.
> Ogni output e' destinato alla revisione da parte di un ricercatore qualificato.
> Vedi [DISCLAIMER.md](DISCLAIMER.md).

---

## Cosa fa

Data una malattia rara monogenica in input:

1. **Normalizza** la malattia a un identificatore Mondo canonico
2. **Identifica** il gene causale tramite le associazioni curate di Orphanet
3. **Espande** ai pathway Reactome che contengono quel gene, e ai pathway direttamente adiacenti
4. **Cerca** farmaci gia' approvati che agiscono su geni appartenenti a quei pathway (DGIdb)
5. **Valuta la coerenza direzionale**: il farmaco si oppone al difetto, o rischia di aggravarlo?
6. **Ancora** ogni collegamento a letteratura reale su PubMed (solo PMID e metadati)
7. **Verifica** l'approvazione contro le etichette FDA reali (openFDA), rendendo visibile per cosa il farmaco sia realmente autorizzato
8. **Ordina** i candidati con uno score deterministico e scomposto in componenti visibili
9. **Genera** una spiegazione in linguaggio naturale con un modello locale, **validata** contro le evidenze raccolte
10. **Produce** un report Markdown pensato per la revisione umana

## Cosa non fa, per costruzione

- Non addestra modelli di machine learning
- Non esegue e non promette validazione in vitro o clinica
- Non usa mai un lessico che suggerisca efficacia clinica dimostrata: il vocabolario dei livelli di evidenza non contiene nemmeno la parola "forte"
- Non usa contenuti protetti da copyright o dietro paywall
- Non lascia che il modello linguistico recuperi fatti: l'LLM **scrive**, non **cerca**

---

## Architettura in una riga

```
                    ┌─ ramo meccanicistico ────────────────────────────┐
malattia → [Mondo] →│ gene causale → [Orphanet] → pathway → [Reactome] │→ geni
                    └──────────────────────────────────────────────────┘   │
                    ┌─ ponte fenotipico ───────────────────────────────┐   │
                   →│ malattie simili → [HPO] → loro geni causali      │→ geni
                    └──────────────────────────────────────────────────┘   │
                                                                           ▼
  farmaci approvati → [DGIdb] → coerenza direzionale → letteratura → [PubMed]
        → score deterministico → evidence bundle (JSON)
        → LLM locale (solo prosa) → validatore anti-allucinazione → report
```

**Due strategie di ricerca, non una.** Il ramo meccanicistico trova i farmaci
che agiscono sullo *stesso* processo alterato dalla malattia. Il ponte
fenotipico trova quelli che agiscono su una *conseguenza* di quel processo,
passando per malattie clinicamente somiglianti: e' il caso di molti
riposizionamenti reali, ed e' invisibile al primo ramo per costruzione.
I candidati che arrivano dal ponte sono marcati come tali nel report e
penalizzati nel punteggio, perche' la somiglianza clinica non dimostra un
meccanismo condiviso. Disattivabile con `--no-phenotype-bridge`.

Il punto architetturale centrale e' l'**evidence bundle**: un oggetto JSON che contiene tutti e soli i fatti verificati. Il modello linguistico riceve quello e nient'altro, senza accesso a strumenti di ricerca. Dopo la generazione, un validatore estrae ogni PMID, gene, farmaco e identificatore dal testo prodotto e verifica che compaia nel bundle. Una citazione inventata diventa cosi' **un bug rilevabile da un test**, non un rischio da mitigare con il prompting.

---

## Installazione

Serve Python 3.11–3.13.

Il progetto non ha dipendenze con codice nativo non firmato: **Smart App Control**,
attivo per impostazione predefinita su Windows recenti, blocca quel tipo di
libreria, e disattivarlo non e' reversibile senza reinstallare il sistema. Nessuno
deve compiere quella scelta per far girare uno strumento di ricerca.

```bash
git clone https://github.com/zalaso/RepurposeRD.git
cd RepurposeRD
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
```

Con [uv](https://github.com/astral-sh/uv), che e' la via consigliata:

```bash
uv sync --extra dev
```

### Modello locale (opzionale ma consigliato)

RepurposeRD funziona **anche senza alcun LLM**: il backend `template` produce
una spiegazione deterministica costruita dalle stesse evidenze. Non e' una
versione degradata, e' l'unica di cui si possa *dimostrare* che non inventa
nulla, perche' non genera: ricopia campi strutturati.

Per la prosa generata serve un modello locale via [Ollama](https://ollama.com):

```bash
ollama pull qwen2.5:7b-instruct
repurposerd run "tuberous sclerosis" --llm-backend ollama
```

Sono supportati anche i server compatibili con l'API OpenAI (LM Studio,
`llama-server` di llama.cpp) tramite `--llm-backend openai-compatible`.

#### Quale modello, su quale hardware

**Il modello predefinito e' `qwen2.5:7b-instruct`**, ed e' la scelta consigliata
per chi ha hardware adeguato. Non esiste alcun ripiego automatico su un modello
piu' piccolo: il progetto usa quello che gli si indica.

Numeri misurati su un portatile senza GPU utilizzabile (AMD Ryzen 3 2200U, due
core, Vega 3 integrata), che e' il caso peggiore realistico:

| Modello | Tempo per candidato | Esito |
|---|---:|---|
| `qwen2.5:7b-instruct` | ~480 s | prosa piu' scorrevole; 3 su 3 validate |
| `qwen2.5:3b-instruct` | ~190 s | 3 su 3 validate; sovradichiara piu' spesso, in modo piu' evidente |
| `template` (nessun LLM) | immediato | deterministico e verificabile per costruzione |

Il 7B **funziona** anche su questo hardware: e' solo lento. Con una GPU discreta
i tempi scendono di uno o due ordini di grandezza, e su una macchina capace non
c'e' ragione di scendere sotto il 7B. Modelli piu' grandi (14B, 32B) sono
utilizzabili allo stesso modo passando `--model`: il backend non impone alcun
limite di dimensione.

#### Rendere praticabile un modello grande su report lunghi

Il vero ostacolo non e' la dimensione del modello ma la lunghezza del report:
quaranta candidati a 7B su CPU sono circa sei ore e mezza, e nessuno le
aspettera'.

```bash
# I primi 5 candidati narrati dal modello, i restanti 35 dal generatore
# deterministico. Stesso report, da ~6,5 ore a meno di un'ora.
repurposerd run "Niemann-Pick disease type C" --top 40 \
  --llm-backend ollama --model qwen2.5:7b-instruct --narrate-top 5
```

Non si perde nulla di verificabile: il generatore deterministico ricopia gli
stessi campi strutturati, e il report dichiara candidato per candidato da dove
viene la prosa. Un revisore legge per esteso i primi, e i restanti li scorre.

#### Un modello piu' grande non e' un modello piu' sicuro

Entrambi i modelli provati hanno tentato di sovradichiarare, e il validatore li
ha intercettati entrambi. Ma **lo hanno fatto in modo diverso, e il modo del 7B
e' il piu' insidioso**:

| Modello | Cosa ha scritto | Perche' e' un problema |
|---|---|---|
| `qwen2.5:3b` | «i dati **confermano che** l'ipotesi e' coerente e affidabile» | afferma; stona, un lettore se ne accorge |
| `qwen2.5:7b` | «il meccanismo ipotizzato per **l'efficacia** del sirolimus» | **presuppone**; suona come una frase di un articolo |

La seconda formula non afferma l'efficacia: la da' per esistente e ne discute il
meccanismo. E' esattamente cio' che il [disclaimer](DISCLAIMER.md) dichiara non
debba mai comparire, ed e' passata inosservata al primo elenco di espressioni
vietate proprio perche' grammaticalmente innocua.

**La qualita' linguistica e l'affidabilita' epistemica non crescono insieme.**

Entrambe le formule sono oggi test di regressione. Ma la correzione che ha
funzionato non e' stata vietare di piu': vietata la radice `efficac` senza
toccare il resto, il 7B ha smesso di superare la validazione **in ogni singolo
caso**, perche' il divieto non era nelle istruzioni che riceveva. E anche dopo
averlo aggiunto al prompt, continuava a scrivere «la coerenza e' confermata».

Ha funzionato **riformulare il fatto che gli si mostra**: il bundle passava
`esito: "coerente"`, che invitava quella frase, e ora passa `valutazione
euristica: compatibile, mai verificata sperimentalmente`. L'etichetta porta con
se' la propria riserva, e il modello non ha piu' ragione di aggiungere altro.
Da 0 su 3 a 3 su 3. Il dettaglio in [docs/PILOT_RESULTS.md](docs/PILOT_RESULTS.md).

L'elenco delle espressioni vietate resta comunque incompleto per costruzione:
ogni modello nuovo puo' trovare una formula non prevista. Per questo il
generatore deterministico non e' un ripiego degradato, ed e' sempre disponibile
con `--llm-backend template`.

Il timeout predefinito e' di dieci minuti per candidato; si regola con
`--llm-timeout`.


---

## Uso

```bash
# 0. Verifica che l'ambiente sia a posto (dice cosa manca e come rimediare)
repurposerd doctor

# 1. Scarica le fonti aperte in locale (~180 MB, una volta sola)
repurposerd fetch

# 2. Costruisci lo store DuckDB
repurposerd build

# 3. Genera le ipotesi
repurposerd run "Tuberous sclerosis complex" --out out/tsc.md
```

Altri comandi utili:

```bash
repurposerd doctor                          # verifica i prerequisiti e dice cosa manca
repurposerd sources                         # fonti, licenze e stato di download
repurposerd info                            # stato dello store e impronta di configurazione
repurposerd resolve "Niemann-Pick type C"   # solo risoluzione malattia -> gene

repurposerd run MONDO:0001734 --llm-backend template    # senza alcun LLM
repurposerd run MONDO:0001734 --no-literature           # senza interrogare PubMed
repurposerd run MONDO:0001734 --no-regulatory           # senza conferma FDA
repurposerd run MONDO:0001734 --no-phenotype-bridge     # solo ramo meccanicistico
repurposerd run MONDO:0001734 --max-bridges 50          # rete fenotipica piu' ampia
repurposerd run MONDO:0001734 --shuffle-control         # controllo negativo
repurposerd run MONDO:0001734 --narrate-top 5           # modello solo sui primi 5
repurposerd run MONDO:0001734 --llm-timeout 900         # CPU lente
repurposerd run MONDO:0001734 --bundle-out out/b.json   # salva l'evidence bundle
```

> [!NOTE]
> La prima esecuzione su una malattia interroga PubMed per alcune centinaia di
> candidati e puo' richiedere una decina di minuti: il rate limit di NCBI e'
> rispettato, non aggirato. Le risposte finiscono in cache, quindi le esecuzioni
> successive sulla stessa malattia sono rapide.

---

## Lingua

La documentazione e' disponibile in italiano e in inglese. **I report generati
sono per ora solo in italiano**, come i prompt che ne producono la prosa.

Rendere selezionabile la lingua del report non e' un lavoro di traduzione di
stringhe: il validatore anti-allucinazione riconosce radici vietate (`efficac`, e
altre) che sono specifiche di una lingua, e un report inglese ha bisogno del
proprio elenco verificato prima di poter essere considerato affidabile. **Un
report tradotto con un validatore non tradotto sarebbe meno sicuro che nessun
report inglese**, ed e' la ragione per cui non e' stato fatto in fretta.

---

## Il banco di prova

Con due soli casi pilota non si poteva dire se una modifica ai pesi migliorasse
o peggiorasse qualcosa. `config/benchmark.yaml` contiene 22 coppie
malattia-farmaco con esito noto, e il comando le esegue tutte:

```bash
repurposerd benchmark --out out/benchmark.md          # completo, ore alla prima esecuzione
repurposerd benchmark --quick --out out/quick.md      # senza PubMed, ~8 minuti
```

Nessuna voce e' stata scritta a memoria: ogni coppia e' stata verificata contro
Mondo, Orphanet, DGIdb e PubMed prima di essere ammessa, e porta i PMID
realmente restituiti dall'interrogazione. Le coppie scartate durante la verifica
sono elencate nel file con il motivo, perche' a chi vorra' ampliarlo servono
tanto quanto quelle incluse.

**Il banco contiene anche casi che devono fallire.** La trientina nella malattia
di Wilson e' un chelante senza bersaglio proteico: nessun metodo basato su
pathway condivisi puo' trovarla. Un banco in cui tutto e' trovabile premierebbe
la promiscuita', e alzare la copertura rendendo lo strumento indiscriminato
sarebbe un peggioramento travestito da miglioramento.

### Risultato della prima esecuzione

| Metrica | Valore |
|---|---|
| Trovati entro la posizione 40 | **17/21** |
| di cui **riposizionamenti veri** | 7/10 |
| di cui farmaci in indicazione | 10/11 |
| Posizione mediana | **2** |
| Fallimenti attesi, correttamente non trovati | 1/1 |

Un dato che vale la pena isolare: **19 casi su 22 girano senza alcun meccanismo
curato** in `config/mechanism.yaml`, quindi con la direzione dell'effetto sempre
ignota. L'ordinamento regge lo stesso. Cio' che la curazione direzionale migliora
non e' il recupero ma la **calibrazione della fiducia**: senza, il livello di
evidenza resta bloccato a `limitata` anche per candidati corretti e ben
posizionati.

**Cosa misura e cosa no.** Misura la copertura, non la precisione: un candidato
non atteso non e' un falso positivo, potrebbe essere un'ipotesi legittima che
nessuno ha ancora studiato. E i 22 casi sono tutti riposizionamenti gia' noti,
quindi gia' studiati, con letteratura abbondante: la componente di letteratura
li favorisce, e la copertura misurata e' percio' una **stima ottimistica**.

## Il controllo negativo

`--shuffle-control` riesegue la pipeline sostituendo **entrambi** gli ingressi
biologici con dati falsi: il gene causale con un gene casuale, e il profilo
fenotipico con quello di una malattia casuale. Tutto il resto resta identico.

Sostituire solo il gene sarebbe stato un controllo a meta': il ponte fenotipico
non parte dal gene ma dal quadro clinico, e avrebbe continuato a lavorare su
vicini di casa autentici mentre si pretendeva di misurare cosa succede con dati
falsi.

Se il ranking prodotto su ingressi falsi e' indistinguibile da quello reale, lo
score non sta misurando nulla. E' il modo piu' economico per accorgersi di aver
costruito un generatore di plausibilita' invece di uno strumento, e va eseguito
come parte della valutazione, non come curiosita'.

---

## Caso pilota: sclerosi tuberosa

Il caso di validazione primario e' la **sclerosi tuberosa (TSC2, MONDO:0001734)**,
scelto perche' ha una risposta nota in anticipo: sirolimus ed everolimus
inibiscono MTOR e sono realmente approvati per manifestazioni della TSC, dove
sono arrivati proprio per riposizionamento. TSC2 e' un regolatore negativo di
mTORC1, quindi la sua perdita di funzione produce iperattivazione: un inibitore
di MTOR e' direzionalmente coerente.

Se la pipeline non recupera sirolimus fra i primi candidati, la pipeline e' rotta.
Sapere in anticipo qual e' la risposta giusta e' cio' che rende utile un pilota.

**Risultato: riuscito.** Sirolimus, everolimus e temsirolimus occupano i primi
tre posti, con direzione coerente e provenienza completa.

Il secondo caso, la **malattia di Niemann-Pick tipo C (NPC1, `MONDO:0018982`)**,
**fallisce**, e il fallimento e' documentato perche' e' istruttivo: miglustat non
viene recuperato, e non per una soglia mal tarata, ma perche' NPC1 e UGCG non
condividono alcun pathway Reactome a nessuna dimensione. Il collegamento reale
passa per la fisiopatologia a valle, che un metodo basato sulla co-appartenenza
a pathway non puo' vedere per costruzione.

Entrambi i casi, con la diagnosi completa del secondo, sono in
[docs/PILOT_RESULTS.md](docs/PILOT_RESULTS.md).

---

## Fonti dati

Il repository **non ridistribuisce dati**. Distribuisce il codice ETL che li
scarica sulla macchina di chi lo usa, registrando per ciascuno licenza, versione,
data di accesso e checksum in `data/raw/manifest.json`.

| Fonte | Ruolo | Licenza |
|---|---|---|
| [HGNC](https://www.genenames.org/) | nomenclatura genica, mapping symbol → Entrez | CC0 1.0 |
| [Mondo](https://mondo.monarchinitiative.org/) | identificatore canonico di malattia | CC BY 4.0 |
| [Orphanet](https://www.orphadata.com/) | gene causale curato per malattia rara | CC BY 4.0 |
| [Reactome](https://reactome.org/) | pathway e loro gerarchia | CC0 1.0 |
| [DGIdb v5](https://dgidb.org/) | interazioni farmaco-gene, stato di approvazione | vedi nota |
| [HPO](https://hpo.jax.org/) | similarita' fenotipica fra malattie rare | licenza propria, vedi nota |
| [openFDA](https://open.fda.gov/) | conferma indipendente dell'approvazione | pubblico dominio |
| [PubMed](https://pubmed.ncbi.nlm.nih.gov/) | grounding su letteratura reale | vedi nota |

Dettagli, motivazioni e **fonti deliberatamente escluse** (DisGeNET, KEGG, OMIM grezzo) in [DATA_SOURCES.md](DATA_SOURCES.md).

---

## Limiti noti

Elencati per esteso in [docs/LIMITATIONS.md](docs/LIMITATIONS.md). I tre che contano di piu':

1. **Il metodo non vede la fisiopatologia a valle.** Cattura i casi in cui il farmaco agisce sullo *stesso* processo alterato, non quelli in cui agisce su una *conseguenza* di quel processo. Il caso pilota Niemann-Pick lo dimostra, e nessuna taratura lo risolve.
2. **La direzione dell'effetto e' nota solo in parte.** Il meccanismo della malattia (perdita o guadagno di funzione) viene derivato da Orphanet, che lo dichiara per 1.025 malattie. Ma il *segno* della relazione fra gene causale e bersaglio del farmaco resta curato a mano e copre tre archi: senza quello, un candidato a distanza uno o due resta `unknown` anche quando il meccanismo e' noto, e `unknown` abbassa il punteggio.
3. **La co-appartenenza a un pathway non e' un meccanismo.** E' un indizio di prossimita' funzionale. Il filtro sulla dimensione del pathway e la penalita' direzionale servono a limitare il danno, non a eliminarlo.
4. **Il conteggio di letteratura misura attenzione, non efficacia.** Un accostamento molto studiato puo' esserlo perche' e' stato ripetutamente smentito.

---

## Contribuire

Vedi [CONTRIBUTING.md](CONTRIBUTING.md). In sintesi: `ruff check`, `pytest`, e ogni
nuova fonte dati deve arrivare con la sua licenza dichiarata in `config/sources.yaml`
e la sua provenienza propagata fino al report.

## Licenza

Codice: [Apache-2.0](LICENSE). La concessione brevettuale esplicita di Apache-2.0
riduce l'attrito per chi contribuisce da un'azienda o da un ufficio di
trasferimento tecnologico, il che in ambito biomedico non e' un dettaglio.

I **dati** restano soggetti alle licenze delle rispettive fonti, che non sono
tutte permissive. Vedi [DATA_SOURCES.md](DATA_SOURCES.md).
