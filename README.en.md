# RepurposeRD

***English** · [Italiano](README.md)*

[![CI](https://github.com/zalaso/RepurposeRD/actions/workflows/ci.yml/badge.svg)](https://github.com/zalaso/RepurposeRD/actions/workflows/ci.yml)
[![License](https://img.shields.io/badge/license-Apache--2.0-blue.svg)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.11%20%7C%203.12%20%7C%203.13-blue.svg)](pyproject.toml)

A generator of **therapeutic repurposing hypotheses** for rare monogenic diseases, based on analysis of biological pathways shared between a disease's causal gene and the targets of already-approved drugs.

**100% local. Open data only. Every claim traceable to a real source.**

> [!WARNING]
> **This tool generates computational research hypotheses, not medical advice.**
> No result produced by RepurposeRD has been validated in vitro, in vivo, or clinically.
> It is not a medical device, not a diagnostic tool, and not a prescriptive tool.
> Every output is intended for review by a qualified researcher.
> See [DISCLAIMER.en.md](DISCLAIMER.en.md).

> [!IMPORTANT]
> **Reports are currently written in Italian.** The documentation is bilingual; the
> tool's output is not yet. An English-speaking researcher can run RepurposeRD and
> read its evidence — gene symbols, PMIDs, drug names, pathway identifiers and
> numeric scores are language-neutral — but the surrounding prose and section
> headings are Italian. See [Language](#language) below.

---

## What it does

Given a rare monogenic disease as input:

1. **Normalizes** the disease to a canonical Mondo identifier
2. **Identifies** the causal gene through Orphanet's curated associations
3. **Expands** to the Reactome pathways containing that gene, and to directly adjacent pathways
4. **Searches** for already-approved drugs acting on genes belonging to those pathways (DGIdb)
5. **Assesses directional coherence**: does the drug oppose the defect, or risk aggravating it?
6. **Anchors** every link to real PubMed literature (PMIDs and metadata only)
7. **Verifies** approval against real FDA labels (openFDA), making visible what the drug is actually authorized for
8. **Ranks** candidates with a deterministic score, decomposed into visible components
9. **Generates** a natural-language explanation with a local model, **validated** against the collected evidence
10. **Produces** a Markdown report designed for human review

## What it does not do, by construction

- Does not train machine-learning models
- Does not perform and does not promise in vitro or clinical validation
- Never uses vocabulary suggesting demonstrated clinical efficacy: the evidence-level vocabulary does not even contain the word "strong"
- Does not use copyrighted or paywalled content
- Does not let the language model retrieve facts: the LLM **writes**, it does not **search**

---

## Architecture in one line

```
                    ┌─ mechanistic branch ─────────────────────────────┐
disease → [Mondo] → │ causal gene → [Orphanet] → pathways → [Reactome] │→ genes
                    └──────────────────────────────────────────────────┘   │
                    ┌─ phenotype bridge ───────────────────────────────┐   │
                   →│ similar diseases → [HPO] → their causal genes    │→ genes
                    └──────────────────────────────────────────────────┘   │
                                                                           ▼
  approved drugs → [DGIdb] → directional coherence → literature → [PubMed]
        → deterministic score → evidence bundle (JSON)
        → local LLM (prose only) → anti-hallucination validator → report
```

**Two search strategies, not one.** The mechanistic branch finds drugs acting on the *same* process the disease disrupts. The phenotype bridge finds those acting on a *consequence* of that process, by way of clinically similar diseases: this is the case for many real repurposings, and it is invisible to the first branch by construction. Candidates arriving through the bridge are flagged as such in the report and penalized in the score, because clinical similarity does not demonstrate a shared mechanism. Disable with `--no-phenotype-bridge`.

The central architectural point is the **evidence bundle**: a JSON object containing all and only the verified facts. The language model receives that and nothing else, with no access to search tools. After generation, a validator extracts every PMID, gene, drug and identifier from the produced text and checks that it appears in the bundle. A fabricated citation thus becomes **a bug detectable by a test**, not a risk to be mitigated through prompting.

---

## Installation

Requires Python 3.11–3.13.

The project has no dependencies containing unsigned native code: **Smart App Control**, enabled by default on recent Windows, blocks that kind of library, and disabling it is not reversible without reinstalling the system. Nobody should have to make that choice to run a research tool.

```bash
git clone https://github.com/zalaso/RepurposeRD.git
cd RepurposeRD
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
```

With [uv](https://github.com/astral-sh/uv), which is the recommended route:

```bash
uv sync --extra dev
```

### Local model (optional but recommended)

RepurposeRD works **even with no LLM at all**: the `template` backend produces a deterministic explanation built from the same evidence. It is not a degraded version — it is the only one that can be *proven* to invent nothing, because it does not generate: it copies structured fields.

For generated prose you need a local model via [Ollama](https://ollama.com):

```bash
ollama pull qwen2.5:7b-instruct
repurposerd run "tuberous sclerosis" --llm-backend ollama
```

Servers compatible with the OpenAI API (LM Studio, llama.cpp's `llama-server`) are also supported via `--llm-backend openai-compatible`.

#### Which model, on which hardware

**The default model is `qwen2.5:7b-instruct`**, and it is the recommended choice for anyone with adequate hardware. There is no automatic fallback to a smaller model: the project uses what you point it at.

Numbers measured on a laptop with no usable GPU (AMD Ryzen 3 2200U, two cores, integrated Vega 3), which is the realistic worst case:

| Model | Time per candidate | Outcome |
|---|---:|---|
| `qwen2.5:7b-instruct` | ~480 s | smoother prose; 3 of 3 validated |
| `qwen2.5:3b-instruct` | ~190 s | 3 of 3 validated; overclaims more often, and more visibly |
| `template` (no LLM) | instant | deterministic and verifiable by construction |

The 7B **works** even on this hardware: it is merely slow. With a discrete GPU the times drop by one or two orders of magnitude, and on a capable machine there is no reason to go below 7B. Larger models (14B, 32B) are usable the same way via `--model`: the backend imposes no size limit.

#### Making a large model practical on long reports

The real obstacle is not model size but report length: forty candidates at 7B on CPU is about six and a half hours, and nobody will wait for that.

```bash
# First 5 candidates narrated by the model, remaining 35 by the deterministic
# generator. Same report, from ~6.5 hours to under one hour.
repurposerd run "Niemann-Pick disease type C" --top 40 \
  --llm-backend ollama --model qwen2.5:7b-instruct --narrate-top 5
```

Nothing verifiable is lost: the deterministic generator copies the same structured fields, and the report states candidate by candidate where the prose came from. A reviewer reads the first few in full and skims the rest.

#### A larger model is not a safer model

Both models tried attempted to overclaim, and the validator caught both. But **they did so differently, and the 7B's way is the more insidious**:

| Model | What it wrote | Why it is a problem |
|---|---|---|
| `qwen2.5:3b` | "the data **confirm that** the hypothesis is coherent and reliable" | asserts; it jars, a reader notices |
| `qwen2.5:7b` | "the mechanism hypothesized for the **efficacy** of sirolimus" | **presupposes**; it sounds like a sentence from a paper |

The second formulation does not assert efficacy: it takes it as given and discusses its mechanism. That is exactly what the [disclaimer](DISCLAIMER.en.md) states must never appear, and it slipped past the first list of forbidden expressions precisely because it is grammatically innocuous.

**Linguistic quality and epistemic reliability do not grow together.**

Both formulations are now regression tests. But the fix that worked was not forbidding more: with the root `efficac` banned and nothing else changed, the 7B stopped passing validation **in every single case**, because the prohibition was not in the instructions it received. And even after adding it to the prompt, it kept writing "the coherence is confirmed."

What worked was **reformulating the fact shown to it**: the bundle used to pass `outcome: "coherent"`, which invited that sentence, and now passes `heuristic assessment: compatible, never experimentally verified`. The label carries its own caveat, and the model no longer has reason to add one. From 0 of 3 to 3 of 3. Details in [docs/PILOT_RESULTS.md](docs/PILOT_RESULTS.md).

The list of forbidden expressions nonetheless remains incomplete by construction: any new model may find an unanticipated formulation. This is why the deterministic generator is not a degraded fallback, and is always available via `--llm-backend template`.

The default timeout is ten minutes per candidate; adjust with `--llm-timeout`.

---

## Usage

```bash
# 0. Check the environment (says what is missing and how to fix it)
repurposerd doctor

# 1. Download the open sources locally (~180 MB, once)
repurposerd fetch

# 2. Build the DuckDB store
repurposerd build

# 3. Generate hypotheses
repurposerd run "Tuberous sclerosis complex" --out out/tsc.md
```

Other useful commands:

```bash
repurposerd doctor                          # check prerequisites, report what is missing
repurposerd sources                         # sources, licenses and download status
repurposerd info                            # store status and configuration digest
repurposerd resolve "Niemann-Pick type C"   # disease -> gene resolution only

repurposerd run MONDO:0001734 --llm-backend template    # with no LLM at all
repurposerd run MONDO:0001734 --no-literature           # without querying PubMed
repurposerd run MONDO:0001734 --no-regulatory           # without FDA confirmation
repurposerd run MONDO:0001734 --no-phenotype-bridge     # mechanistic branch only
repurposerd run MONDO:0001734 --max-bridges 50          # wider phenotype network
repurposerd run MONDO:0001734 --shuffle-control         # negative control
repurposerd run MONDO:0001734 --narrate-top 5           # model on the top 5 only
repurposerd run MONDO:0001734 --llm-timeout 900         # slow CPUs
repurposerd run MONDO:0001734 --bundle-out out/b.json   # save the evidence bundle
```

> [!NOTE]
> The first run on a disease queries PubMed for several hundred candidates and may
> take around ten minutes: NCBI's rate limit is respected, not circumvented.
> Responses are cached, so subsequent runs on the same disease are fast.

---

## Language

The documentation is available in English and Italian. **The generated reports are
currently Italian only**, as are the LLM prompts that produce their prose.

This matters more than it may appear, so it is stated plainly rather than left to
be discovered. What an English-speaking reader can still use directly:

- every identifier (Mondo, ORPHA, Reactome, HGNC symbols, PMIDs, drug names)
- every numeric score and its component breakdown
- the structure of the report, which is stable and documented here

What they cannot: the explanatory prose, the section headings, and the evidence-level
labels, which are Italian words with specific defined meanings.

Making the report language selectable is tracked as the highest-priority item for
international use. It is not merely a matter of translating strings: the
anti-hallucination validator matches forbidden roots (`efficac`, and others) that
are language-specific, and an English report needs its own audited list of
forbidden expressions before it can be trusted. **A translated report with an
untranslated validator would be less safe than no English report at all**, and that
is the reason it has not been done hastily.

---

## The benchmark

With only two pilot cases there was no way to tell whether a change to the weights improved or worsened anything. `config/benchmark.yaml` contains 22 disease-drug pairs with known outcomes, and the command runs them all:

```bash
repurposerd benchmark --out out/benchmark.md          # full, hours on first run
repurposerd benchmark --quick --out out/quick.md      # without PubMed, ~8 minutes
```

No entry was written from memory: every pair was verified against Mondo, Orphanet, DGIdb and PubMed before being admitted, and carries the PMIDs actually returned by the query. Pairs rejected during verification are listed in the file with the reason, because anyone wanting to extend it needs those as much as the included ones.

**The benchmark also contains cases that must fail.** Trientine in Wilson disease is a chelator with no protein target: no method based on shared pathways can find it. A benchmark where everything is findable would reward promiscuity, and raising coverage by making the tool indiscriminate would be a regression disguised as an improvement.

### First-run result

| Metric | Value |
|---|---|
| Found within rank 40 | **17/21** |
| of which **true repurposings** | 7/10 |
| of which on-label drugs | 10/11 |
| Median rank | **2** |
| Expected failures, correctly not found | 1/1 |

One figure worth isolating: **19 of 22 cases ran with no curated mechanism**, hence with the direction of effect always unknown. The ranking held up regardless. What directional curation improves is not recall but **confidence calibration**: without it, the evidence level stays pinned at `limited` even for correct, well-ranked candidates.

> [!NOTE]
> Re-run after disease mechanism began to be derived from Orphanet (digest
> `4c2705204601`): mechanism coverage went from 3 of 22 cases to 7, and **recall did
> not change by a single case**. What changed is the score of candidates at distance
> zero — `cf-ivacaftor` from 0.794 to 0.969. Directional knowledge improves confidence
> calibration, not recall. See [docs/BENCHMARK_BASELINE.md](docs/BENCHMARK_BASELINE.md).

**What it measures and what it does not.** It measures coverage, not precision: an unexpected candidate is not a false positive — it might be a legitimate hypothesis nobody has studied yet. And all 22 cases are already-known repurposings, hence already studied, with abundant literature: the literature component favours them, and the measured coverage is therefore an **optimistic estimate**.

## The negative control

`--shuffle-control` re-runs the pipeline replacing **both** biological inputs with fake data: the causal gene with a random gene, and the phenotype profile with that of a random disease. Everything else stays identical.

Replacing only the gene would have been half a control: the phenotype bridge does not start from the gene but from the clinical picture, and would have kept working on authentic neighbours while claiming to measure what happens with fake data.

If the ranking produced on fake inputs is indistinguishable from the real one, the score is measuring nothing. It is the cheapest way to notice you have built a plausibility generator instead of a tool, and it should be run as part of evaluation, not as a curiosity.

---

## Pilot case: tuberous sclerosis

The primary validation case is **tuberous sclerosis (TSC2, MONDO:0001734)**, chosen because it has a known answer in advance: sirolimus and everolimus inhibit MTOR and are genuinely approved for manifestations of TSC, which they reached precisely through repurposing. TSC2 is a negative regulator of mTORC1, so its loss of function produces hyperactivation: an MTOR inhibitor is directionally coherent.

If the pipeline does not recover sirolimus among the top candidates, the pipeline is broken. Knowing the right answer in advance is what makes a pilot useful.

**Result: succeeded.** Sirolimus, everolimus and temsirolimus occupy the top three positions, with coherent direction and complete provenance.

The second case, **Niemann-Pick disease type C (NPC1, `MONDO:0018982`)**, **fails**, and the failure is documented because it is instructive: miglustat is not recovered, and not because of a badly tuned threshold, but because NPC1 and UGCG share no Reactome pathway at any size. The real link runs through downstream pathophysiology, which a method based on pathway co-membership cannot see by construction.

Both cases, with a full diagnosis of the second, are in [docs/PILOT_RESULTS.md](docs/PILOT_RESULTS.md).

---

## Data sources

The repository **does not redistribute data**. It distributes the ETL code that downloads it onto the user's machine, recording for each source its license, version, access date and checksum in `data/raw/manifest.json`.

| Source | Role | License |
|---|---|---|
| [HGNC](https://www.genenames.org/) | gene nomenclature, symbol → Entrez mapping | CC0 1.0 |
| [Mondo](https://mondo.monarchinitiative.org/) | canonical disease identifier | CC BY 4.0 |
| [Orphanet](https://www.orphadata.com/) | curated causal gene per rare disease | CC BY 4.0 |
| [Reactome](https://reactome.org/) | pathways and their hierarchy | CC0 1.0 |
| [DGIdb v5](https://dgidb.org/) | drug-gene interactions, approval status | see note |
| [HPO](https://hpo.jax.org/) | phenotypic similarity between rare diseases | own license, see note |
| [openFDA](https://open.fda.gov/) | independent confirmation of approval | public domain |
| [PubMed](https://pubmed.ncbi.nlm.nih.gov/) | grounding in real literature | see note |

Details, rationale and **deliberately excluded sources** (DisGeNET, KEGG, raw OMIM) in [DATA_SOURCES.en.md](DATA_SOURCES.en.md).

---

## Known limitations

Listed in full in [docs/LIMITATIONS.en.md](docs/LIMITATIONS.en.md). The ones that matter most:

1. **The method does not see downstream pathophysiology.** It captures cases where the drug acts on the *same* disrupted process, not those where it acts on a *consequence* of that process. The Niemann-Pick pilot demonstrates this, and no amount of tuning resolves it.
2. **The direction of effect is only partly known.** Disease mechanism (loss or gain of function) is derived from Orphanet, which declares it for 1,025 diseases. But the *sign* of the relation between causal gene and drug target remains hand-curated and covers three edges: without it, a candidate one or two steps away stays `unknown` even when the mechanism is known, and `unknown` lowers the score.
3. **Pathway co-membership is not a mechanism.** It is an indication of functional proximity. The pathway-size filter and the directional penalty limit the damage; they do not eliminate it.
4. **Literature counts measure attention, not efficacy.** A heavily studied pairing may be heavily studied because it has been repeatedly refuted.

---

## Contributing

See [CONTRIBUTING.en.md](CONTRIBUTING.en.md). In short: `ruff check`, `pytest`, and every new data source must arrive with its license declared in `config/sources.yaml` and its provenance propagated all the way to the report.

## License

Code: [Apache-2.0](LICENSE). Apache-2.0's explicit patent grant lowers the friction for contributors working from a company or a technology-transfer office, which in a biomedical context is not a detail.

**Data** remains subject to the licenses of the respective sources, which are not all permissive. See [DATA_SOURCES.en.md](DATA_SOURCES.en.md).
