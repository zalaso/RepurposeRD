"""Fixture condivise.

I test usano geni e farmaci INVENTATI (GENEA, FARMACOX) dove verificano la
logica. E' deliberato: un test che usa TSC2 e sirolimus finisce per verificare
la biologia insieme al codice, e quando fallisce non si sa quale delle due sia
rotta. La biologia reale si verifica eseguendo la pipeline sulle fonti vere,
non nella suite unitaria.
"""

from __future__ import annotations

from datetime import date, datetime

import pytest

from repurposerd.models import (
    Article,
    Candidate,
    CausalGene,
    DirectionAssessment,
    Disease,
    DiseaseMechanism,
    DrugInteraction,
    EvidenceBundle,
    Gene,
    LiteratureEvidence,
    Pathway,
    PathwayLink,
    Provenance,
    ScoreBreakdown,
)


@pytest.fixture
def provenance() -> Provenance:
    return Provenance(
        source_id="reactome",
        source_name="Reactome Pathway Database",
        license="CC0-1.0",
        url="https://reactome.org/",
        version="90",
        accessed_at=date(2026, 1, 1),
    )


@pytest.fixture
def pathway(provenance: Provenance) -> Pathway:
    return Pathway(
        reactome_id="R-HSA-9999999", name="Pathway di prova", size=20, provenance=provenance
    )


@pytest.fixture
def link(pathway: Pathway) -> PathwayLink:
    return PathwayLink(
        causal_gene="GENEA",
        target_gene="GENEB",
        pathway=pathway,
        hops=1,
        route="GENEA e GENEB condividono il pathway di prova",
        shared_pathways=["Pathway di prova"],
    )


@pytest.fixture
def interaction(provenance: Provenance) -> DrugInteraction:
    return DrugInteraction(
        drug_name="FARMACOX",
        drug_concept_id="chembl:CHEMBL999999",
        gene_symbol="GENEB",
        interaction_types=["inhibitor"],
        source_dbs=["DB1", "DB2"],
        approved=True,
        max_interaction_score=0.9,
        provenance=provenance,
    )


@pytest.fixture
def assessment() -> DirectionAssessment:
    return DirectionAssessment(
        verdict="coherent",
        disease_mechanism=DiseaseMechanism.LOSS_OF_FUNCTION,
        expected_target_state="hyperactive",
        drug_action="inhibiting",
        rationale="motivazione di prova",
        sources=["PMID:11111111"],
    )


@pytest.fixture
def literature(provenance: Provenance) -> list[LiteratureEvidence]:
    return [
        LiteratureEvidence(
            query_label="drug_and_disease",
            query_string='"FARMACOX"[tiab] AND "malattia di prova"[tiab]',
            total_count=7,
            articles=[
                Article(pmid="22222222", title="Titolo di prova", journal="J Test", year=2024)
            ],
            provenance=provenance,
        )
    ]


@pytest.fixture
def candidate(link, interaction, assessment, literature) -> Candidate:
    return Candidate(
        drug_name="FARMACOX",
        drug_concept_id="chembl:CHEMBL999999",
        target_gene="GENEB",
        pathway_link=link,
        interaction=interaction,
        direction=assessment,
        literature=literature,
        score=ScoreBreakdown(
            components={"pathway_proximity": 0.6, "direction_coherence": 1.0},
            weights={"pathway_proximity": 0.3, "direction_coherence": 0.25},
            total=0.43,
        ),
        tier="limitata",
        weak_evidence_flag=True,
    )


@pytest.fixture
def bundle(candidate, provenance) -> EvidenceBundle:
    disease = Disease(
        mondo_id="MONDO:0000001",
        label="malattia di prova",
        synonyms=[],
        orpha_codes=["ORPHA:1"],
        omim_ids=["OMIM:100000"],
        provenance=provenance,
    )
    causal = CausalGene(
        gene=Gene(symbol="GENEA", hgnc_id="HGNC:1", entrez_id=1),
        association_type="Disease-causing germline mutation(s) in",
        validation_pmids=["33333333"],
        provenance=provenance,
    )
    return EvidenceBundle(
        disease=disease,
        mechanism=DiseaseMechanism.LOSS_OF_FUNCTION,
        mechanism_rationale="motivazione di prova",
        causal_genes=[causal],
        candidates=[candidate],
        generated_at=datetime(2026, 1, 1, 12, 0),
        config_digest="testdigest01",
        provenances=[provenance],
    )
