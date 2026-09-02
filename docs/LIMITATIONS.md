# Limiti noti

Questo documento e' scritto per essere letto **prima** di fidarsi di un report, non dopo. Elenca cio' che il metodo non puo' fare, incluse le debolezze che non hanno ancora una soluzione.

---

## 1. La co-appartenenza a un pathway non e' un meccanismo

Il presupposto dello strumento e' che due geni annotati nello stesso pathway Reactome siano funzionalmente vicini, e che un farmaco che agisce su uno possa influenzare il processo alterato dall'altro.

E' un'euristica ragionevole, ed e' anche il ragionamento che ha portato a riposizionamenti reali. Ma un pathway e' una descrizione curata di un processo biologico, non un circuito con una topologia causale definita. Due geni possono comparire nello stesso pathway e non interagire mai, agire in compartimenti cellulari diversi, o essere espressi in tessuti diversi.

**Cosa mitiga il problema**: il tetto alla dimensione del pathway (`max_pathway_size`, default 200), la penalita' per la distanza (hop), e la componente di coerenza direzionale.
**Cosa resta**: nulla di tutto questo verifica che i due geni interagiscano davvero nel contesto della malattia.

---

## 1-bis. Il metodo non vede la fisiopatologia a valle

Emerso dal caso pilota Niemann-Pick tipo C (vedi `docs/PILOT_RESULTS.md`), ed e' il limite piu' importante scoperto eseguendo il pilota anziche' ragionandoci sopra.

Miglustat e' un riposizionamento reale e documentato su NPC: inibisce UGCG, riducendo la sintesi dei glucosilceramidi. Lo strumento **non lo trova**, e non per una soglia troppo stretta: **NPC1 e UGCG non condividono alcun pathway Reactome, a nessuna dimensione**. In Reactome NPC1 sta nel ramo del trasporto delle lipoproteine, UGCG nel ramo del metabolismo sfingolipidico, e i due rami non si incontrano in alcuna unita' annotata.

Il collegamento reale non e' una co-appartenenza a un pathway: e' fisiopatologia a valle. Il difetto di trasporto del colesterolo causa un accumulo **secondario** di sfingolipidi, e il farmaco agisce su quello.

**Conseguenza**: il metodo cattura i casi in cui il farmaco agisce sullo **stesso processo** alterato, e non quelli in cui agisce su una **conseguenza** di quel processo. La sclerosi tuberosa e' del primo tipo, Niemann-Pick C del secondo. Nessuna taratura dei parametri cambia questo.

**Cosa peggiora il problema**: lo strumento non da' alcun segnale di stare fallendo. Nel caso NPC produce dieci candidati dall'aspetto plausibile, nessuno dei quali e' quello giusto. Un elenco pieno non e' evidenza di successo.

**Stato**: parzialmente mitigato dal **ponte fenotipico** (vedi limite 1-ter). Su Niemann-Pick il ponte raggiunge effettivamente UGCG, il bersaglio di miglustat, passando per SMPD1 (Niemann-Pick tipo A). Il punto cieco resta pero' reale ogni volta che nessuna malattia fenotipicamente simile porta al bersaglio giusto.

---

## 1-ter. Il ponte fenotipico e' a bassa precisione, per natura

Il ramo fenotipico prende i geni causali di malattie clinicamente somiglianti e li usa come punto di ingresso aggiuntivo. Serve a raggiungere cio' che il ramo pathway non vede, e su Niemann-Pick funziona: UGCG viene raggiunto tramite SMPD1, gene causale di Niemann-Pick tipo A.

Ma il prezzo e' alto e va detto:

- **La somiglianza clinica non e' parentela meccanicistica.** Epatosplenomegalia e atassia accomunano molte malattie da accumulo lisosomiale per ragioni diverse fra loro. Due malattie possono somigliarsi per convergenza sintomatica senza condividere nulla a livello molecolare.
- **Il ramo allarga moltissimo lo spazio di ricerca.** Su Niemann-Pick tipo C, 30 malattie-ponte aggiungono circa 2100 geni ai 75 del ramo diretto, e le interazioni farmaco-gene approvate passano da poche centinaia a oltre cinquemila. Quasi tutto quel materiale e' rumore.
- **La soglia sul numero di ponti e' un compromesso, non un ottimo.** Misurato: la malattia di Gaucher, che porta il riposizionamento noto per NPC, si colloca intorno alla trentacinquesima posizione per somiglianza. Nessuna metrica fra quelle valutate (Jaccard pesato per IC, copertura asimmetrica, media geometrica) la porta nei primi dieci: NPC somiglia clinicamente a molte malattie e Gaucher e' una fra queste.
- **La metrica non e' stata scelta guardando il risultato desiderato.** La variante asimmetrica avrebbe alzato Gaucher, ma ha in testa sindromi generiche iper-annotate, che e' un artefatto noto. Si e' tenuto il Jaccard pesato perche' e' simmetrico e standard, non perche' favorisse il caso pilota.

