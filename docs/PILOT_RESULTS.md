# Risultati dei casi pilota

Eseguito il 2026-09-01. Due fasi con impronte di configurazione diverse: `e4328d594a5d` (fase 1, solo ramo meccanicistico) e `6d3285ca3c6f` (fase 2, con ponte fenotipico, pesi ribilanciati e tetto al livello senza direzione). **Report con impronte diverse non sono confrontabili**: i punteggi assoluti cambiano fra le due fasi, gli ordinamenti restano leggibili.
Riproducibile con i comandi indicati sotto.

Il punto di questi due casi e' che la risposta giusta era **nota in anticipo**. Un pilota in cui non si sa cosa aspettarsi non valida nulla: conferma solo che il codice non va in errore.

---

## Caso 1 — Sclerosi tuberosa (`MONDO:0001734`, TSC1/TSC2)

```bash
repurposerd run "tuberous sclerosis" --top 10 --llm-backend template
```

**Atteso**: sirolimus ed everolimus fra i primi candidati, con direzione coerente. Sono inibitori di MTOR, realmente approvati per manifestazioni della TSC, e ci sono arrivati proprio per riposizionamento.

**Ottenuto**:

| # | Farmaco | Bersaglio | Hop | Direzione | Punteggio | Evidenza |
|---:|---|---|---:|---|---:|---|
| 1 | SIROLIMUS | MTOR | 1 | coerente | 0.758 | moderata |
| 2 | EVEROLIMUS | MTOR | 1 | coerente | 0.758 | moderata |
| 3 | TEMSIROLIMUS | MTOR | 1 | coerente | 0.758 | moderata |
| 4 | SAPANISERTIB | MTOR | 1 | coerente | 0.674 | moderata |
| 5 | METFORMIN | MTOR | 1 | coerente | 0.646 | limitata |
| 6 | ASPIRIN | TSC1 | 0 | non determinabile | 0.627 | limitata |
| 7 | ALPELISIB | MTOR | 1 | coerente | 0.592 | limitata |
| 8 | CAPIVASERTIB | AKT1 | 1 | non determinabile | 0.580 | limitata |
| 9 | INFIGRATINIB | MTOR | 1 | coerente | 0.546 | limitata |
| 10 | PERHEXILINE MALEATE | MTOR | 1 | coerente | 0.546 | limitata |

**Esito: riuscito.** I tre controlli positivi occupano i primi tre posti, con direzione coerente e provenienza completa.

### Osservazioni che contano piu' del risultato

- **`ASPIRIN → TSC1` al sesto posto e' rumore**, quasi certamente un artefatto di aggregazione di DGIdb e non una relazione farmacologica reale. Lo strumento non lo esclude, ma lo marca `direzione non determinabile` e, per effetto del tetto sul livello di evidenza, non gli consente di superare `limitata` nonostante un punteggio di 0.68. Un revisore lo scarterebbe comunque in pochi secondi; il tetto serve a chi non lo farebbe.
- Il filtro causale di Orphanet ha **correttamente escluso IFNG**, che Orphanet annota come modificatore e non come causa della TSC. Senza quel filtro, IFNG avrebbe portato con se' un intero ramo immunologico di candidati.
- Il pathway usato per il punteggio di sirolimus e' «Constitutive Signaling by AKT1 E17K in Cancer» (25 geni), scelto perche' e' il piu' piccolo. Biologicamente «MTOR signalling» sarebbe piu' pertinente, e infatti compare nell'elenco dei pathway condivisi. La preferenza per il pathway piu' piccolo massimizza la specificita' statistica ma non sempre la leggibilita': per questo il report mostra anche gli altri.

---

## Caso 2 — Niemann-Pick tipo C (`MONDO:0018982`), fase 1

```bash
repurposerd run "Niemann-Pick disease type C" --top 10 --llm-backend template
```

**Atteso**: miglustat fra i candidati. E' approvato per la malattia di Gaucher tipo 1 e riposizionato su NPC (approvazione EMA), e inibisce UGCG riducendo la sintesi dei glucosilceramidi.

**Ottenuto**: dieci candidati che agiscono tutti direttamente su NPC1 (hop 0), tutti con direzione non determinabile e punteggi fra 0.50 e 0.54. **Miglustat non compare.**

