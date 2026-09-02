"""Limitatore di frequenza per le API pubbliche.

PERCHE' ESISTE
Il client PubMed aspettava una risposta prima di inviare la richiesta
successiva. Misurato: 1,07 secondi per richiesta, cioe' lo **0,94 al secondo**
contro le 3 che NCBI consente. Il freno non era il limite imposto ma la latenza
di rete, pagata in serie.

La correzione non e' alzare il limite: e' usarlo per intero. Il vincolo di NCBI
e' «tre richieste al secondo», non «una alla volta con una pausa in mezzo».
Averne qualcuna in volo insieme, con una garanzia rigorosa sulla frequenza
complessiva, e' il modo in cui quel limite e' pensato.

COME FUNZIONA, E PERCHE' E' CORRETTO
Ogni chiamante prenota uno slot temporale. Gli slot vengono assegnati in
sequenza, distanziati esattamente di `1 / frequenza`, e chi li prenota attende
fino al proprio. Poiche' due slot distano sempre almeno un intervallo, in una
qualunque finestra di un secondo se ne possono avviare al massimo `frequenza`,
**qualunque sia il numero di thread**. La garanzia non dipende dalla
concorrenza, il che e' precisamente cio' che serve per non superare mai il
limite di un servizio altrui.
"""

from __future__ import annotations

import threading
import time


class RateLimiter:
    """Distanzia gli avvii delle richieste, in modo condiviso fra thread."""

    def __init__(self, per_second: float) -> None:
        if per_second <= 0:
            raise ValueError("la frequenza deve essere positiva")
        self.per_second = per_second
        self._interval = 1.0 / per_second
        self._lock = threading.Lock()
        self._next_slot = 0.0

    def acquire(self) -> None:
        """Attende il proprio turno. Prenotazione sotto lock, attesa fuori.

        Tenere il lock durante l'attesa serializzerebbe i chiamanti, che e'
        esattamente il difetto che questo modulo esiste per correggere.
        """
        with self._lock:
            now = time.monotonic()
            slot = max(now, self._next_slot)
            self._next_slot = slot + self._interval

        remaining = slot - time.monotonic()
        if remaining > 0:
            time.sleep(remaining)


def suggested_workers(per_second: float, expected_latency: float = 1.0, cap: int = 8) -> int:
    """Quanti thread servono per saturare la frequenza consentita.

    Con una latenza di circa un secondo e tre richieste al secondo ne servono
    almeno tre in volo. Se ne aggiunge uno di margine e si mette un tetto: oltre
    non si guadagna nulla, perche' a quel punto il collo di bottiglia e' il
    limitatore, e si aprirebbero connessioni verso un servizio altrui senza
    alcun beneficio.
    """
    needed = int(per_second * expected_latency) + 1
    return max(2, min(needed, cap))