**Come si mitiga**: la componente `route_directness` penalizza esplicitamente i candidati del ponte in proporzione alla loro somiglianza (tipicamente 0.15-0.35 contro 1.0 dei diretti), e il report li marca uno per uno. `--no-phenotype-bridge` disattiva il ramo per chi vuole solo il percorso meccanicistico.

---

## 1-quater. La preselezione per la letteratura puo' ancora perdere candidati

PubMed si interroga solo su una selezione di candidati, perche' interrogare un'API pubblica gratuita per millecinquecento voci sarebbe un abuso. Ma la selezione avviene con un punteggio che non contiene ancora la componente di letteratura.

Il difetto era grave e misurato: con una selezione fissa ai primi quaranta, miglustat — al 253esimo posto preliminare con 0.391, contro 0.467 del quarantesimo — veniva escluso **prima** di poter mostrare l'unica evidenza che lo distingue.

**Corretto** con un criterio che si autoregola: la selezione include tutti i candidati entro il peso massimo della componente omessa (0.10) dalla soglia. Nessun candidato escluso puo' quindi superarla.

**Cosa resta**: un tetto massimo (`literature_shortlist_cap`, 400) per contenere il costo. Quando quel tetto taglia, la garanzia non vale piu'. Lo strumento lo dichiara a schermo, ma un run troncato puo' avere perso candidati legittimi.

---

## 2. La direzione dell'effetto e' nota solo in parte

La valutazione direzionale richiede due ingredienti: il **meccanismo della malattia** (perdita o guadagno di funzione) e il **segno della relazione** fra gene causale e bersaglio del farmaco. Lo stato dei due e' molto diverso.

**Il meccanismo di malattia e' in gran parte risolto.** Orphanet lo dichiara esplicitamente nel tipo di associazione gene-malattia, e viene derivato automaticamente per **1.025 malattie** risolvibili a un termine Mondo — contro le 2 che erano curate a mano. Resta `unknown` dove nemmeno Orphanet lo dichiara, che e' la maggioranza delle voci, e dove i geni causali della stessa malattia portano annotazioni in conflitto: in quel caso non si sceglie a maggioranza, si dichiara l'incertezza.

**Il segno della relazione e' ancora interamente a mano**, e copre tre archi. Nessuna fonte di fase 1 lo fornisce: Reactome lo contiene a livello di reazione, ma il file di appartenenza gene-pathway usato qui non lo espone. E' quel che resta del punto (b).

**Cosa comporta in pratica**: per un candidato a distanza zero — il farmaco agisce sul gene causale stesso — il solo meccanismo di malattia basta, perche' l'identita' vale come arco positivo. Per un candidato a distanza uno o due serve anche il segno, e senza quello la direzione resta ignota anche quando il meccanismo e' noto.

**Cosa comporta, misurato sul banco di prova.** Prima della derivazione da Orphanet, solo **3 casi su 22** avevano un meccanismo; ora sono 7. Il banco pero' restituiva gia' 17/21 trovati e posizione mediana 2 **quando erano 3**.

Questo **smentisce** un'affermazione che compariva qui in precedenza, secondo cui lo strumento avrebbe funzionato alle capacita' documentate solo sulla sclerosi tuberosa. Non e' cosi', e la distinzione e' importante:

- **L'ordinamento regge senza il layer curato.** Sono la prossimita' nel pathway, il supporto delle fonti e la letteratura a portare il farmaco atteso in alto. Sette riposizionamenti su dieci vengono trovati con direzione ignota.
- **Il livello di evidenza no.** Con direzione `unknown` il tetto lo blocca a `limitata`, quindi per 19 casi su 22 la fiducia dichiarata e' **sistematicamente sottostimata**. Un candidato corretto e ben posizionato viene presentato al lettore come piu' debole di quanto sia.