### Esito: fallito, e la diagnosi e' piu' istruttiva del fallimento

Verificando i singoli passaggi:

1. **Miglustat e' presente in DGIdb**, come `inhibitor` di **UGCG**, con `approved = TRUE`, riportato da cinque fonti a monte. ✓
2. **UGCG e' annotato in Reactome**, in «Glycosphingolipid biosynthesis» (19 geni), «Glycosphingolipid metabolism» (58) e «Sphingolipid metabolism» (107). ✓
3. **NPC1 e' annotato in Reactome**, in «LDL clearance» (19 geni), «Plasma lipoprotein clearance» (37) e «Plasma lipoprotein assembly, remodeling, and clearance» (75). ✓
4. **NPC1 e UGCG non condividono alcun pathway Reactome. A nessuna dimensione. Zero.**

Il punto 4 e' il risultato importante, e non e' una questione di taratura. Alzare `max_pathway_size` non recupererebbe miglustat, perche' non esiste **nessun** pathway, per quanto grande, che contenga entrambi i geni. In Reactome NPC1 sta nel ramo del trasporto delle lipoproteine e UGCG nel ramo del metabolismo sfingolipidico, e i due rami non si incontrano mai in un'unita' annotata.

### Cosa significa

Il collegamento reale fra NPC1 e miglustat non e' una co-appartenenza a un pathway: e' **fisiopatologia a valle**. Il difetto di trasporto del colesterolo lisosomiale causa un accumulo *secondario* di sfingolipidi, e miglustat agisce su quell'accumulo secondario. E' una catena causale che passa per lo stato patologico della cellula, non per un processo biologico co-annotato.

**Questo e' un limite strutturale del metodo, non un difetto di implementazione.** Un metodo basato sulla co-appartenenza a pathway non puo' vedere questo tipo di collegamento, per costruzione. Nessuna taratura dei parametri lo cambia.

### Conseguenza per la fase 2

Il fallimento indica con precisione cosa serve, ed e' diverso da cio' che avevo previsto prima di eseguire il pilota:

1. **Similarita' fenotipica (HPO)** — NPC e Gaucher condividono fenotipi (epatosplenomegalia, coinvolgimento neurologico). Una seconda strategia di ricerca basata sul fenotipo, indipendente dal pathway, avrebbe potuto accostare le due malattie e quindi i loro farmaci. Sale al primo posto delle priorita', insieme alle relazioni con segno.
2. **Monarch KG** — contiene relazioni fra malattie e fra malattia e fenotipo che Reactome non ha, e collegamenti da modelli animali.
3. **Il ramo pathway resta valido**, ma va dichiarato per quello che e': cattura i casi in cui il farmaco agisce **sullo stesso processo** alterato, non quelli in cui agisce su una **conseguenza a valle**. La sclerosi tuberosa e' del primo tipo, Niemann-Pick C del secondo.


---

## Caso 2 — Niemann-Pick tipo C, ripetuto dopo HPO (fase 2)

```bash
repurposerd run "Niemann-Pick disease type C" --top 40 --llm-backend template
```

Il ponte fenotipico e' stato costruito proprio per il fallimento descritto sopra. Ecco cosa e' cambiato.

### Esito: miglustat viene recuperato, in posizione 32 su 40

| | prima (fase 1) | dopo (fase 2) |
|---|---|---|
| UGCG raggiunto | **no**, a nessuna soglia | **si'**, via SMPD1 |
| miglustat nel ranking | **assente in assoluto** | **#32**, punteggio 0.491 |
| percorso | — | ponte fenotipico, marcato come tale |
| direzione | — | non determinabile, con motivazione esplicita |

Il percorso recuperato, per intero:

```
Niemann-Pick tipo C
  --somiglianza fenotipica 0.208-->  Niemann-Pick tipo A (OMIM:257200)
      fenotipi condivisi: cellule schiumose midollari, ascite,
      regressione dello sviluppo, splenomegalia, epatomegalia, ipotonia
  --gene causale-->                  SMPD1
  --pathway (58 geni)-->             Glycosphingolipid metabolism (R-HSA-1660662)
  --bersaglio-->                     UGCG
  --farmaco approvato, inhibitor-->  MIGLUSTAT
      riportato da ChEMBL, TEND, TTD, TdgClinicalTrial
      PubMed: 123 articoli farmaco+malattia, 114 farmaco+gene causale
```

