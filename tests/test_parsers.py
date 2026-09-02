"""Test dei parser delle fonti.

I campioni sono ritagli minimi che riproducono la struttura reale dei file
(verificata sulle release scaricate), non invenzioni. Servono a fissare il
contratto di formato: quando una fonte cambia schema, sono questi test a doverlo
dire, invece di una pipeline che produce silenziosamente zero risultati.
"""

from __future__ import annotations

from pathlib import Path

from repurposerd.sources.parsers import (
    parse_dgidb,
    parse_mondo_obo,
    parse_orphanet_gene_associations,
    parse_reactome_gene_pathway,
    parse_reactome_relations,
)

# --------------------------------------------------------------- Mondo

MONDO_OBO = """\
format-version: 1.2
ontology: mondo

[Term]
id: MONDO:0001734
name: tuberous sclerosis
def: "Una malattia genetica." [MONDO:design]
synonym: "TSC" EXACT [OMIM:191100]
synonym: "Bourneville disease" EXACT []
xref: Orphanet:805
xref: OMIM:191100
is_a: MONDO:0019052 ! neurocutaneous syndrome

[Term]
id: MONDO:0000002
name: termine ritirato
is_obsolete: true

[Typedef]
id: part_of
name: part of
"""


class TestMondoObo:
    def test_estrae_termine_sinonimi_xref_e_padri(self, tmp_path: Path):
        path = tmp_path / "m.obo"
        path.write_text(MONDO_OBO, encoding="utf-8")
        terms = list(parse_mondo_obo(path))

        assert len(terms) == 1, "i termini obsoleti non devono entrare nello store"
        t = terms[0]
        assert t["mondo_id"] == "MONDO:0001734"
        assert t["name"] == "tuberous sclerosis"
        assert "TSC" in t["synonyms"]
        assert "Orphanet:805" in t["xrefs"]
        assert t["parents"] == ["MONDO:0019052"]

    def test_il_commento_dopo_is_a_viene_scartato(self, tmp_path: Path):
        path = tmp_path / "m.obo"
        path.write_text(MONDO_OBO, encoding="utf-8")
        parents = list(parse_mondo_obo(path))[0]["parents"]
        assert all("!" not in p and " " not in p for p in parents)

    def test_le_stanze_typedef_sono_ignorate(self, tmp_path: Path):
        path = tmp_path / "m.obo"
        path.write_text(MONDO_OBO, encoding="utf-8")
        assert all(t["mondo_id"].startswith("MONDO:") for t in parse_mondo_obo(path))


# --------------------------------------------------------------- Orphanet

ORPHANET_XML = """\
<?xml version="1.0" encoding="UTF-8"?>
<JDBOR>
  <DisorderList count="1">
    <Disorder id="1">
      <OrphaCode>805</OrphaCode>
      <Name lang="en">Tuberous sclerosis complex</Name>
      <DisorderGeneAssociationList count="2">
        <DisorderGeneAssociation>
          <SourceOfValidation>9302285[PMID]_12563011[PMID]</SourceOfValidation>
          <Gene id="1">
            <Name lang="en">TSC2</Name>
            <Symbol>TSC2</Symbol>
            <ExternalReferenceList count="2">
              <ExternalReference><Source>HGNC</Source><Reference>12363</Reference></ExternalReference>
              <ExternalReference><Source>OMIM</Source><Reference>191092</Reference></ExternalReference>
            </ExternalReferenceList>
          </Gene>
          <DisorderGeneAssociationType id="17949">
            <Name lang="en">Disease-causing germline mutation(s) in</Name>
          </DisorderGeneAssociationType>
          <DisorderGeneAssociationStatus id="17991">
            <Name lang="en">Assessed</Name>
          </DisorderGeneAssociationStatus>
        </DisorderGeneAssociation>
        <DisorderGeneAssociation>
          <Gene id="2">
            <Name lang="en">interferon gamma</Name>
            <Symbol>IFNG</Symbol>
          </Gene>
          <DisorderGeneAssociationType id="17953">
            <Name lang="en">Modifying germline mutation in</Name>
          </DisorderGeneAssociationType>
        </DisorderGeneAssociation>
      </DisorderGeneAssociationList>
    </Disorder>
  </DisorderList>
</JDBOR>
"""


