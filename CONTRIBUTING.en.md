# Contributing to RepurposeRD

***English** · [Italiano](CONTRIBUTING.md)*

## First of all: the principle that holds the project up

**Every claim must be traceable to a real source, and every output must be honest about its own degree of uncertainty.**

A contribution that improves results while weakening traceability or the honesty of outputs is not an improvement. If a change makes the tool more useful but less verifiable, discuss it in an issue before writing it.

## Setup

```bash
git clone https://github.com/zalaso/RepurposeRD.git
cd RepurposeRD
uv sync --frozen --extra dev # or: python -m venv .venv && pip install -e ".[dev]"
repurposerd fetch            # ~180 MB of open sources, once
repurposerd build            # ETL, about 10 seconds
pytest
```

Python 3.11–3.13. On 3.14 some dependencies do not yet have prebuilt wheels.

## Before opening a pull request

```bash
ruff check src tests
ruff format --check src tests
pytest
```

These are the same three checks CI runs, plus a dedicated stage for the non-negotiable rules listed below: a failure there is not a broken test, it is a broken promise.

Tests **do not require the downloaded data**: each builds its own synthetic store or uses minimal samples. A suite depending on the 180 MB of real sources would be slow and would fail on every source update for reasons that are not defects in the code.

## Non-negotiable rules

These have tests guarding them. If you make those fail, the answer is not to update the test.

### 1. No fact without provenance

Every biomedical datum entering the evidence bundle carries a `Provenance` with source, license and access date. If you add a field asserting something about the world, it must know where it came from.

### 2. The language model writes, it does not search

The LLM receives the evidence bundle and nothing else. It has no search tools, no network access, no database access. Giving it retrieval capability would mean giving up the fact that the validator can verify its output, which is the property the tool's credibility rests on.

### 3. The validator does not get weakened

`tests/test_validator.py` describes the central property: a fabricated citation must be a **detectable** condition. If a change lets a nonexistent PMID through, that is a bug with the priority of a security bug.

### 4. Efficacy vocabulary stays forbidden, and the list is never finished

No output may assert or suggest clinical efficacy, nor provide dosing guidance. There is no evidence level called "strong", and none should be added: the report's vocabulary must not offer a word a hasty reader could read as efficacy.

**The list in `validator.py` is incomplete by construction.** It has been extended twice, both times after watching a real model get around it:

| Model | Formulation that escaped | What was missing |
|---|---|---|
| `qwen2.5:3b` | "the data **confirm that** the hypothesis is coherent and reliable" | the list had the exact phrase, but did not survive inflection |
| `qwen2.5:7b` | "the mechanism hypothesized for the **efficacy** of sirolimus" | it covered predicative use, not nominal use |

If you find a new formulation:

1. **add the real text as a regression test**, not a paraphrase. The exact formulation a model actually produced is worth more than ten imagined variants;
2. prefer a regular-expression root over a literal match;
3. check that the deterministic generator still passes validation — if it violated the new patterns, a rejection would have nowhere left to fall back to. There is a test guarding this.

**Do not assume a larger model is a safer model.** The 7B overclaims less often than the 3B, but when it does it produces fluent, plausible prose that a reader absorbs without friction. Linguistic quality and epistemic reliability do not grow together.

### 5. A pre-filter cannot ignore a scoring component

The selection of candidates to query on PubMed uses a score that does not yet contain the literature component. The criterion in `bundle._literature_shortlist` therefore includes every candidate within that component's maximum weight of the threshold.

This is not pedantry: before this criterion existed, miglustat — a real, documented repurposing in Niemann-Pick — was excluded at preliminary rank 253, before it could show the one piece of evidence that distinguished it. Anyone adding a scoring component computed **after** the pre-selection must update that margin, or they reintroduce the same defect.

### 6. `unknown` is not neutral

When the direction of effect cannot be determined, the score goes down. Not knowing is a defect in the evidence, not an absence of a problem. Anyone proposing to treat `unknown` as neutral must explain why a reader should place equal trust in a verified candidate and an unverifiable one.

## Adding a data source