**Il ponte utile non e' quello previsto.** Prima di eseguire, l'ipotesi era che il collegamento passasse per la malattia di Gaucher, che condivide con NPC il metabolismo dei glucosilceramidi. Il percorso effettivamente trovato passa invece per **Niemann-Pick tipo A**, deficit di sfingomielinasi: fenotipicamente piu' vicino e biologicamente altrettanto sensato. Gaucher resta intorno alla trentacinquesima posizione per somiglianza e non entra fra i ponti usati.

### Perche' 32 e non 5, e perche' non e' stato "sistemato"

Le componenti del punteggio di miglustat:

| Componente | Valore | Peso | Contributo |
|---|---:|---:|---:|
| prossimita' nel pathway | 0.600 | 0.25 | 0.150 |
| specificita' del pathway | 0.234 | 0.15 | 0.035 |
| coerenza direzionale | 0.300 | 0.25 | 0.075 |
| supporto delle fonti | 1.000 | 0.10 | 0.100 |
| presenza in letteratura | 1.000 | 0.10 | 0.100 |
| direttezza del percorso | 0.208 | 0.15 | 0.031 |
| **totale** | | | **0.491** |

Due componenti lo trattengono, ed entrambe **devono** trattenerlo:

- **direttezza 0.208** — e' la penalita' del ponte, ed e' voluta. Un candidato raggiunto per somiglianza clinica non deve competere alla pari con uno ancorato al gene causale della malattia interrogata.
- **coerenza direzionale 0.30** — il meccanismo curato di NPC non si trasferisce a SMPD1, che e' il gene causale di un'altra malattia. Perdita o guadagno di funzione sono proprieta' di una coppia gene-malattia, non del gene da solo, e lo strumento lo dichiara invece di assumerlo.

Sarebbe stato facile alzare miglustat riducendo la penalita' del ponte. Non e' stato fatto: tarare un parametro sul caso che si vuole far funzionare produce uno strumento che sembra funzionare. **Il criterio adottato e' che miglustat sia raggiungibile e tracciabile, non che sia primo.**

### Il rumore in testa alla classifica

I primi undici candidati (genisteina, resveratrolo, piperina, lansoprazolo, niclosamide fra gli altri) sono tutti interazioni dirette su NPC1 riportate da DGIdb. Quasi certamente sono artefatti di aggregazione da saggi di screening, non relazioni farmacologiche significative.

E' un limite reale e non risolto: lo scoring premia la direttezza, e su NPC i collegamenti diretti sono in larga parte rumore. Lo strumento li marca tutti `direzione non determinabile` ed `evidenza limitata`, il che e' corretto ma non basta a spostarli in basso.

### Il costo dell'allargamento

| | senza ponte | con ponte (30 malattie) |
|---|---:|---:|
| geni raggiunti | 75 | 2 233 |
| interazioni approvate | ~700 | 5 015 |
| candidati distinti | ~250 | 1 448 |
| durata | ~1 min | ~15 min alla prima esecuzione, poi in cache |

Quasi tutto il materiale aggiunto e' rumore. Il ponte compra un caso recuperato al prezzo di un'ampia dispersione, ed e' per questo che si disattiva con `--no-phenotype-bridge`.

---

## Un difetto architetturale scoperto strada facendo

Il caso NPC ha rivelato un problema che non riguardava il ponte ma la pipeline intera.

La letteratura si interroga solo su una selezione di candidati, perche' PubMed ha un rate limit. Ma la selezione avveniva con un punteggio che **non conteneva ancora la componente di letteratura**, ed era fissa ai primi quaranta. Miglustat si colloca al **253esimo posto preliminare** con 0.391, contro 0.467 del quarantesimo: veniva escluso **prima** di poter mostrare l'unica evidenza che lo distingueva, cioe' i 237 articoli che gia' collegano quel farmaco a quella malattia.

