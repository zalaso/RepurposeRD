# Banco di prova — copertura sui riposizionamenti noti

> [!NOTE]
> Questo documento misura la **copertura**: se il farmaco atteso compaia fra i candidati e in che posizione. **Non misura la precisione.** Un candidato non atteso non e' un falso positivo: potrebbe essere un'ipotesi legittima che nessuno ha ancora studiato. Leggerlo come una misura di correttezza complessiva sarebbe un errore.

## Configurazione

- **Impronta**: `4c2705204601` — confrontabile solo con report che riportano la stessa impronta
- **Candidati esaminati per caso**: 40
- **Letteratura**: interrogata
- **Ponte fenotipico**: attivo
- **Eseguito il**: 2026-09-02 16:09

## Risultati aggregati

Sui casi che **devono** essere trovati (riposizionamenti e farmaci in indicazione):

| Metrica | Valore |
|---|---|
| Trovati entro la posizione 5 | 14/21 (67%) |
| Trovati entro la posizione 10 | 15/21 (71%) |
| Trovati entro la posizione 20 | 16/21 (76%) |
| Trovati entro la posizione 40 | 17/21 (81%) |
| Posizione mediana dei trovati | 2 |
| Mai trovati | 4/21 |

Scomposto per tipo di caso:

| Tipo | Trovati entro 40 | Mediana |
|---|---|---|
| riposizionamento | 7/10 | 2 |
| in indicazione | 10/11 | 2 |

**Fallimenti attesi**: 1/1 correttamente non trovati. Se questo numero scendesse, lo strumento starebbe diventando promiscuo: alzerebbe la copertura restituendo tutto.

## Dettaglio

| Caso | Malattia | Farmaco atteso | Tipo | Esito | Punteggio | Percorso |
|---|---|---|---|---|---:|---|
| `tsc-sirolimus` | tuberous sclerosis | sirolimus | riposizionamento | #2 | 0.809 | diretto (MTOR) |
| `tsc-everolimus` | tuberous sclerosis | everolimus | riposizionamento | #1 | 0.809 | diretto (MTOR) |
| `lam-sirolimus` | lymphangioleiomyomatosis | sirolimus | riposizionamento | #2 | 0.704 | diretto (TSC1) |
| `npc-miglustat` | Niemann-Pick disease type C | miglustat | riposizionamento | #32 | 0.491 | ponte (UGCG) |
| `gaucher-miglustat` | Gaucher disease | miglustat | in indicazione | #4 | 0.610 | diretto (UGCG) |
| `gaucher-eliglustat` | Gaucher disease | eliglustat | in indicazione | #8 | 0.560 | diretto (UGCG) |
| `progeria-lonafarnib` | Hutchinson-Gilford progeria syndrome | lonafarnib | riposizionamento | #1 | 0.719 | diretto (LMNA) |
| `alkaptonuria-nitisinone` | alkaptonuria | nitisinone | riposizionamento | #1 | 0.679 | diretto (HPD) |
| `sca-hydroxyurea` | sickle cell anemia | hydroxyurea | riposizionamento | **non trovato** | — | — |
| `pah-sildenafil` | pulmonary arterial hypertension | sildenafil | riposizionamento | #20 | 0.604 | diretto (NOS3) |
| `marfan-losartan` | Marfan syndrome | losartan | riposizionamento | **non trovato** | — | — |
| `fop-palovarotene` | fibrodysplasia ossificans progressiva | palovarotene | riposizionamento | **non trovato** | — | — |
| `cf-ivacaftor` | cystic fibrosis | ivacaftor | in indicazione | #2 | 0.969 | diretto (CFTR) |
| `fabry-migalastat` | Fabry disease | migalastat | in indicazione | #1 | 0.721 | diretto (GLA) |
| `tyrosinemia-nitisinone` | tyrosinemia type 1 | nitisinone | in indicazione | #1 | 0.679 | diretto (HPD) |
| `aip-givosiran` | acute intermittent porphyria | givosiran | in indicazione | #1 | 0.700 | diretto (HMBS) |
| `fh-evolocumab` | familial hypercholesterolemia | evolocumab | in indicazione | #2 | 0.722 | diretto (PCSK9) |
| `sma-risdiplam` | spinal muscular atrophy, type 1 | risdiplam | in indicazione | #1 | 0.638 | diretto (SMN1) |
| `hpp-asfotase` | hypophosphatasia | asfotase alfa | in indicazione | #2 | 0.622 | diretto (ALPL) |
| `attr-tafamidis` | ATTRV30M amyloidosis | tafamidis | in indicazione | #2 | 0.794 | diretto (TTR) |
| `cystinosis-cysteamine` | cystinosis | cysteamine | in indicazione | **non trovato** | — | — |
| `wilson-trientine` | Wilson disease | trientine | fallimento atteso | correttamente non trovato | — | — |

