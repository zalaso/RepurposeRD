"""Tipi di dominio di RepurposeRD.

Regola architetturale che attraversa tutto il modulo: nessun fatto biologico
esiste senza una `Provenance`. Se un dato non sa dire da dove viene, non entra
nell'evidence bundle, e quindi non puo' finire in un report.

PERCHE' DATACLASS E NON PYDANTIC
Il progetto usava pydantic. E' stato rimosso perche' `pydantic_core` e' una
libreria nativa non firmata, e Smart App Control — attivo per impostazione
predefinita su Windows recenti — la blocca. Chi installava il progetto su una
macchina Windows aggiornata si trovava davanti a una scelta irreversibile
(disattivare Smart App Control non e' annullabile senza reinstallare il sistema)
solo per far girare uno strumento di ricerca.

Un progetto che promette "100% locale, gira ovunque" non puo' dipendere da una
wheel che la sicurezza predefinita di un sistema operativo diffuso puo'
bloccare a propria discrezione. Le dataclass della libreria standard non hanno
codice nativo e non hanno questo problema.

Cosa si perde: la validazione automatica dei tipi alla costruzione. Qui vale
poco, perche' questi oggetti non ricevono input esterni — sono costruiti dai
parser del progetto, che hanno i loro test. La serializzazione JSON, che era
l'altro servizio utile di pydantic, e' in `serialize.py`.

`kw_only=True` su ogni dataclass: senza, i campi con default dovrebbero
precedere quelli senza, e l'ordine dei campi dovrebbe essere riorganizzato
per compiacere il linguaggio anziche' per leggibilita'.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from enum import Enum
from typing import Literal


@dataclass(kw_only=True)
class Provenance:
    """Da dove viene un singolo fatto. Obbligatoria ovunque."""

    source_id: str  # es. "reactome", "orphanet"
    source_name: str
    license: str
    url: str | None = None
    version: str | None = None
    accessed_at: date | None = None
    record_id: str | None = None  # identificatore del record nella fonte

    def cite(self) -> str:
        bits = [self.source_name]
        if self.version:
            bits.append(f"v{self.version}")
        if self.accessed_at:
            bits.append(f"accesso {self.accessed_at.isoformat()}")
        return " — ".join(bits)


@dataclass(kw_only=True)
class Gene:
    symbol: str
    hgnc_id: str | None = None
    entrez_id: int | None = None
    uniprot_ids: list[str] = field(default_factory=list)
    name: str | None = None


@dataclass(kw_only=True)
class Disease:
    mondo_id: str
    label: str
    synonyms: list[str] = field(default_factory=list)
    orpha_codes: list[str] = field(default_factory=list)
    omim_ids: list[str] = field(default_factory=list)
    provenance: Provenance


class DiseaseMechanism(str, Enum):
    LOSS_OF_FUNCTION = "loss_of_function"
    GAIN_OF_FUNCTION = "gain_of_function"
    UNKNOWN = "unknown"


@dataclass(kw_only=True)
class CausalGene:
    """Gene causale di una malattia monogenica, con il tipo di associazione curato."""

    gene: Gene
    association_type: str  # es. "Disease-causing germline mutation(s) in"
    validation_pmids: list[str] = field(default_factory=list)
    provenance: Provenance


@dataclass(kw_only=True)
class PhenotypeBridge:
    """Provenienza di un candidato arrivato dal ramo fenotipico.

    Un candidato con questo campo valorizzato NON deriva dal gene causale della
    malattia interrogata, ma da quello di una malattia clinicamente simile. E'
    un'ipotesi piu' indiretta e il report deve dirlo: la somiglianza fenotipica
    e' un indizio di biologia condivisa a valle, non una prova di parentela
    meccanicistica.
    """

    source_disease_id: str
    source_disease_name: str | None = None
    similarity: float
    shared_phenotypes: list[str] = field(default_factory=list)
    borrowed_gene: str
    provenance: Provenance

    def describe(self) -> str:
        top = ", ".join(self.shared_phenotypes[:4])
        return (
            f"{self.borrowed_gene} e' il gene causale di "
            f"{self.source_disease_name or self.source_disease_id}, malattia con "
            f"somiglianza fenotipica {self.similarity:.2f} (fenotipi condivisi: {top})"
        )


@dataclass(kw_only=True)
class Pathway:
    reactome_id: str
    name: str
    size: int  # numero di geni umani annotati, determina la specificita'
    provenance: Provenance


@dataclass(kw_only=True)
class PathwayLink:
    """Il ponte meccanicistico: come si arriva dal gene causale al bersaglio del farmaco."""

    causal_gene: str
    target_gene: str
    pathway: Pathway
    hops: int  # 0 = stesso gene, 1 = stesso pathway, 2 = pathway padre/figlio
    route: str  # descrizione leggibile del percorso
    # Tutti i pathway (entro il tetto di dimensione) che collegano i due geni.
    # `pathway` sopra e' il piu' specifico ed e' quello che entra nello score;
    # questo elenco esiste perche' il piu' piccolo non e' sempre il piu'
    # significativo per un lettore umano, e nascondere gli altri lo priverebbe
    # del contesto necessario a giudicare.
    shared_pathways: list[str] = field(default_factory=list)
    # Valorizzato solo per i candidati provenienti dal ramo fenotipico.
    # `causal_gene` in quel caso e' il gene preso in prestito, non quello
    # della malattia interrogata: senza questo campo la differenza sarebbe
    # invisibile al lettore del report.
    bridge: PhenotypeBridge | None = None


@dataclass(kw_only=True)
class DrugInteraction:
    drug_name: str
    drug_concept_id: str | None = None
    gene_symbol: str
    interaction_types: list[str] = field(default_factory=list)
    source_dbs: list[str] = field(default_factory=list)
    approved: bool = False
    max_interaction_score: float | None = None
    provenance: Provenance


DirectionVerdict = Literal["coherent", "incoherent", "unknown"]
DrugAction = Literal["inhibiting", "activating", "ambiguous"]
TargetState = Literal["hyperactive", "hypoactive", "unknown"]


@dataclass(kw_only=True)
class DirectionAssessment:
    """Valutazione della coerenza direzionale farmaco / meccanismo di malattia.

    `unknown` non e' un esito neutro: e' una lacuna dichiarata dell'evidenza e
    come tale abbassa il punteggio finale.
    """

    verdict: DirectionVerdict
    disease_mechanism: DiseaseMechanism
    expected_target_state: TargetState
    drug_action: DrugAction
    rationale: str
    sources: list[str] = field(default_factory=list)


@dataclass(kw_only=True)
class Article:
    pmid: str
    title: str | None = None
    journal: str | None = None
    year: int | None = None

    @property
    def url(self) -> str:
        return f"https://pubmed.ncbi.nlm.nih.gov/{self.pmid}/"


@dataclass(kw_only=True)
class LiteratureEvidence:
    """Conteggio e identificativi di letteratura reale.

    Si memorizza il CONTEGGIO, mai un giudizio sul contenuto: la numerosita'
    misura quanta attenzione ha ricevuto un accostamento, non se funziona.
    """

    query_label: str
    query_string: str
    total_count: int
    articles: list[Article] = field(default_factory=list)
    provenance: Provenance


@dataclass(kw_only=True)
class RegulatoryLabel:
    """Etichetta regolatoria FDA, quando esiste.

    E' informativa e NON entra nel punteggio. openFDA copre gli Stati Uniti, e
    usarla per ordinare i candidati penalizzerebbe i farmaci approvati solo
    altrove, che nelle malattie rare sono molti: miglustat e' autorizzato da EMA
    per Niemann-Pick tipo C, indicazione che l'FDA non ha mai concesso. Un
    candidato non e' piu' debole perche' e' stato approvato a Bruxelles.

    Il suo valore e' un altro: mostrare le indicazioni etichettate accanto
    all'ipotesi rende evidente che l'ipotesi e' **fuori indicazione**.
    """

    drug_name: str
    label_found: bool
    generic_names: list[str] = field(default_factory=list)
    brand_names: list[str] = field(default_factory=list)
    routes: list[str] = field(default_factory=list)
    application_numbers: list[str] = field(default_factory=list)
    labeled_indications: str | None = None
    matching_labels: int | None = None
    provenance: Provenance

    @property
    def approval_kind(self) -> str | None:
        """NDA = farmaco nuovo, BLA = biologico, ANDA = equivalente generico."""
        for number in self.application_numbers:
            for prefix in ("NDA", "BLA", "ANDA"):
                if number.upper().startswith(prefix):
                    return prefix
        return None


@dataclass(kw_only=True)
class ScoreBreakdown:
    """Score scomposto. Ogni componente e' mostrata nel report: nessun numero opaco."""

    components: dict[str, float]
    weights: dict[str, float]
    total: float

    def contributions(self) -> dict[str, float]:
        return {k: round(v * self.weights.get(k, 0.0), 4) for k, v in self.components.items()}


