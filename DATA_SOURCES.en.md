# Data sources

***English** · [Italiano](DATA_SOURCES.md)*

## Principle: the repository distributes code, not data

RepurposeRD redistributes no biomedical data. It distributes the ETL code that downloads the sources onto the user's machine, recording for each one its license, version, access date and SHA-256 checksum in `data/raw/manifest.json`.

This choice is not only legal prudence. Open sources in the biomedical domain have heterogeneous licenses, some with share-alike clauses that would propagate to any redistributed derived database. By redistributing nothing, the problem does not arise: every user acquires the data directly from the source, under the terms the source itself sets.

`data/` is in `.gitignore`, and stays there.

---

## Integrated sources (phase 1)

### HGNC — HUGO Gene Nomenclature Committee
- **License**: CC0 1.0 (public domain)
- **Role**: normalization of gene symbols, `symbol → Entrez ID → UniProt` mapping
- **Why it is needed**: Reactome indexes genes by NCBI Gene ID, while Orphanet and DGIdb use symbols. Without this bridge the three sources do not speak to each other.
- **File**: `hgnc_complete_set.txt` (~17 MB)

### Mondo Disease Ontology
- **License**: CC BY 4.0
- **Role**: canonical disease identifier, cross-references to Orphanet and OMIM, `is_a` hierarchy
- **Note**: the `mondo-rare` subset (~33 MB) is used instead of the full release (~240 MB). It covers exactly the project's domain. The consequence is that non-rare diseases are not resolvable, which is intended.
- **File**: `mondo-rare.obo`

### Orphanet / Orphadata
- **License**: CC BY 4.0, declared inside the file itself
- **Role**: curated disease-gene associations, with the association **type** and validation PMIDs
- **Why it is the right source**: it explicitly distinguishes `Disease-causing germline mutation(s) in` from `Modifying germline mutation in` and from `Candidate gene tested in`. Only the first group is accepted as causal. In tuberous sclerosis it is this distinction that keeps out IFNG, which Orphanet annotates as a modifier.
- **Also used for disease mechanism**: Orphanet distinguishes `(loss of function)` from `(gain of function)` within the association type. This is derived automatically for 1,025 diseases resolvable to a Mondo term — see `pipeline/direction.py::orphanet_mechanism`. Where the causal genes of one disease carry conflicting annotations, the result is `unknown`, not a majority vote.
- **File**: `en_product6.xml` (~23 MB)

### Reactome
- **License**: CC0 1.0
- **Role**: gene-pathway membership and the hierarchy between pathways. It is the mechanistic bridge the entire method rests on.
- **Files**: `NCBI2Reactome_All_Levels.txt` (~98 MB, filtered to *Homo sapiens* at load time), `ReactomePathwaysRelation.txt`, `ReactomePathways.txt`

### DGIdb v5
- **License**: the code and the aggregate are open; individual interactions come from upstream sources with heterogeneous licenses
- **Role**: drug-gene interactions, interaction type, regulatory approval status
- **How the heterogeneity is handled**: the `interaction_source_db_name` column is propagated all the way to the report, so the upstream provenance of each individual interaction stays visible to the reader and verifiable under the original source's terms.
- **File**: `dgidb_interactions.tsv` (~12 MB)

### HPO — Human Phenotype Ontology

- **License**: **its own, non-standard** — see the note below
- **Role**: phenotypic similarity between rare diseases, which feeds the phenotype bridge (the second search strategy)
- **Files**: `hp-base.obo` (~12 MB), `phenotype.hpoa` (~36 MB)

> [!IMPORTANT]
> **The HPO license status is not automatically verifiable.**
>
> The ontology declares `dcterms:license` with the value `https://hpo.jax.org/app/license`.
> As of the verification date (2026-09-01) that URL returns **404**, and the OBO
> Foundry registry lists HPO under its own license (`hpo`), not a Creative Commons one.
>
> Unable to verify the exact terms, this project **does not assert them**. The entry
> in `config/sources.yaml` declares them as uncertain, and the same note appears in
> the generated report. Since the tool does not redistribute data, the obligation to
> verify falls on whoever downloads it: **before any commercial use or
> redistribution, verify the current terms with HPO.**

Only annotations with `aspect = P` (phenotypic abnormality) and without a `NOT` qualifier are used. Rows for mode of inheritance and clinical course are excluded: including them would make all autosomal recessive diseases resemble each other regardless of clinical picture.