## Confronto con la baseline precedente (`0291af9be1f5`)

La derivazione del meccanismo di malattia da Orphanet ha portato la copertura del
meccanismo da 3 casi su 22 a 7. **Il recupero non e' cambiato di un solo caso**:

| Metrica | `0291af9be1f5` | `4c2705204601` |
|---|---|---|
| Trovati entro 40 | 17/21 | 17/21 |
| Posizione mediana | 2 | 2 |
| Riposizionamenti veri | 7/10 | 7/10 |
| Fallimenti attesi | 1/1 | 1/1 |

Questo **conferma** quanto `LIMITATIONS.md` punto 2 sosteneva senza poterlo
dimostrare: la conoscenza direzionale non migliora il recupero, migliora la
calibrazione della fiducia. Il contrario sarebbe stato sospetto — una componente
che non entra nel recupero non dovrebbe spostarne i numeri.

Dove l'effetto si vede davvero e' nel punteggio dei singoli casi:

| Caso | Prima | Ora | Perche' |
|---|---|---|---|
| `cf-ivacaftor` | #2, 0.794 | #2, **0.969** | la fibrosi cistica guadagna `perdita di funzione` da Orphanet, e ivacaftor agisce su CFTR stesso: a distanza zero il solo meccanismo basta a rendere la direzione coerente |
| `attr-tafamidis` | #3, 0.730 | **#2**, 0.794 | stessa dinamica su TTR |
| `gaucher-miglustat` | #3, 0.610 | #4, 0.610 | punteggio invariato: si e' mosso chi lo circonda |
| `pah-sildenafil` | #18, 0.604 | #20, 0.604 | idem |

**Due casi su ventidue guadagnano punteggio, ed entrambi sono a distanza zero.**
E' esattamente la previsione del punto 2: per un farmaco che agisce sul gene
causale stesso il meccanismo di malattia basta, perche' l'identita' vale come
arco positivo; per un candidato a uno o due passi serve anche il **segno** della
relazione, che resta curato a mano su tre archi. Finche' quel segno non viene
derivato dai dati, i 15 casi trovati a distanza maggiore di zero restano bloccati
a evidenza `limitata` anche quando sono corretti.

## Come usare questi numeri

- **Per confrontare configurazioni**: eseguire il banco prima e dopo una modifica ai pesi e confrontare la copertura e la posizione mediana. Due report con impronta di configurazione diversa non sono confrontabili sui punteggi assoluti, ma lo sono sugli ordinamenti.
- **Non per dichiarare che lo strumento funziona.** Ventidue casi sono pochi, e sono tutti riposizionamenti gia' noti e quindi gia' studiati, con letteratura abbondante. Il comportamento su un accostamento che nessuno ha ancora esaminato non e' misurato qui e non e' misurabile con un banco costruito sui casi riusciti.
- **Attenzione alla circolarita'.** La componente di letteratura premia gli accostamenti gia' studiati, e tutti i casi di questo banco lo sono. La copertura misurata e' quindi una stima ottimistica.
