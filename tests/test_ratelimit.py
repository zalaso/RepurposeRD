"""Test del limitatore di frequenza.

La proprieta' verificata qui non e' un dettaglio prestazionale: e' una promessa
fatta a un servizio pubblico altrui. NCBI concede tre richieste al secondo, e
questo codice ne manda parecchie in parallelo. Se il limitatore sbagliasse,
supereremmo il limite di un'API gratuita mentre il commento nel sorgente
dichiara di rispettarlo.

I test misurano tempi reali e sono quindi tolleranti: si verifica che il limite
non venga **superato**, non che sia raggiunto al millisecondo.
"""

from __future__ import annotations

import itertools
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import pytest

from repurposerd.ratelimit import RateLimiter, suggested_workers


class TestGaranziaDiFrequenza:
    def test_le_partenze_sono_distanziate_nel_complesso(self):
        """La garanzia e' cumulativa, non intervallo per intervallo.

        PERCHE' NON SI CONTROLLA IL SINGOLO INTERVALLO
        Su Windows `time.sleep` ha una granularita' di circa 15,6 ms: le attese
        si quantizzano su multipli di quel valore, e un intervallo da 50 ms
        rimbalza fra 31 e 63 ms. Una versione precedente di questo test
        controllava ogni singolo intervallo e falliva in CI in modo
        intermittente — su intervalli osservati [0.047, 0.063, 0.031, 0.062,
        0.047] che pero' **sommavano esattamente il minimo teorico**.

        Il limitatore era corretto; era il test a misurare la cosa sbagliata.
        Il tempo totale e' immune al jitter del sistema operativo perche' ogni
        slot avanza `_next_slot` di un intervallo pieno a prescindere da quando
        il thread si risvegli davvero.
        """
        rate = 20
        n = 6
        limiter = RateLimiter(per_second=rate)

        inizio = time.monotonic()
        for _ in range(n):
            limiter.acquire()
        durata = time.monotonic() - inizio

        minimo_teorico = (n - 1) / rate
        assert durata >= minimo_teorico * 0.95, f"{durata:.3f}s per {n} partenze"

    def test_nessun_intervallo_collassa_a_zero(self):
        """Il controllo debole che resta sensato sul singolo intervallo.

        Non verifica la spaziatura esatta — quella dipende dal sistema
        operativo — ma che il limitatore stia effettivamente attendendo invece
        di lasciar passare tutto insieme.
        """
        limiter = RateLimiter(per_second=20)
        istanti = []
        for _ in range(6):
            limiter.acquire()
            istanti.append(time.monotonic())
        intervalli = [b - a for a, b in itertools.pairwise(istanti)]
        assert all(i > 0.005 for i in intervalli), intervalli

    def test_il_limite_regge_con_piu_thread(self):
        """La garanzia deve valere a prescindere dalla concorrenza.

        E' il punto dell'intero modulo: se dipendesse dal numero di thread,
        aumentare i lavoratori significherebbe superare il limite.
        """
        limiter = RateLimiter(per_second=20)
        istanti: list[float] = []
        lock = threading.Lock()

        def lavora(_):
            limiter.acquire()
            with lock:
                istanti.append(time.monotonic())

        with ThreadPoolExecutor(max_workers=8) as pool:
            list(pool.map(lavora, range(24)))

        istanti.sort()
        durata = istanti[-1] - istanti[0]
        # 24 partenze a 20/s non possono stare in meno di ~1.15 s.
        minimo_teorico = (len(istanti) - 1) / 20
        assert durata >= minimo_teorico * 0.9, f"{durata:.3f}s per {len(istanti)} partenze"

    def test_nessuna_finestra_di_un_secondo_supera_la_frequenza(self):
        """Il controllo piu' diretto: contare le partenze in ogni finestra."""
        rate = 20
        limiter = RateLimiter(per_second=rate)
        istanti: list[float] = []
        lock = threading.Lock()

        def lavora(_):
            limiter.acquire()
            with lock:
                istanti.append(time.monotonic())

        with ThreadPoolExecutor(max_workers=6) as pool:
            list(pool.map(lavora, range(40)))

        istanti.sort()
        for i, inizio in enumerate(istanti):
            dentro = sum(1 for t in istanti[i:] if t < inizio + 1.0)
            assert dentro <= rate + 1, f"{dentro} partenze in un secondo, limite {rate}"

    def test_la_concorrenza_serve_a_qualcosa(self):
        """Se l'attesa avvenisse sotto lock, i thread si serializzerebbero e il
        modulo non avrebbe motivo di esistere. Qui si verifica che non accada."""
        limiter = RateLimiter(per_second=100)

        def lavora(_):
            limiter.acquire()
            time.sleep(0.05)  # simula la latenza di rete

        inizio = time.monotonic()
        with ThreadPoolExecutor(max_workers=5) as pool:
            list(pool.map(lavora, range(10)))
        durata = time.monotonic() - inizio

        # In serie sarebbero 10 x 0.05 = 0.5 s. Con cinque in volo, molto meno.
        assert durata < 0.35, f"{durata:.3f}s: le richieste non si sovrappongono"


class TestParametri:
    def test_frequenza_non_positiva_e_un_errore(self):
        for valore in (0, -1):
            with pytest.raises(ValueError):
                RateLimiter(per_second=valore)

    def test_lavoratori_sufficienti_a_saturare(self):
        # Con 3 richieste/s e ~1 s di latenza servono almeno 3 in volo.
        assert suggested_workers(3.0, expected_latency=1.0) >= 3

    def test_i_lavoratori_hanno_un_tetto(self):
        """Oltre il tetto il collo di bottiglia e' il limitatore: aprire altre
        connessioni verso un servizio altrui non darebbe alcun beneficio."""
        assert suggested_workers(1000.0) <= 8

    def test_almeno_due_lavoratori(self):
        assert suggested_workers(0.5) >= 2
