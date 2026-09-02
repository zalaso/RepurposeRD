"""Stadio 5: grounding su letteratura reale via PubMed E-utilities.

POLITICA SUL COPYRIGHT
Si memorizzano soltanto PMID, titolo, rivista e anno, cioe' metadati
bibliografici. Non si scaricano ne' si citano testualmente abstract o full text
al di fuori del PMC Open Access subset. Nessuno scraping oltre le E-utilities,
che sono l'interfaccia che NCBI mette a disposizione proprio per questo.

COSA MISURA E COSA NON MISURA
Il conteggio degli articoli misura quanta attenzione ha ricevuto un
accostamento, non se funziona. Un accostamento molto studiato puo' esserlo
perche' e' stato ripetutamente smentito. Per questo la componente di letteratura
ha il peso piu' basso nello score, e il report riporta il conteggio come
conteggio, mai come supporto all'efficacia.
"""

from __future__ import annotations

import json
import os
import threading
from collections.abc import Iterable
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import httpx

from ..config import paths
from ..models import Article, LiteratureEvidence
from ..provenance import provenance_for
from ..ratelimit import RateLimiter, suggested_workers
from ..serialize import from_jsonable, to_jsonable

EUTILS = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
USER_AGENT = "RepurposeRD/0.1 (open-source research tool)"

# NCBI: 3 richieste al secondo senza API key, 10 con. Rispettato, non aggirato.
# Il limite e' sulla FREQUENZA, non sulla serialita': si usa per intero avendone
# qualcuna in volo insieme, con la garanzia del limitatore (vedi ratelimit.py).
_RATE_NO_KEY = 3.0
_RATE_WITH_KEY = 10.0

# Le esummary accettano fino a 200 identificativi per richiesta.
ESUMMARY_BATCH = 200