**Quindi la curazione direzionale migliora la calibrazione della fiducia, non il recupero.** E' un miglioramento importante — un livello di evidenza sempre prudente e' quasi altrettanto inutile di uno sempre ottimista — ma non e' il prerequisito che sembrava prima di misurarlo.

**Come si risolve**: derivare le relazioni con segno dai dati di regolazione a livello di reazione di Reactome.

---

## 3. Il controllo negativo e' piu' debole di quanto sembri

`--shuffle-control` sostituisce il gene causale con uno casuale e lascia il resto identico. Nei test su tre semi, i candidati di controllo si fermano a punteggi di 0.33–0.53 con direzione sempre `non determinabile`, contro 0.758 e direzione `coerente` del caso reale.

Il controllo sostituisce **entrambi** gli ingressi biologici: il gene causale e il profilo fenotipico che alimenta il ponte. In una versione precedente il ponte veniva semplicemente disattivato durante il controllo, il che lasciava meta' della pipeline senza verifica; alimentarlo con il profilo vero gli avrebbe invece dato vicini autentici, cioe' un vantaggio che al controllo non spetta.

**Resta pero' un limite**: il gene casuale non ha, per costruzione, alcuna relazione curata in `mechanism.yaml`, quindi non puo' ottenere punti di coerenza direzionale. Il confronto misura in parte "malattia curata contro malattia non curata", non solo "biologia reale contro biologia casuale". Un controllo piu' severo richiederebbe archi con segno derivati automaticamente, e ricade quindi nel limite 2.

---

## 4. Il conteggio di letteratura misura attenzione, non efficacia

Un accostamento farmaco-malattia molto rappresentato in letteratura puo' esserlo perche' e' promettente, oppure perche' e' stato studiato e ripetutamente smentito. Il conteggio non distingue i due casi, e lo strumento non legge gli abstract.

C'e' anche una distorsione strutturale: i farmaci vecchi, molto usati e molto studiati accumulano articoli su qualunque argomento. Per questo la componente di letteratura ha il peso piu' basso (0.10) e usa una scala logaritmica con saturazione.

---

## 5. Le fonti sono incomplete e in disaccordo fra loro

- **DGIdb** aggrega decine di database a monte con criteri di inclusione diversi. Un'interazione riportata da una sola fonte puo' derivare da un singolo esperimento in vitro ad alta concentrazione.
- **La colonna `approved` di DGIdb e' inaffidabile, ed e' ora misurato.** Nel caso pilota della sclerosi tuberosa, due candidati su otto marcati `approved` non hanno alcuna etichetta FDA: uno di essi e' un inibitore mTOR rimasto sperimentale. La conferma openFDA rende visibile la discordanza, ma **non la risolve**: non filtra quei candidati, li segnala soltanto, perche' l'assenza di etichetta FDA puo' anche significare che l'approvazione e' extra-USA.
- Alcune interazioni sono palesemente rumorose. Nel caso pilota, `ASPIRIN → TSC1` compare al sesto posto: e' quasi certamente un artefatto di aggregazione, non una relazione farmacologica reale. Lo strumento lo marca `direzione non determinabile`, ma non lo esclude.
- **Orphanet** e' curato con cura ma non e' esaustivo, e colloca spesso l'associazione con il gene sui sottotipi clinici anziche' sul termine padre. Lo strumento scende nella gerarchia Mondo per compensare, ma questa discesa puo' aggregare sottotipi con geni causali diversi.
- **Reactome** annota meglio le vie di segnalazione ben studiate. Un gene poco studiato ha meno pathway, e quindi meno candidati: l'assenza di risultati riflette anche l'assenza di annotazione, non solo l'assenza di biologia.

---

## 6. Il punteggio ordina, non quantifica

Il punteggio e' una somma pesata di componenti dichiarate in `config/scoring.yaml`. I pesi sono scelte di progettazione argomentate, non stime calibrate su dati.

**Un punteggio di 0.75 non significa "75% di probabilita' di successo".** Non significa alcuna probabilita'. Significa soltanto che quel candidato precede quelli con punteggio inferiore, secondo quei pesi. Cambiare i pesi cambia l'ordine, ed e' per questo che l'impronta della configurazione compare in ogni report: due report con impronta diversa non sono confrontabili.

---

## 7. Nessun modello appreso, per scelta e per necessita'