La correzione non e' stata alzare il numero, ma sostituirlo con un criterio: la selezione include tutti i candidati entro il **peso massimo della componente omessa** (0.10) dalla soglia. Nessun candidato escluso puo' quindi superarla. Il criterio si autoregola, e su NPC produce 250 candidati invece di 40.

Resta un tetto massimo per contenere il costo. Quando quel tetto taglia, lo strumento lo dichiara a schermo, perche' un risultato che potrebbe aver perso candidati non deve sembrare completo.

---

## Fase 1 verificata con un modello locale reale

La pipeline e' stata eseguita con Ollama su hardware modesto (AMD Ryzen 3 2200U, senza GPU utilizzabile).

| Modello | Tempo per candidato | Esito |
|---|---:|---|
| `qwen2.5:7b-instruct` | ~480 s | 1.19 token/s; 3 su 3 generate e validate, 2 respingimenti recuperati al secondo tentativo |
| `qwen2.5:3b-instruct` | ~190 s | 3 su 3 generate e validate |

Il 7B **funziona** anche su questa macchina: e' solo lento. Il modello
predefinito del progetto e' e resta il 7B; il 3B e' stato usato solo per
accorciare i cicli di prova.

Un report da quaranta candidati a 7B su questa CPU sarebbe pero' di circa sei
ore e mezza. Per questo esiste `--narrate-top N`: il modello narra i primi N
candidati, il generatore deterministico i restanti, e il report dichiara
candidato per candidato da dove viene la prosa. Lo stesso report scende sotto
l'ora senza perdere nulla di verificabile.

**Tre difetti reali sono emersi solo eseguendo con un modello vero:**

1. **Il validatore respingeva generazioni corrette.** Il modello citava RHEB e AKT1, che compaiono nella motivazione curata della coerenza direzionale — cioe' gli erano stati forniti da noi — ma non figuravano fra i geni consentiti. L'invariante corretta non e' «puo' citare cio' che sta nel bundle» ma **«puo' citare cio' che gli e' stato mostrato»**: il vocabolario ora deriva dal prompt stesso.
2. **L'ordinamento non era riproducibile.** Sirolimus, everolimus e temsirolimus ottengono lo stesso identico punteggio e comparivano in ordine diverso a ogni esecuzione, contraddicendo l'impronta di configurazione dichiarata in intestazione.
3. **Il lessico vietato non reggeva le flessioni.** L'elenco conteneva `conferma che` e ha lasciato passare `confermano che`: qwen2.5:3b ha prodotto un testo che dichiarava l'ipotesi «coerente e affidabile». Il controllo e' ora basato su radici con espressioni regolari, e il testo reale sfuggito e' diventato un test di regressione.

**Un quarto difetto, trovato solo eseguendo il modello grande fino in fondo.**
Il 7B ha prodotto: «il meccanismo ipotizzato per **l'efficacia** del sirolimus»,
«**confermando** l'interazione», «la coerenza e' **altamente probabile**».
Nessuna delle tre era intercettata. La prima e' la piu' grave: non afferma
l'efficacia, la **presuppone**, trattandola come un fatto esistente di cui si
discute il meccanismo — ed e' precisamente cio' che il disclaimer del progetto
dichiara non debba mai comparire.

### Vietare non basta: bisogna riformulare cio' che si mostra

Chiudere la falla ha richiesto tre iterazioni, e le prime due hanno fallito in
modi istruttivi. Tutte misurate sullo stesso caso, tre candidati con
`qwen2.5:7b-instruct`:

| Intervento | Generate e validate | Ripieghi |
|---|---:|---:|
| Validatore severo, prompt invariato | **0 / 3** | 3 |
| + prompt allineato al validatore | 1 / 3 | 2 |
| + fatti riformulati nel bundle | **3 / 3** | **0** |

**Primo tentativo — vietare la radice.** Bandita `efficac`, il 7B ha iniziato a
fallire sistematicamente. Il modello stava seguendo le istruzioni che aveva:
erano le istruzioni a non menzionare la nuova regola. *Un validatore piu' severo
del prompt non produce output migliori, produce solo ripieghi.*

**Secondo tentativo — allineare il prompt.** Meglio, ma il modello continuava a
scrivere «la coerenza del meccanismo e' confermata» nonostante il divieto
esplicito. Un modello da sette miliardi di parametri **non rispetta in modo
affidabile una proibizione lessicale esplicita**.