class PubMedClient:
    """Client E-utilities con cache su disco e rate limiting.

    La cache non e' un'ottimizzazione accessoria: rende un run riproducibile e
    fa si' che rieseguire la pipeline non ribatta sull'API di NCBI.
    """

    def __init__(
        self,
        cache_path: Path | None = None,
        api_key: str | None = None,
        max_workers: int | None = None,
    ) -> None:
        self.api_key = api_key or os.environ.get("NCBI_API_KEY")
        self.rate = _RATE_WITH_KEY if self.api_key else _RATE_NO_KEY
        self.limiter = RateLimiter(self.rate)
        self.max_workers = max_workers or suggested_workers(self.rate)
        self.cache_path = cache_path or (paths().processed / "pubmed_cache.json")
        self._cache: dict[str, dict] = {}
        # La cache e' letta e scritta da piu' thread: le operazioni su dict sono
        # atomiche sotto GIL, ma le sequenze leggi-modifica-scrivi no.
        self._cache_lock = threading.Lock()
        self._load_cache()

    # ---------------------------------------------------------------- cache

    def _load_cache(self) -> None:
        if self.cache_path.exists():
            try:
                with self.cache_path.open(encoding="utf-8") as fh:
                    self._cache = json.load(fh)
            except (json.JSONDecodeError, OSError):
                self._cache = {}

    def save_cache(self) -> None:
        self.cache_path.parent.mkdir(parents=True, exist_ok=True)
        with self._cache_lock:
            snapshot = dict(self._cache)
        with self.cache_path.open("w", encoding="utf-8") as fh:
            json.dump(snapshot, fh, ensure_ascii=False)

    def _cache_get(self, key: str) -> dict | None:
        with self._cache_lock:
            return self._cache.get(key)

    def _cache_put(self, key: str, value: dict) -> None:
        with self._cache_lock:
            self._cache[key] = value

    # ---------------------------------------------------------------- http

    def _get(self, endpoint: str, params: dict) -> dict:
        if self.api_key:
            params = {**params, "api_key": self.api_key}
        self.limiter.acquire()
        resp = httpx.get(
            f"{EUTILS}/{endpoint}",
            params=params,
            timeout=30.0,
            headers={"User-Agent": USER_AGENT},
        )
        resp.raise_for_status()
        return resp.json()

    # ---------------------------------------------------------------- api

    def search(self, term: str, retmax: int = 5) -> tuple[int, list[str]]:
        key = f"esearch::{retmax}::{term}"
        hit = self._cache_get(key)
        if hit is not None:
            return hit["count"], hit["pmids"]

        data = self._get(
            "esearch.fcgi",
            {
                "db": "pubmed",
                "term": term,
                "retmax": retmax,
                "retmode": "json",
                "sort": "relevance",
            },
        )
        result = data.get("esearchresult", {})
        count = int(result.get("count", 0))
        pmids = list(result.get("idlist", []))
        self._cache_put(key, {"count": count, "pmids": pmids})
        return count, pmids

    def articles_for(self, pmids: Iterable[str]) -> dict[str, Article]:
        """Metadati per un insieme qualunque di PMID, accorpando le richieste.

        DUE MIGLIORIE RISPETTO ALLA VERSIONE PRECEDENTE
        La cache era indicizzata sull'INSIEME di PMID richiesti: lo stesso
        articolo, chiesto in una combinazione diversa, veniva riscaricato. Ora
        la chiave e' il singolo PMID, e gli articoli si riusano ovunque
        ricompaiano — cosa che nei riposizionamenti accade di continuo, perche'
        gli stessi lavori tornano su piu' farmaci della stessa via.

        E le esummary accettano fino a 200 identificativi per richiesta: farne
        una ogni cinque significava sprecare il 97% della capacita' di ogni
        chiamata. Sul banco di prova questo dimezza il numero di richieste.
        """
        wanted = [p for p in dict.fromkeys(pmids) if p]
        out: dict[str, Article] = {}
        missing: list[str] = []
        for pmid in wanted:
            cached = self._cache_get(f"article::{pmid}")
            if cached is not None:
                out[pmid] = from_jsonable(Article, cached)
            else:
                missing.append(pmid)

        chunks = [missing[i : i + ESUMMARY_BATCH] for i in range(0, len(missing), ESUMMARY_BATCH)]
        for fetched in self._map(self._fetch_summaries, chunks):
            out.update(fetched)
        return out

    def _fetch_summaries(self, chunk: list[str]) -> dict[str, Article]:
        try:
            data = self._get(
                "esummary.fcgi", {"db": "pubmed", "id": ",".join(chunk), "retmode": "json"}
            )
        except (httpx.HTTPError, ValueError, KeyError):
            return {}
        result = data.get("result", {})
        found: dict[str, Article] = {}
        for pmid in result.get("uids", []):
            rec = result.get(pmid, {})
            pubdate = str(rec.get("pubdate", ""))
            article = Article(
                pmid=pmid,
                title=rec.get("title") or None,
                journal=rec.get("source") or None,
                year=int(pubdate[:4]) if pubdate[:4].isdigit() else None,
            )
            found[pmid] = article
            self._cache_put(f"article::{pmid}", to_jsonable(article))
        return found

    def _map(self, fn, items: list):
        """Esegue `fn` sugli elementi, in parallelo quando conviene.

        Con un solo elemento non si apre un pool: pagarne il costo per una
        chiamata sola sarebbe solo rumore, e i test che usano un client finto
        restano deterministici.
        """
        if not items:
            return []
        if len(items) == 1 or self.max_workers <= 1:
            return [fn(items[0])] if len(items) == 1 else [fn(i) for i in items]
        with ThreadPoolExecutor(max_workers=self.max_workers) as pool:
            return list(pool.map(fn, items))

    def summaries(self, pmids: list[str]) -> list[Article]:
        """Metadati per pochi PMID, nell'ordine richiesto."""
        found = self.articles_for(pmids)
        return [found[p] for p in pmids if p in found]


def _quote(term: str) -> str:
    return term.replace('"', "")


