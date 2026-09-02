"""Conferma regolatoria indipendente tramite openFDA.

A COSA SERVE
DGIdb porta una colonna `approved`, ma e' un aggregato di fonti a monte con
criteri diversi, e non dice **per che cosa** un farmaco sia approvato. openFDA
espone le etichette FDA reali: dice se il farmaco ha un'etichetta negli Stati
Uniti e quali indicazioni vi compaiono.

Il valore per il lettore non e' la conferma in se'. E' che vedere le indicazioni
etichettate accanto a un'ipotesi di riposizionamento rende **evidente che
l'ipotesi e' fuori indicazione**. Un report che dice «approvato per la profilassi
del rigetto nel trapianto renale» e poi propone una malattia diversa dice al
revisore, senza doverlo spiegare, di che tipo di salto si stia parlando.

PERCHE' NON ENTRA NEL PUNTEGGIO
openFDA copre gli Stati Uniti. Usarla come componente di score penalizzerebbe i
farmaci approvati solo altrove, che nelle malattie rare sono molti: miglustat e'
autorizzato da EMA per Niemann-Pick tipo C, indicazione che l'FDA non ha mai
concesso. Un candidato non e' piu' debole perche' e' stato approvato a Bruxelles
anziche' a Silver Spring, e codificare quella distinzione in un punteggio
scientifico significherebbe inserire una distorsione geografica in un dato che
non ne ha.

Resta quindi **informativa**, mostrata nel report e assente dallo score. Il
report dichiara esplicitamente che l'assenza di etichetta FDA non significa
"non approvato".

LICENZA
Le etichette FDA sono opere del governo statunitense, di pubblico dominio.
Termini: https://open.fda.gov/license/
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

import httpx

from ..config import paths
from ..models import Provenance, RegulatoryLabel
from ..provenance import provenance_for
from ..serialize import from_jsonable, to_jsonable

API = "https://api.fda.gov/drug/label.json"
USER_AGENT = "RepurposeRD/0.1 (open-source research tool)"

# openFDA consente 240 richieste al minuto per IP senza chiave, 1000 con chiave.
# Si resta ampiamente sotto: non c'e' nulla da guadagnare ad avvicinarsi al limite.
_RATE_NO_KEY = 1 / 3
_RATE_WITH_KEY = 1 / 10

# Le indicazioni sono di pubblico dominio, ma l'etichetta intera puo' superare i
# 50.000 caratteri. Se ne conserva un estratto: serve a far capire per cosa il
# farmaco sia etichettato, non a riprodurre il foglietto illustrativo.
MAX_INDICATION_CHARS = 400


class OpenFDAClient:
    """Client openFDA con cache su disco e rate limiting.

    La cache, come per PubMed, non e' un'ottimizzazione accessoria: rende
    riproducibile un run e evita di ribattere su un'API pubblica gratuita a ogni
    riesecuzione sulla stessa malattia.
    """

    def __init__(self, cache_path: Path | None = None, api_key: str | None = None) -> None:
        self.api_key = api_key or os.environ.get("OPENFDA_API_KEY")
        self.delay = _RATE_WITH_KEY if self.api_key else _RATE_NO_KEY
        self.cache_path = cache_path or (paths().processed / "openfda_cache.json")
        self._cache: dict[str, dict] = {}
        self._last_call = 0.0
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
        with self.cache_path.open("w", encoding="utf-8") as fh:
            json.dump(self._cache, fh, ensure_ascii=False)

    # ---------------------------------------------------------------- http

    def _throttle(self) -> None:
        elapsed = time.monotonic() - self._last_call
        if elapsed < self.delay:
            time.sleep(self.delay - elapsed)
        self._last_call = time.monotonic()

    def _query(self, field: str, drug_name: str) -> dict | None:
        """Una interrogazione su un singolo campo. None se non trova nulla.

        openFDA risponde 404 quando la ricerca non produce risultati: e' un esito
        normale, non un errore, e va distinto da un guasto di rete.
        """
        params = {"search": f'{field}:"{drug_name}"', "limit": 1}
        if self.api_key:
            params["api_key"] = self.api_key

        self._throttle()
        try:
            resp = httpx.get(API, params=params, timeout=30.0, headers={"User-Agent": USER_AGENT})
        except httpx.HTTPError:
            return None

        if resp.status_code == 404:
            return None
        if resp.status_code != 200:
            return None
        try:
            data = resp.json()
        except ValueError:
            return None

        results = data.get("results") or []
        if not results:
            return None
        return {"result": results[0], "total": data.get("meta", {}).get("results", {}).get("total")}

    # ---------------------------------------------------------------- api

    def label_for(self, drug_name: str) -> RegulatoryLabel:
        """Etichetta FDA per un farmaco, se esiste.

        Si prova prima il nome generico e poi quello commerciale: DGIdb usa
        prevalentemente denominazioni comuni, ma non sempre.
        """
        key = f"label::{drug_name.lower()}"
        if key in self._cache:
            return from_jsonable(RegulatoryLabel, self._cache[key])

        prov = provenance_for("openfda")
        hit = None
        for field in ("openfda.generic_name", "openfda.brand_name"):
            hit = self._query(field, drug_name.lower())
            if hit:
                break

        label = _to_label(drug_name, hit, prov)
        self._cache[key] = to_jsonable(label)
        return label


def _first_list(record: dict, key: str, limit: int = 3) -> list[str]:
    value = record.get(key)
    if isinstance(value, list):
        return [str(v) for v in value[:limit]]
    return []


def _to_label(drug_name: str, hit: dict | None, prov: Provenance) -> RegulatoryLabel:
    if not hit:
        return RegulatoryLabel(
            drug_name=drug_name,
            label_found=False,
            provenance=prov,
        )

    result = hit["result"]
    openfda = result.get("openfda") or {}

    indications = ""
    raw = result.get("indications_and_usage")
    if isinstance(raw, list) and raw:
        indications = " ".join(str(raw[0]).split())
        if len(indications) > MAX_INDICATION_CHARS:
            indications = indications[:MAX_INDICATION_CHARS].rstrip() + "..."

    return RegulatoryLabel(
        drug_name=drug_name,
        label_found=True,
        generic_names=_first_list(openfda, "generic_name"),
        brand_names=_first_list(openfda, "brand_name"),
        routes=_first_list(openfda, "route"),
        application_numbers=_first_list(openfda, "application_number"),
        labeled_indications=indications or None,
        matching_labels=hit.get("total"),
        provenance=prov,
    )
