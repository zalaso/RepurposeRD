"""Parser dei file grezzi delle fonti aperte.

Ogni parser e' uno streaming iterator: i file arrivano a decine di MB e non
c'e' motivo di tenerli interamente in memoria. I formati sono quelli verificati
sulle release reali, non presunti; se una fonte cambia schema, il posto in cui
intervenire e' soltanto questo modulo.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from collections.abc import Iterator
from pathlib import Path

# ---------------------------------------------------------------- HGNC


def parse_hgnc(path: Path) -> Iterator[dict]:
    """hgnc_complete_set.txt: TSV con header.

    Serve il mapping symbol -> entrez_id, perche' Reactome indicizza i geni per
    NCBI Gene ID mentre DGIdb e Orphanet usano i simboli HGNC.
    """
    with path.open(encoding="utf-8", errors="replace") as fh:
        header = fh.readline().rstrip("\n").split("\t")
        idx = {name: i for i, name in enumerate(header)}

        def get(row: list[str], key: str) -> str:
            i = idx.get(key)
            return row[i].strip() if i is not None and i < len(row) else ""

        for line in fh:
            row = line.rstrip("\n").split("\t")
            symbol = get(row, "symbol")
            if not symbol or get(row, "status") != "Approved":
                continue
            entrez = get(row, "entrez_id")
            yield {
                "symbol": symbol.upper(),
                "hgnc_id": get(row, "hgnc_id") or None,
                "entrez_id": int(entrez) if entrez.isdigit() else None,
                "uniprot_ids": get(row, "uniprot_ids") or None,
                "name": get(row, "name") or None,
                "prev_symbols": get(row, "prev_symbol") or None,
                "alias_symbols": get(row, "alias_symbol") or None,
            }


# ---------------------------------------------------------------- Mondo (OBO)

_OBO_STANZA = re.compile(r"^\[(\w+)\]$")


def parse_obo(path: Path, prefix: str) -> Iterator[dict]:
    """Parser OBO generico: stanze [Term] con id / name / synonym / xref / is_a.

    Lo stesso formato serve Mondo e HPO, quindi il parser e' uno solo,
    parametrizzato sul prefisso degli identificatori. Duplicarlo per due
    ontologie che condividono il formato significherebbe correggere due volte
    ogni futuro difetto.
    """
    term: dict | None = None
    in_term = False

    def emit(t: dict | None) -> dict | None:
        if t and t.get("id", "").startswith(prefix) and not t.get("obsolete"):
            return t
        return None

    with path.open(encoding="utf-8", errors="replace") as fh:
        for raw in fh:
            line = raw.rstrip("\n")
            stanza = _OBO_STANZA.match(line.strip())
            if stanza:
                out = emit(term)
                if out:
                    yield out
                in_term = stanza.group(1) == "Term"
                term = {
                    "id": "",
                    "name": "",
                    "definition": None,
                    "synonyms": [],
                    "xrefs": [],
                    "parents": [],
                    "obsolete": False,
                }
                continue
            if not in_term or term is None or ": " not in line:
                continue

            key, _, value = line.partition(": ")
            value = value.strip()
            if key == "id":
                term["id"] = value
            elif key == "name":
                term["name"] = value
            elif key == "def":
                term["definition"] = value.split('"')[1] if '"' in value else value
            elif key == "synonym":
                if '"' in value:
                    term["synonyms"].append(value.split('"')[1])
            elif key == "xref":
                term["xrefs"].append(value.split(" ")[0])
            elif key == "is_a":
                # "is_a: MONDO:0001234 ! nome leggibile" -> si tiene il solo ID
                parent = value.split("!")[0].strip()
                if parent.startswith(prefix):
                    term["parents"].append(parent)
            elif key == "is_obsolete" and value.lower() == "true":
                term["obsolete"] = True

    out = emit(term)
    if out:
        yield out


def parse_mondo_obo(path: Path) -> Iterator[dict]:
    """mondo-rare.obo.

    Si usa il subset 'rare' perche' copre esattamente il dominio del progetto a
    circa un settimo della dimensione della release completa. La chiave dell'id
    e' rinominata in `mondo_id` per compatibilita' con il resto della pipeline.
    """
    for term in parse_obo(path, "MONDO:"):
        term["mondo_id"] = term.pop("id")
        yield term


def parse_hpo_obo(path: Path) -> Iterator[dict]:
    """hp-base.obo: termini fenotipici e loro gerarchia.

    La gerarchia serve alla regola del true-path: una malattia annotata con un
    termine e' implicitamente annotata con tutti i suoi antenati, ed e' cio' che
    rende confrontabili annotazioni fatte a livelli di dettaglio diversi.
    """
    for term in parse_obo(path, "HP:"):
        term["hpo_id"] = term.pop("id")
        yield term


HPOA_PHENOTYPE_ASPECT = "P"


def parse_phenotype_hpoa(path: Path) -> Iterator[dict]:
    """phenotype.hpoa: annotazioni malattia -> fenotipo curate da HPO.

    Si tengono solo le righe con `aspect == 'P'` (anomalia fenotipica). Le altre
    descrivono modalita' di trasmissione, decorso clinico e modificatori: sono
    informazioni reali, ma includerle nella similarita' fenotipica farebbe
    somigliare fra loro tutte le malattie autosomiche recessive a prescindere
    dal quadro clinico.

    Si escludono anche le righe con qualifier 'NOT', che asseriscono l'ASSENZA
    di un fenotipo: trattarle come presenza invertirebbe il loro significato.
    """
    with path.open(encoding="utf-8", errors="replace") as fh:
        header: list[str] = []
        for line in fh:
            if line.startswith("#"):
                continue
            if not header:
                header = line.rstrip("\n").split("\t")
                continue
            row = line.rstrip("\n").split("\t")
            if len(row) < len(header):
                continue
            rec = dict(zip(header, row, strict=False))

            if rec.get("aspect", "").strip() != HPOA_PHENOTYPE_ASPECT:
                continue
            if rec.get("qualifier", "").strip().upper() == "NOT":
                continue

            disease_id = rec.get("database_id", "").strip()
            hpo_id = rec.get("hpo_id", "").strip()
            if not disease_id or not hpo_id.startswith("HP:"):
                continue

            # phenotype.hpoa usa 'ORPHA:' come Orphanet: gia' la forma canonica
            # usata altrove nella pipeline.
            yield {
                "disease_id": disease_id,
                "disease_name": rec.get("disease_name", "").strip() or None,
                "hpo_id": hpo_id,
                "evidence": rec.get("evidence", "").strip() or None,
                "frequency": rec.get("frequency", "").strip() or None,
                "reference": rec.get("reference", "").strip() or None,
            }


# ---------------------------------------------------------------- Orphanet

# Solo queste associazioni identificano un gene CAUSALE. Le altre (modificatore,
# candidato, suscettibilita') descrivono un rapporto reale ma non monogenico
# causale: includerle qui gonfierebbe i falsi positivi a monte di tutto il resto.
CAUSAL_ASSOCIATION_TYPES = {
    "Disease-causing germline mutation(s) in",
    "Disease-causing germline mutation(s) (loss of function) in",
    "Disease-causing germline mutation(s) (gain of function) in",
    "Disease-causing somatic mutation(s) in",
}

_PMID_RE = re.compile(r"(\d+)\[PMID\]")


def parse_orphanet_gene_associations(path: Path) -> Iterator[dict]:
    """en_product6.xml: associazioni malattia-gene curate da Orphanet (CC BY 4.0)."""
    for _event, disorder in ET.iterparse(str(path), events=("end",)):
        if disorder.tag != "Disorder":
            continue

        orpha_code = (disorder.findtext("OrphaCode", default="") or "").strip()
        disorder_name = (disorder.findtext("Name", default="") or "").strip()

        for assoc in disorder.iterfind("./DisorderGeneAssociationList/DisorderGeneAssociation"):
            gene = assoc.find("Gene")
            if gene is None:
                continue
            symbol = (gene.findtext("Symbol", default="") or "").strip()
            if not symbol:
                continue

            assoc_type = (
                assoc.findtext("./DisorderGeneAssociationType/Name", default="") or ""
            ).strip()
            assoc_status = (
                assoc.findtext("./DisorderGeneAssociationStatus/Name", default="") or ""
            ).strip()

            hgnc_ref = None
            omim_ref = None
            for ext in gene.iterfind("./ExternalReferenceList/ExternalReference"):
                src = (ext.findtext("Source", default="") or "").strip()
                ref = (ext.findtext("Reference", default="") or "").strip()
                if src == "HGNC":
                    hgnc_ref = "HGNC:" + ref
                elif src == "OMIM":
                    omim_ref = "OMIM:" + ref

            validation = assoc.findtext("SourceOfValidation", default="") or ""
            pmids = _PMID_RE.findall(validation)

            yield {
                "orpha_code": "ORPHA:" + orpha_code,
                "disorder_name": disorder_name,
                "gene_symbol": symbol.upper(),
                "gene_name": (gene.findtext("Name", default="") or "").strip() or None,
                "hgnc_id": hgnc_ref,
                "omim_id": omim_ref,
                "association_type": assoc_type,
                "association_status": assoc_status,
                "is_causal": assoc_type in CAUSAL_ASSOCIATION_TYPES,
                "pmids": ",".join(pmids) if pmids else None,
            }

        # iterparse: senza clear() il DOM cresce fino a esaurire la memoria.
        disorder.clear()


# ---------------------------------------------------------------- Reactome


def parse_reactome_gene_pathway(path: Path, species: str = "Homo sapiens") -> Iterator[dict]:
    """NCBI2Reactome_All_Levels.txt.

    Colonne: entrez_id, pathway_id, url, pathway_name, evidence_code, species.
    """
    with path.open(encoding="utf-8", errors="replace") as fh:
        for line in fh:
            parts = line.rstrip("\n").split("\t")
            if len(parts) < 6 or parts[5].strip() != species:
                continue
            entrez = parts[0].strip()
            if not entrez.isdigit():
                continue
            yield {
                "entrez_id": int(entrez),
                "pathway_id": parts[1].strip(),
                "pathway_name": parts[3].strip(),
                "evidence_code": parts[4].strip(),
            }


def parse_reactome_relations(path: Path, prefix: str = "R-HSA-") -> Iterator[dict]:
    """ReactomePathwaysRelation.txt: parent_id <tab> child_id, tutte le specie."""
    with path.open(encoding="utf-8", errors="replace") as fh:
        for line in fh:
            parts = line.rstrip("\n").split("\t")
            if len(parts) < 2:
                continue
            parent, child = parts[0].strip(), parts[1].strip()
            if parent.startswith(prefix) and child.startswith(prefix):
                yield {"parent_id": parent, "child_id": child}


def parse_reactome_pathways(path: Path, species: str = "Homo sapiens") -> Iterator[dict]:
    """ReactomePathways.txt: pathway_id <tab> nome <tab> specie."""
    with path.open(encoding="utf-8", errors="replace") as fh:
        for line in fh:
            parts = line.rstrip("\n").split("\t")
            if len(parts) < 3 or parts[2].strip() != species:
                continue
            yield {"pathway_id": parts[0].strip(), "pathway_name": parts[1].strip()}


# ---------------------------------------------------------------- DGIdb


def parse_dgidb(path: Path) -> Iterator[dict]:
    """interactions.tsv di DGIdb v5.

    La colonna `approved` e' cio' che implementa il vincolo "farmaco gia'
    approvato"; `interaction_type` e' l'input della valutazione direzionale;
    `interaction_source_db_name` viene propagata fino al report perche' la
    provenienza a monte di ogni singola interazione resti tracciabile.
    """
    with path.open(encoding="utf-8", errors="replace") as fh:
        header = fh.readline().rstrip("\n").split("\t")
        idx = {name: i for i, name in enumerate(header)}

        def get(row: list[str], key: str) -> str:
            i = idx.get(key)
            if i is None or i >= len(row):
                return ""
            v = row[i].strip()
            return "" if v.upper() in {"NULL", "NA", ""} else v

        for line in fh:
            row = line.rstrip("\n").split("\t")
            gene = get(row, "gene_name")
            drug = get(row, "drug_name")
            if not gene or not drug:
                continue
            raw_score = get(row, "interaction_score")
            try:
                score = float(raw_score) if raw_score else None
            except ValueError:
                score = None
            yield {
                "gene_symbol": gene.upper(),
                "gene_concept_id": get(row, "gene_concept_id") or None,
                "drug_name": drug,
                "drug_concept_id": get(row, "drug_concept_id") or None,
                "interaction_type": (get(row, "interaction_type") or "").lower() or None,
                "interaction_score": score,
                "source_db": get(row, "source_db")
                or get(row, "interaction_source_db_name")
                or None,
                "approved": get(row, "approved").upper() == "TRUE",
            }
