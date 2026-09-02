"""Stadio 4: coerenza direzionale fra azione del farmaco e difetto della malattia.

E' il punto in cui i metodi naive di sovrapposizione fra pathway sbagliano.
"Farmaco e malattia condividono un pathway" e' un'affermazione senza direzione:
se la malattia nasce dalla perdita di funzione di un gene e il farmaco inibisce
un gene a valle nello stesso pathway, l'effetto atteso puo' essere peggiorativo,
non terapeutico. Un ranking che non distingue i due casi mette il candidato
dannoso accanto a quello sensato e lascia al lettore il compito di accorgersene.

LA REGOLA
Si propaga il segno dal gene causale al bersaglio del farmaco, ottenendo lo
stato ATTESO del bersaglio nella malattia. Un farmaco e' coerente se la sua
azione si oppone a quello stato:

    LoF + arco negativo -> bersaglio iperattivo -> serve un inibitore
    LoF + arco positivo -> bersaglio ipoattivo  -> serve un attivatore
    GoF + arco negativo -> bersaglio ipoattivo  -> serve un attivatore
    GoF + arco positivo -> bersaglio iperattivo -> serve un inibitore

Il caso hop 0 (il farmaco agisce sul gene causale stesso) rientra nella stessa
regola trattando l'identita' come un arco positivo su se' stessi.

ONESTA' DEL DEFAULT
Cio' che non e' curato in config/mechanism.yaml vale `unknown`, e `unknown`
abbassa il punteggio. Non sapere la direzione e' un difetto dell'evidenza, non
un'assenza di problema, e il punteggio deve rifletterlo.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..config import mechanism_config
from ..models import DirectionAssessment, DiseaseMechanism, DrugAction, TargetState


@dataclass(frozen=True)
class MechanismCall:
    """Meccanismo attribuito a una malattia, con l'indicazione di chi lo dice.

    `origin` non e' decorativo: un'annotazione curata a mano con motivazione e
    PMID e una derivata da Orphanet hanno autorita' diverse, e il lettore del
    report deve poterle distinguere invece di vedere entrambe come "il
    meccanismo".
    """

    mechanism: DiseaseMechanism
    rationale: str | None = None
    sources: list[str] = field(default_factory=list)
    origin: str = "ignoto"  # curato | orphanet | ignoto


def _curated_mechanism(mondo_id: str) -> MechanismCall | None:
    entry = (mechanism_config().get("disease_mechanism") or {}).get(mondo_id)
    if not entry:
        return None
    try:
        mech = DiseaseMechanism(entry.get("mechanism", "unknown"))
    except ValueError:
        return None
    if mech is DiseaseMechanism.UNKNOWN:
        return None
    return MechanismCall(
        mechanism=mech,
        rationale=entry.get("rationale"),
        sources=list(entry.get("sources") or []),
        origin="curato",
    )


def orphanet_mechanism(con, orpha_codes: list[str]) -> MechanismCall | None:
    """Meccanismo dichiarato da Orphanet nel tipo di associazione gene-malattia.

    PERCHE' ESISTE
    Orphanet distingue esplicitamente `Disease-causing germline mutation(s)
    (loss of function) in` da `(gain of function) in`. E' la stessa
    informazione che `config/mechanism.yaml` conteneva a mano per due malattie,
    gia' presente sul disco per **oltre mille**, curata da Orphanet e sotto
    licenza CC BY 4.0.

    Non sostituisce la curazione a mano: quella ha la precedenza, perche' porta
    una motivazione leggibile e fonti scelte. Copre pero' il caso di gran lunga
    piu' frequente, cioe' la malattia che nessuno ha ancora annotato.

    CONFLITTI
    Se i geni causali di una stessa malattia portano annotazioni opposte, il
    risultato e' `None`, non una scelta a maggioranza. Un disaccordo fra le
    fonti non si risolve votando: si dichiara, e la direzione resta ignota.
    """
    if not orpha_codes:
        return None

    placeholders = ", ".join(["?"] * len(orpha_codes))
    rows = con.execute(
        f"""
        SELECT DISTINCT association_type, gene_symbol
        FROM orphanet_gene_assoc
        WHERE orpha_code IN ({placeholders}) AND is_causal
          AND association_type LIKE '%function)%'
        """,
        orpha_codes,
    ).fetchall()
    if not rows:
        return None

    trovati = set()
    geni = []
    for tipo, gene in rows:
        low = tipo.lower()
        if "loss of function" in low:
            trovati.add(DiseaseMechanism.LOSS_OF_FUNCTION)
        elif "gain of function" in low:
            trovati.add(DiseaseMechanism.GAIN_OF_FUNCTION)
        geni.append(gene)

    if len(trovati) != 1:
        return None

    mech = next(iter(trovati))
    verso = "perdita" if mech is DiseaseMechanism.LOSS_OF_FUNCTION else "guadagno"
    return MechanismCall(
        mechanism=mech,
        rationale=(
            f"Orphanet classifica l'associazione con {', '.join(sorted(set(geni)))} come "
            f"mutazione germinale causa-malattia con {verso} di funzione. E' "
            "un'annotazione della fonte, non una valutazione di questo strumento."
        ),
        sources=sorted({f"ORPHA:{c.split(':')[-1]}" for c in orpha_codes}),
        origin="orphanet",
    )


def resolve_mechanism(
    mondo_id: str, con=None, orpha_codes: list[str] | None = None
) -> MechanismCall:
    """Meccanismo della malattia: prima la curazione a mano, poi Orphanet.

    L'ordine non e' arbitrario. Una voce di `config/mechanism.yaml` porta una
    motivazione scritta e fonti scelte da chi l'ha inserita, e per le due
    malattie che ne dispongono e' piu' informativa. Orphanet copre il resto.
    """
    curato = _curated_mechanism(mondo_id)
    if curato:
        return curato
    if con is not None and orpha_codes:
        derivato = orphanet_mechanism(con, orpha_codes)
        if derivato:
            return derivato
    return MechanismCall(mechanism=DiseaseMechanism.UNKNOWN)


def disease_mechanism(mondo_id: str) -> tuple[DiseaseMechanism, str | None, list[str]]:
    """Solo la curazione a mano. Mantenuta per i chiamanti che non hanno lo store."""
    call = _curated_mechanism(mondo_id) or MechanismCall(mechanism=DiseaseMechanism.UNKNOWN)
    return call.mechanism, call.rationale, call.sources


def classify_drug_action(interaction_types: list[str]) -> DrugAction:
    """Traduce i tipi di interazione DGIdb in azione farmacologica.

    Se i tipi riportati si contraddicono fra loro (una fonte dice inibitore, una
    altra agonista) l'esito e' `ambiguous`: il disaccordo fra le fonti e' esso
    stesso un'informazione, e appiattirlo su una delle due sarebbe arbitrario.
    """
    sem = mechanism_config().get("interaction_semantics", {})
    inhibiting = {s.lower() for s in sem.get("inhibiting", [])}
    activating = {s.lower() for s in sem.get("activating", [])}

    found: set[DrugAction] = set()
    for t in interaction_types:
        t = (t or "").strip().lower()
        if not t:
            continue
        if t in inhibiting:
            found.add("inhibiting")
        elif t in activating:
            found.add("activating")

    if len(found) == 1:
        return next(iter(found))
    return "ambiguous"


def _edge_sign(causal_gene: str, target_gene: str) -> tuple[str | None, str | None, list[str]]:
    """Segno dell'arco regolatorio dal gene causale al bersaglio.

    Ritorna (sign, via, sources). L'identita' e' un arco positivo su se' stessi.
    """
    if causal_gene.upper() == target_gene.upper():
        return "positive", "il farmaco agisce direttamente sul prodotto del gene causale", []

    for edge in mechanism_config().get("signed_edges") or []:
        if (
            str(edge.get("source", "")).upper() == causal_gene.upper()
            and str(edge.get("target", "")).upper() == target_gene.upper()
        ):
            return edge.get("sign"), edge.get("via"), list(edge.get("sources") or [])
    return None, None, []


def _expected_state(mechanism: DiseaseMechanism, sign: str) -> TargetState:
    if mechanism is DiseaseMechanism.LOSS_OF_FUNCTION:
        return "hyperactive" if sign == "negative" else "hypoactive"
    if mechanism is DiseaseMechanism.GAIN_OF_FUNCTION:
        return "hypoactive" if sign == "negative" else "hyperactive"
    return "unknown"


_OPPOSES: dict[TargetState, DrugAction] = {
    "hyperactive": "inhibiting",
    "hypoactive": "activating",
}

_STATE_IT = {"hyperactive": "iperattivo", "hypoactive": "ipoattivo", "unknown": "indeterminato"}
_ACTION_IT = {"inhibiting": "inibitoria", "activating": "attivatoria", "ambiguous": "ambigua"}


def assess(
    mechanism: DiseaseMechanism,
    causal_gene: str,
    target_gene: str,
    interaction_types: list[str],
    borrowed_gene: bool = False,
) -> DirectionAssessment:
    """Valuta la coerenza direzionale.

    `borrowed_gene` indica che il gene di partenza appartiene a un'altra
    malattia, raggiunta per somiglianza fenotipica. In quel caso il meccanismo
    curato della malattia interrogata non e' applicabile e la motivazione deve
    dirlo con precisione, invece di lasciar credere che manchi un'annotazione.
    """
    action = classify_drug_action(interaction_types)
    sign, via, edge_sources = _edge_sign(causal_gene, target_gene)

    # --- Casi in cui la direzione non e' determinabile, ciascuno con la sua ragione
    if mechanism is DiseaseMechanism.UNKNOWN:
        if borrowed_gene:
            rationale = (
                f"{causal_gene} e' il gene causale di un'altra malattia, raggiunta per "
                "somiglianza fenotipica. Il meccanismo annotato per la malattia "
                "interrogata non si trasferisce insieme al gene: perdita o guadagno di "
                "funzione sono proprieta' di una specifica coppia gene-malattia, e "
                "assumerle valide anche qui produrrebbe una coerenza direzionale "
                "asserita su un presupposto mai verificato."
            )
        else:
            rationale = (
                "Il meccanismo della malattia (perdita o guadagno di funzione) non e' "
                "annotato in config/mechanism.yaml, quindi la direzione dell'effetto "
                "atteso non e' determinabile."
            )
        return DirectionAssessment(
            verdict="unknown",
            disease_mechanism=mechanism,
            expected_target_state="unknown",
            drug_action=action,
            rationale=rationale,
            sources=[],
        )

    if sign is None:
        return DirectionAssessment(
            verdict="unknown",
            disease_mechanism=mechanism,
            expected_target_state="unknown",
            drug_action=action,
            rationale=(
                f"Non esiste una relazione regolatoria con segno curata fra {causal_gene} "
                f"e {target_gene}: i due geni condividono un pathway, ma la fonte non dice "
                "se l'uno attivi o inibisca l'altro."
            ),
            sources=[],
        )

    expected = _expected_state(mechanism, sign)

    if action == "ambiguous":
        return DirectionAssessment(
            verdict="unknown",
            disease_mechanism=mechanism,
            expected_target_state=expected,
            drug_action=action,
            rationale=(
                f"Nella malattia {target_gene} e' atteso {_STATE_IT[expected]}, ma i tipi di "
                f"interazione riportati da DGIdb non identificano univocamente se il farmaco "
                f"lo inibisca o lo attivi."
            ),
            sources=edge_sources,
        )

    needed = _OPPOSES[expected]
    coherent = action == needed
    mech_it = (
        "perdita di funzione"
        if mechanism is DiseaseMechanism.LOSS_OF_FUNCTION
        else "guadagno di funzione"
    )

    rationale = (
        f"La malattia deriva da {mech_it} di {causal_gene}"
        + (f" ({via})" if via else "")
        + f". Ne consegue che {target_gene} e' atteso {_STATE_IT[expected]}, e l'intervento "
        f"appropriato sarebbe {_ACTION_IT[needed]}. L'azione riportata del farmaco e' "
        f"{_ACTION_IT[action]}: "
        + (
            "le due direzioni concordano."
            if coherent
            else "le due direzioni sono opposte, quindi l'effetto atteso andrebbe nella "
            "direzione sbagliata rispetto al difetto."
        )
    )

    return DirectionAssessment(
        verdict="coherent" if coherent else "incoherent",
        disease_mechanism=mechanism,
        expected_target_state=expected,
        drug_action=action,
        rationale=rationale,
        sources=edge_sources,
    )