### openFDA — Drug Labeling API
- **License**: public domain (work of the United States government)
- **Role**: independent confirmation of approval and of labelled indications
- **Status**: queried via API on the final candidates only, not downloaded in bulk

**Why it is genuinely needed.** DGIdb carries an `approved` column, but it is an aggregate of heterogeneous sources and proved unreliable: in the tuberous sclerosis pilot, two of eight candidates marked `approved` have no FDA label at all (one is an experimental mTOR inhibitor never authorized). openFDA makes the discrepancy visible.

The second, less obvious value is that showing **what** a drug is labelled for makes it evident that the hypothesis is off-label. A report stating "indicated for prophylaxis of organ rejection" next to a proposal for another disease tells the reviewer, without explanation, what kind of leap is involved.

> [!NOTE]
> **It does not enter the score, and that is deliberate.** openFDA covers the
> United States. Using it to rank candidates would penalize drugs approved only
> elsewhere, of which there are many in rare diseases: miglustat is authorized by
> the EMA for Niemann-Pick type C, an indication the FDA never granted. A candidate
> is not weaker for having been approved in Brussels rather than Silver Spring, and
> encoding that distinction into a scientific score would build a geographic bias
> into it.
>
> The absence of an FDA label in the report should therefore not be read as "not approved".

### PubMed / NCBI E-utilities
- **License**: bibliographic metadata is freely reusable; **abstract text may be copyrighted**
- **Role**: grounding hypotheses in real literature
- **Policy adopted**:
  - only PMID, title, journal and year are stored
  - abstracts and full text are neither downloaded nor quoted verbatim outside the PMC Open Access subset
  - no scraping beyond the E-utilities, which are the interface NCBI provides for exactly this use
  - the rate limit is respected (3 requests per second without an API key, 10 with one), and responses are cached so the same calls are not repeated

---

## Deliberately excluded sources

Listing these matters as much as listing the included ones: an absent source can look like an oversight, and here it is not.

### DisGeNET — excluded for licensing

Since 2023 DisGeNET has moved to a commercial model. The last fully open release (v7.0, 2020) is distributed under **CC BY-NC-SA 4.0**:

- the **NonCommercial** clause is incompatible with a project meant to be usable by anyone, including companies and academic spin-offs
- the **ShareAlike** clause would propagate to any derived database

**Replaced by**: Orphanet (curated associations, CC BY 4.0), HGNC, and in phase 2 the Open Targets Platform (CC0). For monogenic diseases this combination has better curation than DisGeNET, which is built to also cover weak statistical associations in common diseases.

### KEGG — excluded for licensing

It is the best-known pathway resource, but programmatic access and redistribution are subject to a restrictive license, incompatible with the project's constraints.

**Replaced by**: Reactome (CC0), which for human signalling pathways is curated at least as well and is completely open.

### OMIM (raw data) — excluded for licensing

Redistribution of OMIM data requires registration and is subject to restrictions. Only OMIM **identifiers** are used, as cross-references, never the content.

---

## Sources planned for phase 2

To be integrated after pipeline validation, in this order:

1. **Reactome at the reaction level** — to derive **signed** regulatory relations from data, replacing or feeding the hand-curated annotations in `config/mechanism.yaml`. It is the single most important improvement the project can still receive.
2. ~~**HPO** — phenotypic similarity as a second search strategy~~ — **integrated**, see `pipeline/phenotype.py`
3. **Monarch Initiative KG** — cross-species links and associations from animal models
4. **ChEMBL** (CC BY-SA 3.0) — interaction potency and selectivity, to refine the score beyond a plain "the interaction exists". Note the ShareAlike clause on derivatives.
5. **Open Targets Platform** (CC0) — gene-disease evidence as a cross-check on Orphanet
6. **DrugCentral** (CC BY-SA 4.0) — structured approved indications, richer than openFDA

---

## Adding a source

Every new source must arrive with:

1. an entry in `config/sources.yaml` declaring **the license and the license URL**, not just the download URL
2. a parser in `src/repurposerd/sources/parsers.py` with a test in `tests/test_parsers.py` pinning its format
3. propagation of `Provenance` all the way to the report: a fact that cannot say where it came from does not enter the evidence bundle
4. if the license has NC or SA clauses, an explicit note on what that implies for derivatives

A technically useful source with an incompatible license goes in the "excluded" section, with the reason. The project prefers to be less complete than less clear.
