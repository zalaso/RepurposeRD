"""Orchestrazione: dalla query all'evidence bundle.

L'evidence bundle e' il contratto centrale del progetto. Contiene tutti e soli i
fatti verificati, ciascuno con la sua provenienza. Il modello linguistico
ricevera' questo oggetto e nient'altro, e il validatore verifichera' il testo
generato contro di esso. Cio' che non e' qui dentro, non esiste.

ORDINE DELLE OPERAZIONI
La letteratura viene interrogata solo per i candidati che hanno gia' superato
una prima selezione. Non e' solo una questione di velocita': PubMed ha un rate
limit che va rispettato, e interrogarlo per centinaia di candidati che verranno
scartati comunque significa trattare male una risorsa pubblica gratuita.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime

import duckdb
from rich.console import Console

from ..config import config_digest, scoring_config
from ..models import (
    Candidate,
    CausalGene,
    Disease,
    DiseaseMechanism,
    EvidenceBundle,
    Gene,
    PathwayLink,
    PhenotypeBridge,
)
from ..provenance import provenance_for
from ..sources.openfda import OpenFDAClient
from . import candidates as cand
from . import direction as direction_mod
from . import literature as lit_mod
from . import pathways as pw
from . import phenotype as ph
from . import scoring
from .resolve import causal_genes_for, resolve

console = Console()


def _shuffled_causal_genes(
    con: duckdb.DuckDBPyConnection, original: list[CausalGene], seed: int
) -> list[CausalGene]:
    """Controllo negativo: sostituisce il gene causale con uno casuale.

    Tutto il resto della pipeline resta identico. Se il ranking prodotto qui e'
    indistinguibile da quello reale, lo score non sta misurando nulla.
    """
    symbol = cand.random_control_gene(con, seed=seed)
    row = con.execute(
        "SELECT symbol, hgnc_id, entrez_id, uniprot_ids, name FROM genes WHERE symbol = ?",
        [symbol],
    ).fetchone()
    if not row:
        return original
    return [
        CausalGene(
            gene=Gene(
                symbol=row[0],
                hgnc_id=row[1],
                entrez_id=row[2],
                uniprot_ids=[u for u in (row[3] or "").split("|") if u],
                name=row[4],
            ),
            association_type="CONTROLLO NEGATIVO — associazione casuale, non reale",
            validation_pmids=[],
            provenance=provenance_for("hgnc", "hgnc_complete_set", record_id=row[0]),
        )
    ]


def rank_candidates(candidates: list[Candidate]) -> list[Candidate]:
    """Ordina i candidati in modo riproducibile.

    Lo spareggio sul nome del farmaco non e' cosmetico. SIROLIMUS, EVEROLIMUS e
    TEMSIROLIMUS ottengono esattamente lo stesso punteggio nel caso pilota della
    sclerosi tuberosa, e senza un criterio esplicito il loro ordine cambia fra
    esecuzioni identiche: un report che non e' riproducibile contraddice
    l'impronta di configurazione che dichiara in intestazione.
    """
    return sorted(candidates, key=lambda c: (-c.score.total, c.drug_name))


def _literature_shortlist(
    ordered: list[tuple[float, Candidate]],
    top_n: int,
    cfg: dict,
) -> tuple[list[tuple[float, Candidate]], bool]:
    """Quali candidati meritano un'interrogazione a PubMed.

    IL PROBLEMA
    La letteratura si interroga solo su una selezione, perche' PubMed ha un rate
    limit e non si interroga un'API pubblica gratuita per millecinquecento
    candidati. Ma la selezione avviene con un punteggio che NON contiene ancora
    la componente di letteratura: un pre-filtro che ignora una componente del
    punteggio finale puo' scartare un candidato che quella componente avrebbe
    promosso sopra la soglia.

    Non e' teorico. Misurato sul caso Niemann-Pick: miglustat — riposizionamento
    reale e documentato — si colloca al 253esimo posto preliminare con 0.391,
    mentre il quarantesimo valeva 0.467. Con una selezione fissa a quaranta
    veniva escluso prima ancora di poter mostrare l'unica evidenza che lo
    distingue, cioe' l'attenzione che la letteratura gli ha gia' dedicato.

    IL CRITERIO
    La componente di letteratura vale al massimo il suo peso (0.10). Quindi
    nessun candidato piu' distante di quel margine dalla soglia puo' superarla,
    e nessun candidato entro quel margine puo' essere escluso senza rischio.
    La selezione e' percio' definita come:

        soglia = punteggio del candidato in posizione top_n - peso(letteratura)

    Il criterio si autoregola e non dipende da un numero scelto a mano.

    IL TETTO
    Resta un limite massimo per il costo. Quando taglia, la garanzia sopra non
    vale piu' e il chiamante lo dichiara nel report: un risultato che potrebbe
    aver perso candidati deve dirlo, invece di sembrare completo.
    """
    if not ordered:
        return [], False

    max_literature = float(cfg["weights"].get("literature_support", 0.0))
    cap = int(cfg["filters"].get("literature_shortlist_cap", 400))

    cutoff_index = min(top_n, len(ordered)) - 1
    threshold = ordered[cutoff_index][0] - max_literature

    eligible = [row for row in ordered if row[0] >= threshold]
    truncated = len(eligible) > cap
    return eligible[:cap], truncated


def _phenotype_bridge_links(
    con: duckdb.DuckDBPyConnection,
    disease: Disease,
    already_reached: set[str],
    max_bridges: int,
    min_similarity: float,
    min_shared_terms: int,
    max_pathway_size: int,
    max_hops: int,
) -> dict[str, PathwayLink]:
    """Geni raggiunti passando per malattie fenotipicamente simili.

    Il ramo esiste perche' quello meccanicistico ha un punto cieco dimostrato:
    se il farmaco agisce su una conseguenza a valle del difetto anziche' sullo
    stesso processo, i due geni non condividono alcun pathway e nessuna soglia
    li avvicina (vedi docs/PILOT_RESULTS.md, caso Niemann-Pick).

    I geni gia' raggiunti dal ramo principale NON vengono sovrascritti: un
    collegamento diretto e' sempre preferibile a uno preso in prestito, e
    lasciare che il ponte lo rimpiazzi peggiorerebbe il punteggio di un
    candidato legittimo.
    """
    matches = ph.similar_diseases(
        con,
        disease.orpha_codes,
        top_k=max_bridges,
        min_similarity=min_similarity,
        min_shared_terms=min_shared_terms,
        exclude_ids=ph.self_match_ids(con, disease.mondo_id),
    )
    if not matches:
        console.print("  [dim]ponte fenotipico: nessuna malattia simile sopra soglia[/dim]")
        return {}

    console.print(
        f"  ponte fenotipico: [bold]{len(matches)}[/bold] malattie simili "
        f"(somiglianza {matches[-1].similarity:.2f}-{matches[0].similarity:.2f})"
    )

    out: dict[str, PathwayLink] = {}
    for match in matches:
        if not match.orpha_codes:
            continue  # senza codice Orphanet non si risale al gene causale
        borrowed = _causal_genes_for_codes(con, match.orpha_codes)
        if not borrowed:
            continue

        bridge_links = pw.expand(
            con, borrowed, max_pathway_size=max_pathway_size, max_hops=max_hops
        )
        for target, link in bridge_links.items():
            if target in already_reached or target in out:
                continue
            link.bridge = PhenotypeBridge(
                source_disease_id=match.disease_id,
                source_disease_name=match.disease_name,
                similarity=match.similarity,
                shared_phenotypes=[p.name for p in match.shared_phenotypes],
                borrowed_gene=link.causal_gene,
                provenance=match.provenance
                or provenance_for("hpo", "hpo_disease_annotations", record_id=match.disease_id),
            )
            link.route = (
                f"{target} e' raggiunto tramite {link.causal_gene}, gene causale di "
                f"«{match.disease_name or match.disease_id}», malattia con somiglianza "
                f"fenotipica {match.similarity:.2f} rispetto a {disease.label}. "
                f"{link.route}"
            )
            out[target] = link

    console.print(f"  geni aggiunti dal ponte fenotipico: [bold]{len(out)}[/bold]")
    return out


def _causal_genes_for_codes(
    con: duckdb.DuckDBPyConnection, orpha_codes: list[str]
) -> list[CausalGene]:
    """Geni causali di una malattia-ponte, con gli stessi filtri del ramo principale."""
    stub = Disease(
        mondo_id="",
        label="",
        orpha_codes=orpha_codes,
        provenance=provenance_for("orphanet", "orphanet_gene_associations"),
    )
    return causal_genes_for(con, stub)


def build_bundle(
    con: duckdb.DuckDBPyConnection,
    query: str,
    top_n: int = 20,
    with_literature: bool = True,
    shuffle_control: bool = False,
    seed: int = 0,
    use_phenotype_bridge: bool = True,
    max_bridges: int | None = None,
    with_regulatory: bool = True,
) -> EvidenceBundle:
    cfg = scoring_config()
    filters = cfg["filters"]

    # --- 1. malattia e geni causali
    resolved = resolve(con, query)
    disease = resolved.disease
    causal_genes = resolved.causal_genes
    console.print(f"  malattia: [bold]{disease.label}[/bold] ({disease.mondo_id})")

    if shuffle_control:
        causal_genes = _shuffled_causal_genes(con, causal_genes, seed)
        console.print(
            f"  [yellow]CONTROLLO NEGATIVO[/yellow]: gene causale sostituito con "
            f"{causal_genes[0].gene.symbol}"
        )

    if not causal_genes:
        raise ValueError(
            f"Nessun gene causale curato da Orphanet per {disease.mondo_id}. "
            "La malattia potrebbe non essere monogenica, o non avere una "
            "cross-reference Orphanet nel subset Mondo caricato."
        )
    console.print(f"  geni causali: [bold]{', '.join(c.gene.symbol for c in causal_genes)}[/bold]")

    # --- 2. meccanismo curato (determina la direzione attesa)
    mechanism, mech_rationale, _mech_sources = direction_mod.disease_mechanism(disease.mondo_id)
    if shuffle_control:
        # Il meccanismo curato appartiene alla malattia reale, non al gene casuale:
        # tenerlo darebbe al controllo un vantaggio che non gli spetta.
        mechanism, mech_rationale = DiseaseMechanism.UNKNOWN, None
    console.print(f"  meccanismo: [bold]{mechanism.value}[/bold]")

    # --- 3. espansione sui pathway
    links = pw.expand(
        con,
        causal_genes,
        max_pathway_size=filters["max_pathway_size"],
        max_hops=filters["max_hops"],
    )
    console.print(f"  geni raggiunti nei pathway: [bold]{len(links)}[/bold]")
    if not links:
        console.print("  [yellow]nessun pathway Reactome sufficientemente specifico[/yellow]")

    # --- 3-bis. ponte fenotipico: secondo punto di ingresso, indipendente dai pathway
    bridge_cfg = cfg.get("phenotype_bridge", {})
    if bridge_cfg.get("enabled") and use_phenotype_bridge:
        # Nel controllo negativo il ponte non viene disattivato ma alimentato
        # con il profilo fenotipico di una malattia casuale. Disattivarlo
        # lascerebbe meta' della pipeline senza controllo; lasciarlo sul
        # profilo vero gli darebbe vicini autentici, cioe' un vantaggio che
        # al controllo non spetta.
        bridge_disease = disease
        if shuffle_control:
            fake_codes = cand.random_control_phenotype_source(con, seed=seed)
            bridge_disease = replace(disease, orpha_codes=fake_codes)
            console.print(
                f"  [yellow]CONTROLLO NEGATIVO[/yellow]: profilo fenotipico sostituito "
                f"con {fake_codes[0] if fake_codes else 'nessuno'}"
            )
        links |= _phenotype_bridge_links(
            con,
            disease=bridge_disease,
            already_reached=set(links),
            max_bridges=max_bridges or int(bridge_cfg.get("max_bridges", 30)),
            min_similarity=float(bridge_cfg.get("min_similarity", 0.15)),
            min_shared_terms=int(bridge_cfg.get("min_shared_terms", 5)),
            max_pathway_size=filters["max_pathway_size"],
            max_hops=filters["max_hops"],
        )

    # --- 4. farmaci approvati sui geni raggiunti
    interactions = cand.find_drugs(con, list(links), require_approved=filters["require_approved"])
    console.print(f"  interazioni farmaco-gene approvate: [bold]{len(interactions)}[/bold]")

    # --- 5. direzione + score preliminare (senza letteratura)
    preliminary: list[tuple[float, Candidate]] = []
    keep_incoherent = cfg["components"]["direction_coherence"].get("keep_incoherent", True)

    for inter in interactions:
        link = links[inter.gene_symbol]
        # Il meccanismo curato appartiene alla malattia interrogata. Per un
        # candidato del ponte fenotipico il gene di partenza e' preso in
        # prestito da un'ALTRA malattia, e non c'e' ragione di credere che
        # perdita o guadagno di funzione si trasferiscano insieme al gene:
        # applicarlo comunque produrrebbe una coerenza direzionale asserita su
        # un presupposto mai verificato. Si dichiara quindi `unknown`, che
        # abbassa il punteggio ed e' la posizione onesta.
        link_mechanism = DiseaseMechanism.UNKNOWN if link.bridge else mechanism
        assessment = direction_mod.assess(
            link_mechanism,
            link.causal_gene,
            inter.gene_symbol,
            inter.interaction_types,
            borrowed_gene=link.bridge is not None,
        )
        if assessment.verdict == "incoherent" and not keep_incoherent:
            continue

        breakdown = scoring.score_candidate(link, inter, assessment, literature=[])
        tier, weak = scoring.tier_for(breakdown.total, assessment.verdict)
        preliminary.append(
            (
                breakdown.total,
                Candidate(
                    drug_name=inter.drug_name,
                    drug_concept_id=inter.drug_concept_id,
                    target_gene=inter.gene_symbol,
                    pathway_link=link,
                    interaction=inter,
                    direction=assessment,
                    literature=[],
                    score=breakdown,
                    tier=tier,
                    weak_evidence_flag=weak,
                ),
            )
        )

    # Un farmaco che colpisce piu' geni dello stesso pathway comparirebbe piu'
    # volte: si tiene la sua istanza migliore, perche' un report in cui lo stesso
    # farmaco appare otto volte e' meno leggibile, non piu' informativo.
    by_drug: dict[str, tuple[float, Candidate]] = {}
    for total, c in preliminary:
        key = c.drug_name.lower()
        if key not in by_drug or total > by_drug[key][0]:
            by_drug[key] = (total, c)

    # Lo spareggio sul nome del farmaco non e' cosmetico: SIROLIMUS, EVEROLIMUS e
    # TEMSIROLIMUS ottengono esattamente lo stesso punteggio, e senza un criterio
    # esplicito il loro ordine cambia fra esecuzioni identiche. Un report che non
    # e' riproducibile contraddice l'impronta di configurazione che dichiara.
    ordered = sorted(by_drug.values(), key=lambda t: (-t[0], t[1].drug_name))
    console.print(f"  candidati distinti: [bold]{len(by_drug)}[/bold]")

    shortlist, truncated = _literature_shortlist(ordered, top_n=top_n, cfg=cfg)

    # --- 6. letteratura sui soli candidati in shortlist, poi riassegnazione dello score
    final: list[Candidate] = []
    if with_literature and shortlist:
        client = lit_mod.PubMedClient()
        console.print(f"  interrogazione PubMed su {len(shortlist)} candidati ...")
        if truncated:
            console.print(
                "  [yellow]il tetto della selezione ha tagliato: alcuni candidati non "
                "sono stati interrogati e potrebbero mancare dal ranking[/yellow]"
            )
        primary_gene = causal_genes[0].gene.symbol
        # Un'unica passata accorpata: le esearch restano una per interrogazione,
        # le esummary si fanno tutte insieme in blocchi da duecento. Dimezza le
        # richieste a un'API pubblica di cui se ne fanno decine di migliaia.
        per_drug = lit_mod.gather_many(
            client,
            [c.drug_name for _, c in shortlist],
            disease.label,
            primary_gene,
        )
        for _, c in shortlist:
            c.literature = per_drug.get(c.drug_name, [])
            c.score = scoring.score_candidate(
                c.pathway_link, c.interaction, c.direction, c.literature
            )
            c.tier, c.weak_evidence_flag = scoring.tier_for(c.score.total, c.direction.verdict)
            final.append(c)
        client.save_cache()
    else:
        final = [c for _, c in shortlist]

    final = rank_candidates(final)
    final = [c for c in final if c.score.total >= filters["min_score"]][:top_n]
    console.print(f"  candidati sopra la soglia: [bold]{len(final)}[/bold]")

    # --- 6-bis. conferma regolatoria indipendente, solo sui candidati finali
    # Si interroga dopo il taglio perche' e' informativa e non influenza
    # l'ordinamento: interrogarla prima costerebbe centinaia di richieste
    # per un dato che non sposta nulla nel ranking.
    if with_regulatory and final:
        fda = OpenFDAClient()
        console.print(f"  conferma FDA su {len(final)} candidati ...")
        for c in final:
            c.regulatory = fda.label_for(c.drug_name)
        fda.save_cache()
        senza = sum(1 for c in final if c.regulatory and not c.regulatory.label_found)
        if senza:
            console.print(
                f"  [yellow]{senza} candidati marcati approvati da DGIdb non hanno "
                "un'etichetta FDA[/yellow]"
            )

    # --- 7. bundle
    provenances = [disease.provenance]
    provenances += [cg.provenance for cg in causal_genes]
    for c in final:
        provenances += [c.pathway_link.pathway.provenance, c.interaction.provenance]
        provenances += [lit.provenance for lit in c.literature]
        if c.regulatory:
            provenances.append(c.regulatory.provenance)
    unique_prov = list({(p.source_id, p.version, p.accessed_at): p for p in provenances}.values())

    return EvidenceBundle(
        disease=disease,
        mechanism=mechanism,
        mechanism_rationale=mech_rationale,
        causal_genes=causal_genes,
        candidates=final,
        generated_at=datetime.now(),
        config_digest=config_digest(),
        provenances=unique_prov,
        literature_shortlist_truncated=bool(truncated and with_literature),
    )
