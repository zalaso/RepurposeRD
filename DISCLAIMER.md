# Disclaimer


*[English](DISCLAIMER.en.md) · **Italiano***

## In breve

**RepurposeRD produce ipotesi di ricerca generate al calcolatore. Non produce consigli medici.**

Nessuna delle ipotesi generate da questo strumento e' stata verificata in vitro, in vivo o clinicamente dallo strumento stesso. La presenza di un farmaco in un report **non** indica che sia efficace per la malattia considerata: indica soltanto che esiste un collegamento formale, ricostruito da basi di dati pubbliche, fra il suo bersaglio molecolare e un pathway biologico che contiene il gene causale di quella malattia.

## Cosa non e' questo strumento

- **Non e' un dispositivo medico.** Non e' certificato, registrato o valutato da alcuna autorita' regolatoria.
- **Non e' uno strumento diagnostico.** Non stabilisce, conferma o esclude alcuna diagnosi.
- **Non e' uno strumento prescrittivo.** Non fornisce indicazioni terapeutiche, posologiche o di somministrazione, e il generatore di testo e' esplicitamente vincolato a non produrne.
- **Non e' una revisione sistematica della letteratura.** I conteggi PubMed riportati misurano quanti articoli corrispondono a un'interrogazione, non cosa quegli articoli concludano.

## Per chi e' pensato

Per ricercatori qualificati in ambito biomedico, che usino ogni ipotesi come punto di partenza da verificare risalendo alle fonti citate, e non come conclusione.

## Se sei un paziente o un familiare

Comprendiamo perche' uno strumento come questo possa attirare chi convive con una malattia rara, soprattutto quando le opzioni terapeutiche disponibili sono poche o nessuna.

**Non usare questo strumento per prendere decisioni sulla tua salute o su quella di una persona che assisti.** Un farmaco che compare in un report puo' essere inefficace per la malattia in questione, e puo' essere dannoso: assumere un farmaco approvato per un'altra indicazione, senza controllo medico, comporta rischi reali e talvolta gravi.

Se vuoi approfondire una possibilita' terapeutica, parlane con il medico che ti segue o con un centro di riferimento per le malattie rare. Sono le persone che possono valutare il tuo caso specifico.

## Sui limiti scientifici del metodo

La logica di questo strumento e' che due geni appartenenti allo stesso pathway biologico sono funzionalmente vicini, e che un farmaco che agisce su uno potrebbe influenzare il processo alterato dall'altro. E' un'euristica ragionevole ed e' anche il modo in cui alcuni riposizionamenti reali sono stati individuati, ma resta un'euristica:

- **La co-appartenenza a un pathway non e' un meccanismo.** E' un indizio di prossimita' funzionale, non una catena causale dimostrata.
- **La direzione dell'effetto e' spesso ignota.** Sapere che un farmaco tocca il pathway giusto non dice se lo spinga nella direzione utile o in quella dannosa. Quando il report riporta `non determinabile`, sta dicendo esattamente questo, e non e' un'informazione rassicurante.
- **Le fonti sono incomplete e non concordi.** Le interazioni farmaco-gene provengono da database che aggregano fonti eterogenee, con criteri di inclusione diversi e livelli di curazione diversi.
- **Il punteggio ordina, non quantifica.** Non e' la stima di una probabilita' di successo. Un punteggio di 0.75 non significa "75% di probabilita'": significa soltanto che quel candidato precede quelli con punteggio inferiore secondo i pesi dichiarati in `config/scoring.yaml`.

L'elenco esteso e' in [docs/LIMITATIONS.md](docs/LIMITATIONS.md).

## Nessuna garanzia

Il software e' distribuito sotto licenza Apache-2.0, senza garanzie di alcun tipo, esplicite o implicite, come specificato nella sezione 7 della licenza. Gli autori e i contributori non rispondono di alcun danno derivante dall'uso di questo software o dei suoi risultati.

## Segnalazioni

Se trovi un output che afferma o suggerisce efficacia clinica, apri una issue con il testo esatto. Un output di quel tipo e' un difetto del software, non una sfumatura accettabile, e viene trattato con la stessa priorita' di un bug di sicurezza.