1. An entry in `config/sources.yaml` with **the license and the license URL**, not just the download URL
2. A parser in `src/repurposerd/sources/parsers.py`
3. A test in `tests/test_parsers.py` with a minimal sample reproducing the real file structure
4. A loader in `src/repurposerd/sources/build.py` — for tabular files use DuckDB's native CSV reader, not `executemany` (see the note in `store.bulk_insert`)
5. Propagation of `Provenance` all the way to the report

If the license has NonCommercial or ShareAlike clauses, state in the PR what that implies for derivatives. A useful source with an incompatible license goes in the `excluded` section of `sources.yaml`, with the reason: the project prefers to be less complete than less clear.

## Adding mechanistic annotations

`config/mechanism.yaml` is the hand-curated knowledge layer. Every entry requires:

- `rationale`: why the claim is true, in a form a reviewer can read
- `sources`: at least one PMID or source identifier. **A curated assertion without a source is worth no more than an opinion**, and the project does not accept one.
- `curated_by`: who stands behind it

Note that disease mechanism (loss or gain of function) is now derived automatically from Orphanet for over a thousand diseases. A hand-written `disease_mechanism` entry is needed only where Orphanet does not declare it **and** a solid source is available — adding by hand what Orphanet already says only creates two truths that can diverge.

This file has a disproportionate weight on results (see `docs/LIMITATIONS.en.md`, point 2). PRs touching it receive closer review than PRs touching code.

## The two search strategies

The project has two paths leading to the same scoring stage:

- **Mechanistic branch** (`pipeline/pathways.py`): from the disease's causal gene to genes sharing a Reactome pathway with it.
- **Phenotype bridge** (`pipeline/phenotype.py`): from clinically similar diseases to their causal genes, as an additional entry point.

The second exists because the first has a demonstrated blind spot: if the drug acts on a downstream consequence of the defect rather than on the same process, the two genes share no pathway and no threshold brings them closer.

**Every candidate arriving through the bridge must remain recognizable as such** — in the model (`PathwayLink.bridge`), in the score (`route_directness`), in the prompt and in the report. A change making an indirect hypothesis indistinguishable from a direct one is a regression, however much it improves the ranking.

## Particularly useful contributions

In order of impact:

1. **Signed relations derived from Reactome at the reaction level.** This would replace hand annotations with data, and it is the single most important improvement still possible.
2. **Extending the benchmark** (`config/benchmark.yaml`). Twenty-two cases are few, and this is the contribution worth more than any algorithmic refinement: without a broader benchmark there is no way to demonstrate that a change improves anything.

   Every new entry must pass the same verification as the existing ones, **before** being written:
   - the disease resolves in Mondo from the given string (`repurposerd resolve "..."`)
   - Orphanet attributes causal genes to it
   - the drug exists in DGIdb (watch out for salt forms: `LOSARTAN POTASSIUM`)
   - PubMed has literature on the pair, and the PMIDs in the file are the ones **actually returned**, not remembered

   New `structural_miss` cases are equally welcome: the cases the method cannot find are worth as much as the ones it must find.
3. **A better phenotypic similarity metric.** The current one is an information-content-weighted Jaccard; Resnik's best-match average would be more robust to differences in annotation counts, but requires computing the most informative common ancestor per term pair. Anyone taking this on must evaluate it on **several** cases, not only the already-known ones: tuning the metric on the case you want to work is the fastest way to build a tool that appears to work.
4. **A stricter negative control** than the current one (see `docs/LIMITATIONS.en.md`, point 3).
5. **Pharmacokinetic modelling**, today entirely absent: a directionally perfect candidate can be useless because it does not reach the affected tissue.
6. **Report language selection.** Reports are currently Italian only. This is not a string-translation task: the anti-hallucination validator matches language-specific forbidden roots, and an English report needs its own audited list of forbidden expressions before it can be trusted. A translated report with an untranslated validator would be less safe than no English report at all.

## Style

- Comments explain **why**, not **what**. The code already says what it does.
- Function names describe the effect, not the implementation.
- Error messages tell the user what to do next.
- Tests describe properties, not implementations: they must survive a refactoring.

## License of contributions

By contributing, you agree that your contribution is distributed under Apache-2.0, like the rest of the project.
