# Banco di prova — copertura sui riposizionamenti noti

> [!NOTE]
> Questo documento misura la **copertura**: se il farmaco atteso compaia fra i candidati e in che posizione. **Non misura la precisione.** Un candidato non atteso non e' un falso positivo: potrebbe essere un'ipotesi legittima che nessuno ha ancora studiato. Leggerlo come una misura di correttezza complessiva sarebbe un errore.

## Configurazione

- **Impronta**: `0291af9be1f5` — confrontabile solo con report che riportano la stessa impronta
- **Candidati esaminati per caso**: 40
- **Letteratura**: interrogata
- **Ponte fenotipico**: attivo
- **Eseguito il**: 2026-09-02 11:34

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
| `gaucher-miglustat` | Gaucher disease | miglustat | in indicazione | #3 | 0.610 | diretto (UGCG) |
| `gaucher-eliglustat` | Gaucher disease | eliglustat | in indicazione | #8 | 0.560 | diretto (UGCG) |
| `progeria-lonafarnib` | Hutchinson-Gilford progeria syndrome | lonafarnib | riposizionamento | #1 | 0.719 | diretto (LMNA) |
| `alkaptonuria-nitisinone` | alkaptonuria | nitisinone | riposizionamento | #1 | 0.679 | diretto (HPD) |
| `sca-hydroxyurea` | sickle cell anemia | hydroxyurea | riposizionamento | **non trovato** | — | — |
| `pah-sildenafil` | pulmonary arterial hypertension | sildenafil | riposizionamento | #18 | 0.604 | diretto (NOS3) |
| `marfan-losartan` | Marfan syndrome | losartan | riposizionamento | **non trovato** | — | — |
| `fop-palovarotene` | fibrodysplasia ossificans progressiva | palovarotene | riposizionamento | **non trovato** | — | — |
| `cf-ivacaftor` | cystic fibrosis | ivacaftor | in indicazione | #2 | 0.794 | diretto (CFTR) |
| `fabry-migalastat` | Fabry disease | migalastat | in indicazione | #1 | 0.721 | diretto (GLA) |
| `tyrosinemia-nitisinone` | tyrosinemia type 1 | nitisinone | in indicazione | #1 | 0.679 | diretto (HPD) |
| `aip-givosiran` | acute intermittent porphyria | givosiran | in indicazione | #1 | 0.700 | diretto (HMBS) |
| `fh-evolocumab` | familial hypercholesterolemia | evolocumab | in indicazione | #2 | 0.722 | diretto (PCSK9) |
| `sma-risdiplam` | spinal muscular atrophy, type 1 | risdiplam | in indicazione | #1 | 0.638 | diretto (SMN1) |
| `hpp-asfotase` | hypophosphatasia | asfotase alfa | in indicazione | #2 | 0.622 | diretto (ALPL) |
| `attr-tafamidis` | ATTRV30M amyloidosis | tafamidis | in indicazione | #3 | 0.730 | diretto (TTR) |
| `cystinosis-cysteamine` | cystinosis | cysteamine | in indicazione | **non trovato** | — | — |
| `wilson-trientine` | Wilson disease | trientine | fallimento atteso | correttamente non trovato | — | — |

## Come usare questi numeri

- **Per confrontare configurazioni**: eseguire il banco prima e dopo una modifica ai pesi e confrontare la copertura e la posizione mediana. Due report con impronta di configurazione diversa non sono confrontabili sui punteggi assoluti, ma lo sono sugli ordinamenti.
- **Non per dichiarare che lo strumento funziona.** Ventidue casi sono pochi, e sono tutti riposizionamenti gia' noti e quindi gia' studiati, con letteratura abbondante. Il comportamento su un accostamento che nessuno ha ancora esaminato non e' misurato qui e non e' misurabile con un banco costruito sui casi riusciti.
- **Attenzione alla circolarita'.** La componente di letteratura premia gli accostamenti gia' studiati, e tutti i casi di questo banco lo sono. La copertura misurata e' quindi una stima ottimistica.
