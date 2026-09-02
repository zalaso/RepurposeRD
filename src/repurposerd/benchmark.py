"""Esecuzione del banco di prova e misura della copertura.

A COSA SERVE
A rendere confrontabili due configurazioni. Finora ogni scelta sui pesi dello
scoring era argomentata ma non validata: con due soli casi pilota non si poteva
dire se una modifica migliorasse o peggiorasse. Questo modulo produce numeri
che si possono confrontare fra un'impronta di configurazione e l'altra.

COSA MISURA, E COSA NO
Misura se il farmaco atteso compare fra i candidati e in che posizione. Non
misura se le ipotesi generate siano buone: un candidato non atteso non e' un
falso positivo, potrebbe essere un'ipotesi legittima che nessuno ha ancora
studiato. Il banco misura la **copertura**, non la precisione, e sarebbe un
errore leggerlo come se misurasse la seconda.

I `structural_miss` non vanno trovati: contarli come successi premierebbe uno
strumento reso promiscuo, che alza la copertura restituendo tutto.
"""

from __future__ import annotations

import re
import statistics
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

import duckdb
import yaml

from .config import config_digest, paths
from .pipeline.bundle import build_bundle
from .pipeline.resolve import AmbiguousDisease, DiseaseNotFound

# Suffissi salini e formulativi con cui DGIdb denomina i farmaci. Senza questa
# normalizzazione il banco direbbe "non trovato" per LOSARTAN quando in tabella
# c'e' LOSARTAN POTASSIUM, misurando la denominazione invece del metodo.
SALT_TOKENS = {
    "acetate",
    "besylate",
    "bromide",
    "calcium",
    "chloride",
    "citrate",
    "dihydrate",
    "dipotassium",
    "disodium",
    "fumarate",
    "hydrobromide",
    "hydrochloride",
    "lactate",
    "magnesium",
    "malate",
    "maleate",
    "mesylate",
    "micronized",
    "monohydrate",
    "nitrate",
    "oxalate",
    "phosphate",
    "potassium",
    "sodium",
    "succinate",
    "sulfate",
    "tartrate",
    "tosylate",
    "hcl",
}

_NON_WORD = re.compile(r"[^a-z0-9\s]+")


def normalize_drug(name: str) -> str:
    """Nome del farmaco senza sale ne' punteggiatura, per il confronto."""
    cleaned = _NON_WORD.sub(" ", name.lower())
    tokens = [t for t in cleaned.split() if t and t not in SALT_TOKENS]
    return " ".join(tokens)


def drug_matches(expected: str, candidate: str) -> bool:
    """Vero se il candidato e' il farmaco atteso, tollerando le forme saline.

    Il confronto e' sull'intera sequenza di parole normalizzate: `asfotase alfa`
    non deve corrispondere a un farmaco che contenga solo `alfa`.
    """
    exp = normalize_drug(expected)
    cand = normalize_drug(candidate)
    if not exp or not cand:
        return False
    if exp == cand:
        return True
    exp_tokens = exp.split()
    cand_tokens = cand.split()
    n = len(exp_tokens)
    return any(cand_tokens[i : i + n] == exp_tokens for i in range(len(cand_tokens) - n + 1))


@dataclass(kw_only=True)
class CaseResult:
    case_id: str
    disease: str
    expected_drug: str
    kind: str
    found: bool = False
    rank: int | None = None
    total_candidates: int = 0
    score: float | None = None
    tier: str | None = None
    via_bridge: bool = False
    matched_name: str | None = None
    target_gene: str | None = None
    shortlist_truncated: bool = False
    error: str | None = None

    @property
    def succeeded(self) -> bool:
        """Un `structural_miss` ha successo proprio non venendo trovato."""
        if self.error:
            return False
        if self.kind == "structural_miss":
            return not self.found
        return self.found