Il progetto esclude l'addestramento di modelli. Oltre a essere un vincolo dichiarato, e' anche la scelta corretta: non esiste un training set credibile. I riposizionamenti riusciti e documentati sono poche decine, fortemente distorti verso cio' che qualcuno ha gia' avuto ragione di studiare. Un modello addestrato su quelli imparerebbe soprattutto a riconoscere la popolarita' di un farmaco.

Uno score a pesi dichiarati e' peggiore di un buon modello, che qui non e' disponibile, ed e' migliore di un cattivo modello che sembrerebbe piu' autorevole di quanto sia.

---

## 8. Limiti del layer linguistico

- Il validatore anti-allucinazione riconosce PMID, identificatori strutturati, simboli genici e nomi di farmaco. **Non** puo' verificare che un'affermazione in prosa sia una conseguenza logica corretta dei fatti forniti: puo' dire che il modello non ha citato nulla di inesistente, non che abbia ragionato bene.
- L'elenco delle espressioni vietate resta **incompleto per costruzione**. E' stato ampliato due volte, entrambe dopo aver visto un modello reale aggirarlo senza volerlo:
  - `qwen2.5:3b` ha scritto «i dati **confermano che** l'ipotesi e' coerente e affidabile». L'elenco conteneva `conferma che` e non reggeva le flessioni.
  - `qwen2.5:7b` ha scritto «il meccanismo ipotizzato per **l'efficacia** del sirolimus». L'elenco copriva `efficacia dimostrata` e `e' efficace`, ma non l'uso **nominale**, che e' la formula piu' insidiosa: non afferma l'efficacia, la presuppone.

  Entrambi i casi sono ora test di regressione, ma la lezione e' che **ogni nuovo modello puo' trovare una formula non prevista**. Il ripiego sul generatore deterministico limita il danno, non lo elimina.

- **I modelli grandi non sono immuni, sono piu' pericolosi.** Il 7B sovradichiara meno spesso del 3B, ma quando lo fa produce prosa piu' scorrevole e quindi piu' facile da assorbire senza attrito. La qualita' linguistica e l'affidabilita' epistemica non crescono insieme.
- Il generatore deterministico non ha questo problema, perche' non genera: ricopia campi strutturati.

---

## 9. Limiti di copertura

- E' caricato il subset **rare** di Mondo: le malattie non rare non sono risolvibili. E' voluto.
- Sono trattate le malattie **monogeniche**. Su una malattia poligenica il concetto stesso di "gene causale" non regge, e lo strumento non lo verifica: se Orphanet riporta piu' geni causali, li usa tutti.
- Solo dati umani. Le evidenze da organismi modello sono ignorate in fase 1.
- Nessun modello di farmacocinetica, biodisponibilita' o penetrazione della barriera ematoencefalica. Un candidato direzionalmente perfetto puo' essere del tutto inutile perche' non raggiunge il tessuto interessato. Questa dimensione e' **completamente assente** dal punteggio.

---

## 10. Il banco di prova e' una stima ottimistica

`config/benchmark.yaml` contiene 22 coppie con esito noto, e i numeri che produce vanno letti sapendo cosa li distorce:

- **Circolarita' con la letteratura.** Tutti i casi sono riposizionamenti gia' noti e gia' studiati. La componente `literature_support` premia proprio gli accostamenti gia' studiati, quindi li favorisce per costruzione. Su un accostamento che nessuno ha ancora esaminato lo strumento sara' sensibilmente peggiore, e questo il banco non lo misura ne' puo' misurarlo.
- **Misura la copertura, non la precisione.** Un candidato non atteso non e' un falso positivo: potrebbe essere un'ipotesi legittima. Non esiste modo di misurare la precisione senza validazione sperimentale, che e' fuori dallo scopo dello strumento.
- **Ventidue casi sono pochi** per distinguere un miglioramento reale dal rumore. Una differenza di uno o due casi fra due configurazioni non e' significativa.
- **Selezione dei casi.** Sono i riposizionamenti che qualcuno ha avuto ragione di studiare e che sono finiti in letteratura. I riposizionamenti falliti, e quelli mai tentati, non sono rappresentati.

Il banco serve a **confrontare due configurazioni fra loro**, non a dichiarare che lo strumento funziona.

---

## Come segnalare un limite non elencato

Apri una issue. Un limite documentato vale piu' di un limite risolto male: lo scopo di questo strumento e' aiutare un ricercatore a valutare un'ipotesi, e un ricercatore che conosce i limiti dello strumento e' in una posizione migliore di uno che si fida.
