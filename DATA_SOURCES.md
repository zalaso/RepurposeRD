# Fonti dati

## Principio: il repository distribuisce codice, non dati

RepurposeRD non ridistribuisce alcun dato biomedico. Distribuisce il codice ETL che scarica le fonti sulla macchina di chi lo usa, registrando per ciascuna licenza, versione, data di accesso e checksum SHA-256 in `data/raw/manifest.json`.

Questa scelta non e' solo prudenza legale. Le fonti aperte in ambito biomedico hanno licenze eterogenee, alcune con clausole di condivisione allo stesso modo (share-alike) che si propagherebbero a qualunque database derivato ridistribuito. Non ridistribuendo nulla, il problema non si pone: ogni utente acquisisce i dati direttamente dalla fonte, alle condizioni che la fonte stessa pone.

`data/` e' in `.gitignore`, e ci resta.

---

## Fonti integrate (fase 1)

### HGNC — HUGO Gene Nomenclature Committee
- **Licenza**: CC0 1.0 (pubblico dominio)
- **Ruolo**: normalizzazione dei simboli genici, mapping `symbol → Entrez ID → UniProt`
- **Perche' serve**: Reactome indicizza i geni per NCBI Gene ID, mentre Orphanet e DGIdb usano i simboli. Senza questo ponte le tre fonti non si parlano.
- **File**: `hgnc_complete_set.txt` (~17 MB)

### Mondo Disease Ontology
- **Licenza**: CC BY 4.0
- **Ruolo**: identificatore canonico della malattia, cross-reference verso Orphanet e OMIM, gerarchia `is_a`
- **Nota**: si usa il subset `mondo-rare` (~33 MB) invece della release completa (~240 MB). Copre esattamente il dominio del progetto. La conseguenza e' che le malattie non rare non sono risolvibili, il che e' voluto.
- **File**: `mondo-rare.obo`

### Orphanet / Orphadata
- **Licenza**: CC BY 4.0, dichiarata all'interno del file stesso
- **Ruolo**: associazioni malattia-gene curate, con il **tipo** di associazione e i PMID di validazione
- **Perche' e' la fonte giusta**: distingue esplicitamente `Disease-causing germline mutation(s) in` da `Modifying germline mutation in` e da `Candidate gene tested in`. Solo il primo gruppo viene accettato come causale. Nella sclerosi tuberosa e' questa distinzione a tenere fuori IFNG, che Orphanet annota come modificatore.
- **File**: `en_product6.xml` (~23 MB)

### Reactome
- **Licenza**: CC0 1.0
- **Ruolo**: appartenenza gene-pathway e gerarchia fra pathway. E' il ponte meccanicistico su cui si regge l'intero metodo.
- **File**: `NCBI2Reactome_All_Levels.txt` (~98 MB, filtrato a *Homo sapiens* in fase di caricamento), `ReactomePathwaysRelation.txt`, `ReactomePathways.txt`

### DGIdb v5
- **Licenza**: il codice e l'aggregato sono aperti; le singole interazioni provengono da fonti a monte con licenze eterogenee
- **Ruolo**: interazioni farmaco-gene, tipo di interazione, stato di approvazione regolatoria
- **Come si gestisce l'eterogeneita'**: la colonna `interaction_source_db_name` viene propagata fino al report, cosi' la provenienza a monte di ogni singola interazione resta visibile a chi la legge e verificabile alle condizioni della fonte originale.
- **File**: `dgidb_interactions.tsv` (~12 MB)

### HPO — Human Phenotype Ontology

- **Licenza**: **propria, non standard** — vedi la nota qui sotto
- **Ruolo**: similarita' fenotipica fra malattie rare, che alimenta il ponte fenotipico (seconda strategia di ricerca)
- **File**: `hp-base.obo` (~12 MB), `phenotype.hpoa` (~36 MB)

> [!IMPORTANT]
> **Lo stato della licenza HPO non e' verificabile automaticamente.**
>
> L'ontologia dichiara `dcterms:license` con valore `https://hpo.jax.org/app/license`.
> Alla data di verifica (2026-09-01) quell'URL restituisce **404**, e il registro
> OBO Foundry riporta per HPO una licenza propria (`hpo`), non una Creative Commons.
>
> Non potendo verificare i termini esatti, questo progetto **non li asserisce**.
> La voce in `config/sources.yaml` li dichiara come incerti, e la stessa nota
> compare nel report generato. Poiche' lo strumento non ridistribuisce dati,
> l'obbligo di verifica ricade su chi li scarica: **prima di un uso commerciale
> o di una ridistribuzione, verificare i termini correnti presso HPO.**

Le annotazioni usate sono solo quelle con `aspect = P` (anomalia fenotipica) e
senza qualifier `NOT`. Le righe di modalita' di trasmissione e decorso clinico
sono escluse: includerle farebbe somigliare fra loro tutte le malattie
autosomiche recessive a prescindere dal quadro clinico.

### openFDA — Drug Labeling API
- **Licenza**: pubblico dominio (opera del governo statunitense)
- **Ruolo**: conferma indipendente dell'approvazione e delle indicazioni etichettate
- **Stato**: interrogata via API sui soli candidati finali, non scaricata in blocco