class TestOrphanet:
    def test_distingue_gene_causale_da_modificatore(self, tmp_path: Path):
        path = tmp_path / "o.xml"
        path.write_text(ORPHANET_XML, encoding="utf-8")
        rows = {r["gene_symbol"]: r for r in parse_orphanet_gene_associations(path)}

        assert rows["TSC2"]["is_causal"] is True
        # E' il filtro che tiene fuori IFNG dai risultati della sclerosi tuberosa:
        # un modificatore e' un'associazione reale, ma non una causa.
        assert rows["IFNG"]["is_causal"] is False

    def test_estrae_pmid_di_validazione(self, tmp_path: Path):
        path = tmp_path / "o.xml"
        path.write_text(ORPHANET_XML, encoding="utf-8")
        rows = {r["gene_symbol"]: r for r in parse_orphanet_gene_associations(path)}
        assert rows["TSC2"]["pmids"] == "9302285,12563011"

    def test_normalizza_riferimenti_esterni(self, tmp_path: Path):
        path = tmp_path / "o.xml"
        path.write_text(ORPHANET_XML, encoding="utf-8")
        row = next(r for r in parse_orphanet_gene_associations(path) if r["gene_symbol"] == "TSC2")
        assert row["orpha_code"] == "ORPHA:805"
        assert row["hgnc_id"] == "HGNC:12363"
        assert row["omim_id"] == "OMIM:191092"


# --------------------------------------------------------------- Reactome

REACTOME_GP = (
    "7249\tR-HSA-165159\thttps://reactome.org/x\tMTOR signalling\tTAS\tHomo sapiens\n"
    "7249\tR-BTA-165159\thttps://reactome.org/x\tMTOR signalling\tTAS\tBos taurus\n"
    "abc\tR-HSA-000000\thttps://reactome.org/x\tRiga malformata\tTAS\tHomo sapiens\n"
)

REACTOME_REL = "R-HSA-165159\tR-HSA-166208\nR-BTA-165159\tR-BTA-166208\n"


class TestReactome:
    def test_filtra_per_specie_e_scarta_righe_malformate(self, tmp_path: Path):
        path = tmp_path / "gp.txt"
        path.write_text(REACTOME_GP, encoding="utf-8")
        rows = list(parse_reactome_gene_pathway(path))
        assert len(rows) == 1
        assert rows[0] == {
            "entrez_id": 7249,
            "pathway_id": "R-HSA-165159",
            "pathway_name": "MTOR signalling",
            "evidence_code": "TAS",
        }

    def test_relazioni_solo_umane(self, tmp_path: Path):
        path = tmp_path / "rel.txt"
        path.write_text(REACTOME_REL, encoding="utf-8")
        rows = list(parse_reactome_relations(path))
        assert rows == [{"parent_id": "R-HSA-165159", "child_id": "R-HSA-166208"}]


# --------------------------------------------------------------- DGIdb

DGIDB_TSV = (
    "gene_claim_name\tgene_concept_id\tgene_name\tinteraction_source_db_name\t"
    "interaction_source_db_version\tinteraction_type\tinteraction_score\tdrug_claim_name\t"
    "drug_concept_id\tdrug_name\tapproved\timmunotherapy\tanti_neoplastic\n"
    "MTOR\thgnc:3942\tmtor\tTTD\t1.0\tinhibitor\t12.5\tSIROLIMUS\tchembl:CHEMBL413\t"
    "SIROLIMUS\tTRUE\tFALSE\tFALSE\n"
    "MTOR\thgnc:3942\tMTOR\tDTC\t1.0\tNULL\tNULL\tX\tNULL\tFARMACO SPERIMENTALE\tFALSE\tFALSE\tFALSE\n"
    "\t\t\tDTC\t1.0\tinhibitor\t1.0\tY\t\t\tTRUE\tFALSE\tFALSE\n"
)


class TestDgidb:
    def test_normalizza_e_scarta_righe_incomplete(self, tmp_path: Path):
        path = tmp_path / "d.tsv"
        path.write_text(DGIDB_TSV, encoding="utf-8")
        rows = list(parse_dgidb(path))

        assert len(rows) == 2, "le righe senza gene o senza farmaco vanno scartate"
        assert rows[0]["gene_symbol"] == "MTOR"  # normalizzato in maiuscolo
        assert rows[0]["approved"] is True
        assert rows[0]["interaction_type"] == "inhibitor"
        assert rows[0]["interaction_score"] == 12.5

    def test_i_valori_null_diventano_none(self, tmp_path: Path):
        path = tmp_path / "d.tsv"
        path.write_text(DGIDB_TSV, encoding="utf-8")
        row = list(parse_dgidb(path))[1]
        assert row["interaction_type"] is None
        assert row["interaction_score"] is None
        assert row["drug_concept_id"] is None
        assert row["approved"] is False