@dataclass(kw_only=True)
class BenchmarkReport:
    results: list[CaseResult] = field(default_factory=list)
    config_digest: str = ""
    top_n: int = 0
    with_literature: bool = True
    with_phenotype_bridge: bool = True
    generated_at: datetime = field(default_factory=datetime.now)

    def _of_kind(self, *kinds: str) -> list[CaseResult]:
        return [r for r in self.results if r.kind in kinds]

    def recall_at(self, k: int, *kinds: str) -> tuple[int, int]:
        """Quanti casi trovati entro la posizione k, sul totale del gruppo."""
        group = self._of_kind(*kinds) if kinds else self._of_kind("repurposing", "on_label")
        hit = sum(1 for r in group if r.found and r.rank is not None and r.rank <= k)
        return hit, len(group)

    def median_rank(self, *kinds: str) -> float | None:
        group = self._of_kind(*kinds) if kinds else self._of_kind("repurposing", "on_label")
        ranks = [r.rank for r in group if r.rank is not None]
        return statistics.median(ranks) if ranks else None

    def errors(self) -> list[CaseResult]:
        return [r for r in self.results if r.error]

    def truncated(self) -> list[CaseResult]:
        """Casi in cui il tetto sulla preselezione ha tagliato.

        Un farmaco atteso assente in uno di questi casi puo' non essere
        stato interrogato affatto: e' un limite di costo, non un fallimento
        del metodo, e leggerlo come tale sottostimerebbe lo strumento.
        """
        return [r for r in self.results if r.shortlist_truncated]


def load_cases() -> list[dict[str, Any]]:
    path = paths().config / "benchmark.yaml"
    if not path.exists():
        raise FileNotFoundError(f"Banco di prova mancante: {path}")
    with path.open(encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}
    return list(data.get("cases") or [])


def run_case(
    con: duckdb.DuckDBPyConnection,
    case: dict[str, Any],
    top_n: int,
    with_literature: bool,
    use_phenotype_bridge: bool,
    with_regulatory: bool,
) -> CaseResult:
    result = CaseResult(
        case_id=case["id"],
        disease=case["disease"],
        expected_drug=case["expected_drug"],
        kind=case.get("kind", "repurposing"),
    )
    try:
        bundle = build_bundle(
            con,
            case["disease"],
            top_n=top_n,
            with_literature=with_literature,
            use_phenotype_bridge=use_phenotype_bridge,
            with_regulatory=with_regulatory,
        )
    except (DiseaseNotFound, AmbiguousDisease, ValueError) as exc:
        result.error = str(exc).split("\n")[0][:160]
        return result

    result.total_candidates = len(bundle.candidates)
    result.shortlist_truncated = bundle.literature_shortlist_truncated
    for rank, cand in enumerate(bundle.candidates, 1):
        if drug_matches(case["expected_drug"], cand.drug_name):
            result.found = True
            result.rank = rank
            result.score = cand.score.total
            result.tier = cand.tier
            result.via_bridge = cand.pathway_link.bridge is not None
            result.matched_name = cand.drug_name
            result.target_gene = cand.target_gene
            break
    return result


def run_benchmark(
    con: duckdb.DuckDBPyConnection,
    top_n: int = 40,
    with_literature: bool = True,
    use_phenotype_bridge: bool = True,
    with_regulatory: bool = False,
    only: list[str] | None = None,
    progress: Any = None,
) -> BenchmarkReport:
    """Esegue tutti i casi e raccoglie gli esiti.

    `with_regulatory` e' disattivato per impostazione predefinita: la conferma
    FDA non entra nel punteggio e quindi non cambia il ranking, mentre aggiunge
    una richiesta di rete per candidato finale di ogni caso.
    """
    cases = load_cases()
    if only:
        cases = [c for c in cases if c["id"] in only]

    report = BenchmarkReport(
        config_digest=config_digest(),
        top_n=top_n,
        with_literature=with_literature,
        with_phenotype_bridge=use_phenotype_bridge,
    )
    for i, case in enumerate(cases, 1):
        if progress:
            progress(i, len(cases), case)
        report.results.append(
            run_case(con, case, top_n, with_literature, use_phenotype_bridge, with_regulatory)
        )
    return report