**Perche' serve davvero.** DGIdb porta una colonna `approved`, ma e' un aggregato
di fonti eterogenee e si e' rivelato inaffidabile: nel caso pilota della sclerosi
tuberosa, due candidati su otto marcati `approved` non hanno alcuna etichetta FDA
(uno e' un inibitore mTOR sperimentale mai autorizzato). openFDA rende visibile la
discordanza.

Il secondo valore, meno ovvio, e' che mostrare **per cosa** un farmaco sia
etichettato rende evidente che l'ipotesi e' fuori indicazione. Un report che
riporta «indicato per la profilassi del rigetto d'organo» accanto a una proposta
su un'altra malattia dice al revisore, senza spiegazioni, di che salto si tratta.

> [!NOTE]
> **Non entra nel punteggio, ed e' una scelta deliberata.** openFDA copre gli
> Stati Uniti. Usarla per ordinare i candidati penalizzerebbe i farmaci approvati
> solo altrove, che nelle malattie rare sono molti: miglustat e' autorizzato da
> EMA per Niemann-Pick tipo C, indicazione che l'FDA non ha mai concesso. Un
> candidato non e' piu' debole perche' e' stato approvato a Bruxelles anziche' a
> Silver Spring, e codificare quella distinzione in un punteggio scientifico
> significherebbe inserirvi una distorsione geografica.
>
> L'assenza di etichetta FDA nel report non va quindi letta come "non approvato".

### PubMed / NCBI E-utilities
- **Licenza**: i metadati bibliografici sono liberamente riutilizzabili; **il testo degli abstract puo' essere protetto da copyright**
- **Ruolo**: grounding delle ipotesi su letteratura reale
- **Politica adottata**:
  - si memorizzano soltanto PMID, titolo, rivista e anno
  - non si scaricano ne' si citano testualmente abstract o full text al di fuori del PMC Open Access subset
  - nessuno scraping oltre le E-utilities, che sono l'interfaccia che NCBI mette a disposizione proprio per questo uso
  - il rate limit e' rispettato (3 richieste al secondo senza API key, 10 con), e le risposte sono messe in cache per non ripetere le stesse chiamate

---

## Fonti deliberatamente escluse

Elencarle e' importante quanto elencare quelle incluse: una fonte assente puo' sembrare una dimenticanza, e qui non lo e'.

### DisGeNET — esclusa per licenza

Dal 2023 DisGeNET e' passata a un modello commerciale. L'ultima release pienamente aperta (v7.0, 2020) e' distribuita sotto **CC BY-NC-SA 4.0**:

- la clausola **NonCommercial** e' incompatibile con un progetto pensato per essere usabile da chiunque, incluse aziende e spin-off accademici
- la clausola **ShareAlike** si propagherebbe a qualunque database derivato

**Sostituita da**: Orphanet (associazioni curate, CC BY 4.0), HGNC, e in fase 2 Open Targets Platform (CC0). Per le malattie monogeniche questa combinazione ha una curazione superiore a DisGeNET, che e' costruita per coprire anche associazioni statistiche deboli su malattie comuni.

### KEGG — esclusa per licenza

E' la risorsa di pathway piu' conosciuta, ma l'accesso programmatico e la ridistribuzione sono soggetti a licenza restrittiva, incompatibile con i vincoli del progetto.

**Sostituita da**: Reactome (CC0), che per le vie di segnalazione umane e' curata almeno altrettanto bene ed e' completamente aperta.

### OMIM (dati grezzi) — esclusa per licenza

La ridistribuzione dei dati OMIM richiede registrazione ed e' soggetta a restrizioni. Si usano soltanto gli **identificatori** OMIM come cross-reference, mai il contenuto.

---

## Fonti previste per la fase 2

Da integrare dopo la validazione della pipeline, in quest'ordine:

1. **Reactome a livello di reazione** — per derivare le relazioni regolatorie **con segno** dai dati, sostituendo o alimentando le annotazioni curate a mano in `config/mechanism.yaml`. E' il miglioramento singolo piu' importante che il progetto possa ancora ricevere.
2. ~~**HPO** — similarita' fenotipica come seconda strategia di ricerca~~ — **integrato**, vedi `pipeline/phenotype.py`
3. **Monarch Initiative KG** — collegamenti fra specie e associazioni da modelli animali
4. **ChEMBL** (CC BY-SA 3.0) — potenza e selettivita' delle interazioni, per raffinare il punteggio oltre il semplice "l'interazione esiste". Attenzione alla clausola ShareAlike sui derivati.
5. **Open Targets Platform** (CC0) — evidenza gene-malattia come controllo incrociato su Orphanet
6. **DrugCentral** (CC BY-SA 4.0) — indicazioni approvate strutturate, piu' ricche di openFDA

---

## Aggiungere una fonte

Ogni nuova fonte deve arrivare con:

1. una voce in `config/sources.yaml` che dichiari **licenza e URL della licenza**, non solo l'URL di download
2. un parser in `src/repurposerd/sources/parsers.py` con un test in `tests/test_parsers.py` che ne fissi il formato
3. la propagazione della `Provenance` fino al report: un fatto che non sa dire da dove viene non entra nell'evidence bundle
4. se la licenza ha clausole NC o SA, una nota esplicita su cosa comporta per i derivati

Una fonte tecnicamente utile ma con licenza incompatibile va nella sezione "escluse", con la motivazione. Il progetto preferisce essere meno completo che meno chiaro.