def _queries_for(drug_name: str, disease_label: str, causal_gene: str) -> list[tuple[str, str]]:
    """Le due interrogazioni per candidato.

    Restano deliberatamente poche e semplici. Una query elaborata darebbe
    l'impressione di una ricerca sistematica, che questa non e'.
    """
    return [
        ("drug_and_disease", f'"{_quote(drug_name)}"[tiab] AND "{_quote(disease_label)}"[tiab]'),
        ("drug_and_causal_gene", f'"{_quote(drug_name)}"[tiab] AND "{_quote(causal_gene)}"[tiab]'),
    ]


def gather(
    client: PubMedClient,
    drug_name: str,
    disease_label: str,
    causal_gene: str,
    max_articles: int = 5,
) -> list[LiteratureEvidence]:
    """Due interrogazioni per candidato: farmaco+malattia e farmaco+gene causale.

    Restano deliberatamente poche e semplici. Una query elaborata darebbe
    l'impressione di una ricerca sistematica, che questa non e'.
    """
    prov = provenance_for("pubmed")
    queries = _queries_for(drug_name, disease_label, causal_gene)

    out: list[LiteratureEvidence] = []
    for label, term in queries:
        try:
            count, pmids = client.search(term, retmax=max_articles)
            articles = client.summaries(pmids) if pmids else []
        except (httpx.HTTPError, ValueError, KeyError):
            # Un'indisponibilita' di rete non deve invalidare il resto del run:
            # si registra evidenza zero, che abbassa lo score, invece di inventarla.
            count, articles = 0, []
        out.append(
            LiteratureEvidence(
                query_label=label,
                query_string=term,
                total_count=count,
                articles=articles,
                provenance=prov,
            )
        )
    return out


def gather_many(
    client: PubMedClient,
    drug_names: list[str],
    disease_label: str,
    causal_gene: str,
    max_articles: int = 5,
) -> dict[str, list[LiteratureEvidence]]:
    """Come `gather`, ma per molti farmaci insieme.

    Le esearch restano una per interrogazione — non sono accorpabili, perche'
    ogni farmaco ha il proprio termine di ricerca. Le esummary invece si fanno
    tutte alla fine, in blocchi da duecento: e' li' che sta il guadagno.

    Sul banco di prova questo dimezza le richieste a PubMed, da quattro per
    candidato a due. Non e' solo velocita': e' trattare con misura un'API
    pubblica e gratuita di cui si fanno decine di migliaia di chiamate.
    """
    prov = provenance_for("pubmed")

    # Fase 1: tutte le esearch, in parallelo. Sono la parte irriducibile — ogni
    # farmaco ha il proprio termine e non si possono accorpare — ma nulla
    # impone di aspettarne una prima di avviare la successiva.
    tasks: list[tuple[str, str, str]] = []
    for drug in drug_names:
        for label, term in _queries_for(drug, disease_label, causal_gene):
            tasks.append((drug, label, term))

    def run(task: tuple[str, str, str]) -> tuple[str, str, str, int, list[str]]:
        drug, label, term = task
        try:
            count, pmids = client.search(term, retmax=max_articles)
        except (httpx.HTTPError, ValueError, KeyError):
            # Un'indisponibilita' di rete non deve invalidare il resto del run:
            # si registra evidenza zero, che abbassa lo score, invece di inventarla.
            count, pmids = 0, []
        return drug, label, term, count, pmids

    per_drug: dict[str, list[tuple[str, str, int, list[str]]]] = {d: [] for d in drug_names}
    needed: list[str] = []
    for drug, label, term, count, pmids in client._map(run, tasks):
        per_drug[drug].append((label, term, count, pmids))
        needed.extend(pmids)

    # Fase 2: un solo passaggio di esummary, in blocchi da duecento.
    articles = client.articles_for(needed)

    return {
        drug: [
            LiteratureEvidence(
                query_label=label,
                query_string=term,
                total_count=count,
                articles=[articles[p] for p in pmids if p in articles],
                provenance=prov,
            )
            for label, term, count, pmids in found
        ]
        for drug, found in per_drug.items()
    }
