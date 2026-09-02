"""Stadio 6: score deterministico e scomposto.

Nessun modello appreso, per due ragioni. La prima e' un vincolo del progetto.
La seconda e' che non esiste un training set credibile: i riposizionamenti
riusciti noti sono poche decine, fortemente distorti verso cio' che qualcuno ha
gia' avuto ragione di studiare, e un modello addestrato su quelli imparerebbe
soprattutto a riconoscere la popolarita'.

Uno score a pesi dichiarati e' peggiore di un buon modello che qui non possiamo
avere, ed e' meglio di un cattivo modello che sembrerebbe migliore di quanto sia.
Ogni componente e' visibile nel report, cosi' un revisore puo' non essere
d'accordo con il numero e vedere esattamente da dove viene.
"""

from __future__ import annotations

import math

from ..config import scoring_config
from ..models import (
    DirectionAssessment,
    DrugInteraction,
    LiteratureEvidence,
    PathwayLink,
    ScoreBreakdown,
)


def _component_pathway_proximity(link: PathwayLink) -> float:
    by_hop = scoring_config()["components"]["pathway_proximity"]["by_hop"]
    return float(by_hop.get(link.hops, by_hop.get(str(link.hops), 0.0)))


def _component_pathway_specificity(link: PathwayLink) -> float:
    """Un pathway piccolo e' molto piu' informativo di uno grande.

    Che due geni compaiano entrambi in un pathway da 8 geni dice qualcosa; che
    compaiano entrambi in uno da 800 non dice quasi nulla. La scala e'
    logaritmica perche' la differenza fra 5 e 50 geni conta molto piu' della
    differenza fra 150 e 195.
    """
    max_size = scoring_config()["filters"]["max_pathway_size"]
    size = max(link.pathway.size, 1)
    if size <= 1:
        return 1.0
    if size >= max_size:
        return 0.0
    return max(0.0, min(1.0, 1.0 - math.log(size) / math.log(max_size)))


def _component_direction(direction: DirectionAssessment) -> float:
    cfg = scoring_config()["components"]["direction_coherence"]
    return float(cfg.get(direction.verdict, 0.0))


def _component_interaction_support(interaction: DrugInteraction) -> float:
    """Numero di database a monte distinti che riportano l'interazione."""
    saturation = scoring_config()["components"]["interaction_support"]["saturation_at"]
    n = len(interaction.source_dbs)
    return min(1.0, n / saturation) if saturation else 0.0


def _component_literature(literature: list[LiteratureEvidence]) -> float:
    """Solo conteggio di articoli reali. Nessuna interpretazione del contenuto.

    La numerosita' misura quanta attenzione ha ricevuto un accostamento, non se
    funziona: un accostamento molto studiato puo' esserlo perche' e' stato
    ripetutamente smentito. Per questo il peso di questa componente e' il piu'
    basso di tutti.
    """
    saturation = scoring_config()["components"]["literature_support"]["saturation_at"]
    if not saturation:
        return 0.0
    total = sum(lit.total_count for lit in literature)
    return min(1.0, math.log1p(total) / math.log1p(saturation))


def _component_route_directness(link: PathwayLink) -> float:
    """Quanto e' diretto il percorso dalla malattia al candidato.

    Un candidato ancorato al gene causale della malattia interrogata vale 1.0.
    Uno arrivato da una malattia fenotipicamente simile vale la somiglianza
    stessa, che tipicamente sta fra 0.15 e 0.35: la penalita' e' quindi
    sostanziale, ed e' voluta. La somiglianza clinica suggerisce biologia
    condivisa a valle, non parentela meccanicistica, e il punteggio deve
    riflettere questa differenza invece di appiattirla.
    """
    cfg = scoring_config()["components"].get("route_directness", {})
    if link.bridge is None:
        return float(cfg.get("direct", 1.0))
    return max(0.0, min(1.0, float(link.bridge.similarity)))


def score_candidate(
    link: PathwayLink,
    interaction: DrugInteraction,
    direction: DirectionAssessment,
    literature: list[LiteratureEvidence],
) -> ScoreBreakdown:
    weights = dict(scoring_config()["weights"])
    components = {
        "pathway_proximity": _component_pathway_proximity(link),
        "pathway_specificity": _component_pathway_specificity(link),
        "direction_coherence": _component_direction(direction),
        "interaction_support": _component_interaction_support(interaction),
        "literature_support": _component_literature(literature),
        "route_directness": _component_route_directness(link),
    }
    total = sum(components[k] * weights.get(k, 0.0) for k in components)
    return ScoreBreakdown(
        components={k: round(v, 4) for k, v in components.items()},
        weights={k: float(v) for k, v in weights.items()},
        total=round(total, 4),
    )


def tier_for(score: float, direction_verdict: str | None = None) -> tuple[str, bool]:
    """Traduce lo score in un livello di evidenza dichiarato.

    Non esiste un tier "forte". Nessuna combinazione di evidenza puramente
    computazionale lo giustifica, e il vocabolario del report non deve offrire
    una parola che un lettore frettoloso possa leggere come efficacia.

    TETTO SENZA DIREZIONE
    Se `direction_verdict` non e' "coherent", il livello e' limitato dal valore
    di `max_tier_without_direction`. Non e' una taratura di soglia ma una
    regola: non si puo' definire "moderata" un'evidenza di cui non si sa se il
    farmaco correggerebbe o aggraverebbe il difetto. Nel caso pilota della
    sclerosi tuberosa questo tetto e' cio' che tiene ASPIRIN -> TSC1, un
    artefatto di aggregazione con punteggio alto e direzione ignota, fuori
    dallo stesso livello dei candidati verificati.
    """
    cfg = scoring_config()
    tiers = cfg["tiers"]

    chosen = tiers[-1]
    for tier in tiers:
        if score >= tier["min_score"]:
            chosen = tier
            break

    cap_name = cfg.get("max_tier_without_direction")
    if cap_name and direction_verdict is not None and direction_verdict != "coherent":
        names = [t["name"] for t in tiers]
        if cap_name in names and names.index(chosen["name"]) < names.index(cap_name):
            chosen = tiers[names.index(cap_name)]

    return chosen["name"], bool(chosen["weak_evidence_flag"])