@dataclass(kw_only=True)
class Candidate:
    drug_name: str
    drug_concept_id: str | None = None
    target_gene: str
    pathway_link: PathwayLink
    interaction: DrugInteraction
    direction: DirectionAssessment
    literature: list[LiteratureEvidence] = field(default_factory=list)
    # Conferma regolatoria indipendente. Informativa: non entra nello score.
    regulatory: RegulatoryLabel | None = None
    score: ScoreBreakdown
    tier: str
    weak_evidence_flag: bool
    # Popolata dal layer LLM, sempre dopo validazione contro il bundle.
    narrative: str | None = None

    @property
    def total_pmids(self) -> list[str]:
        seen: list[str] = []
        for lit in self.literature:
            for art in lit.articles:
                if art.pmid not in seen:
                    seen.append(art.pmid)
        return seen


@dataclass(kw_only=True)
class EvidenceBundle:
    """L'unico input che il modello linguistico e' autorizzato a vedere.

    Il validatore anti-allucinazione verifica che ogni entita' citata nel testo
    generato compaia in questo oggetto. Cio' che non e' qui dentro, non esiste.
    """

    disease: Disease
    mechanism: DiseaseMechanism
    mechanism_rationale: str | None = None
    # Chi attribuisce il meccanismo: `curato` (config/mechanism.yaml, con
    # motivazione e fonti scelte a mano), `orphanet` (derivato dal tipo di
    # associazione dichiarato dalla fonte) o `ignoto`. Autorita' diverse, e
    # il lettore del report deve poterle distinguere.
    mechanism_origin: str = "ignoto"
    causal_genes: list[CausalGene]
    candidates: list[Candidate]
    generated_at: datetime
    config_digest: str  # hash della configurazione di scoring: rende il run riproducibile
    provenances: list[Provenance] = field(default_factory=list)
    # Vero se il tetto sulla preselezione per la letteratura ha tagliato.
    # In quel caso la garanzia del criterio non vale piu' e alcuni candidati
    # legittimi possono essere assenti: chi legge questo bundle deve poter
    # distinguere "non trovato" da "non interrogato".
    literature_shortlist_truncated: bool = False

    # --- Vocabolari consentiti, usati dal validatore ---

    def allowed_pmids(self) -> set[str]:
        out: set[str] = set()
        for cg in self.causal_genes:
            out.update(cg.validation_pmids)
        for c in self.candidates:
            out.update(c.total_pmids)
            out.update(s.split(":")[-1] for s in c.direction.sources if s.startswith("PMID:"))
        return out

    def allowed_drugs(self) -> set[str]:
        return {c.drug_name.lower() for c in self.candidates}

    def allowed_genes(self) -> set[str]:
        out = {cg.gene.symbol.upper() for cg in self.causal_genes}
        for c in self.candidates:
            out.add(c.target_gene.upper())
            out.add(c.pathway_link.causal_gene.upper())
            if c.pathway_link.bridge:
                out.add(c.pathway_link.bridge.borrowed_gene.upper())
        return out

    def allowed_identifiers(self) -> set[str]:
        out = {self.disease.mondo_id}
        out.update(self.disease.orpha_codes)
        out.update(self.disease.omim_ids)
        for c in self.candidates:
            out.add(c.pathway_link.pathway.reactome_id)
            if c.drug_concept_id:
                out.add(c.drug_concept_id)
            if c.pathway_link.bridge:
                out.add(c.pathway_link.bridge.source_disease_id)
        return out