**Terzo tentativo — riformulare il fatto.** Il bundle passava
`coerenza_direzionale.esito: "coerente"`, e quel campo *invitava* la frase
vietata. Ora passa `valutazione_euristica: "compatibile secondo la valutazione
euristica, mai verificata sperimentalmente"`. L'etichetta porta con se' la
propria riserva, e il modello non ha piu' ragione di aggiungere "confermata".

Il testo prodotto dopo la riformulazione:

> «Il meccanismo ipotizzato per l'**effetto** del sirolimus [...] La
> **valutazione euristica indica** che questa direzione e' **compatibile** con i
> fatti, anche se **non ancora verificata sperimentalmente**. [...] supportano la
> **plausibilita'** dell'ipotesi.»

**La lezione generalizzabile**: formulare il dato in modo che porti gia' il
proprio limite e' piu' efficace di qualunque divieto, e non e' un trucco di
prompting — rende il dato piu' onesto anche per chi legge il bundle JSON senza
alcun modello di mezzo.

### Cosa insegnano questi quattro difetti

Tutti e quattro sono emersi **eseguendo con modelli veri**, nessuno dai test
sintetici. E i due sul lessico portano una conclusione scomoda:

**i modelli grandi non sono piu' sicuri, sono piu' pericolosi.** Il 7B
sovradichiara meno spesso del 3B, ma quando lo fa produce prosa scorrevole e
plausibile, che un lettore assorbe senza attrito. Il 3B scriveva «coerente e
affidabile», che stona; il 7B scrive «il meccanismo ipotizzato per l'efficacia»,
che suona come una frase di un articolo scientifico. La qualita' linguistica e
l'affidabilita' epistemica non crescono insieme.

E' anche la ragione per cui il generatore deterministico non e' un ripiego
degradato: e' l'unico testo di cui si possa dimostrare che non presuppone nulla.

---

## Controllo negativo

```bash
repurposerd run "tuberous sclerosis" --shuffle-control --seed 1 --no-literature
```

Sostituendo il gene causale con uno casuale e lasciando identico tutto il resto, su tre semi:

| Seme | Gene sostitutivo | Miglior punteggio | Livello | Direzione |
|---|---|---:|---|---|
| 1 | STEEP1 | — | nessun candidato sopra soglia | — |
| 2 | POLDIP3 | 0.363 | debole | non determinabile |
| 3 | NCF1 | 0.534 | limitata | non determinabile |

Contro 0.758 / moderata / coerente del caso reale. La separazione c'e'.

**Ma il controllo e' piu' debole di quanto il margine suggerisca**: il gene casuale non ha, per costruzione, relazioni curate in `config/mechanism.yaml`, quindi non puo' ottenere punti di coerenza direzionale (0.25 del totale). Il confronto misura in parte "malattia curata contro malattia non curata". Escludendo la componente direzionale, sirolimus scende a circa 0.51 e il miglior controllo sale a circa 0.36: distinti, ma di un margine molto piu' stretto.

---

## Conclusione onesta sui due piloti

**Caso 1, sclerosi tuberosa: riuscito senza riserve.** Il meccanismo passa per un pathway co-annotato e la relazione con segno e' curata; i tre controlli positivi occupano i primi tre posti con direzione coerente.

**Caso 2, Niemann-Pick tipo C: recuperato, non risolto.** Il ponte fenotipico porta miglustat da irraggiungibile a trentaduesimo, con percorso tracciabile e provenienza completa. Un ricercatore che scorre quaranta candidati lo trova; uno che ne guarda quindici no. E i primi undici posti restano occupati da quello che e' quasi certamente rumore di aggregazione.

**Cosa questi due casi non dimostrano.** Due malattie non bastano a giudicare uno strumento, e sono entrambe patologie ben studiate, con letteratura abbondante e annotazioni ricche. Il comportamento su una malattia poco studiata, con pochi fenotipi annotati e nessun pathway specifico, non e' stato misurato, e c'e' ragione di aspettarsi che sia sensibilmente peggiore.

Un'assenza di risultati non e' evidenza di assenza, e un elenco pieno non e' evidenza di successo. Chi legge un report deve saperlo.
