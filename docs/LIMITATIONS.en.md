# Known limitations

***English** · [Italiano](LIMITATIONS.md)*

This document is written to be read **before** trusting a report, not after. It lists what the method cannot do, including weaknesses that have no solution yet.

---

## 1. Pathway co-membership is not a mechanism

The tool's premise is that two genes annotated in the same Reactome pathway are functionally close, and that a drug acting on one may influence the process disrupted by the other.

It is a reasonable heuristic, and it is also the reasoning that led to real repurposings. But a pathway is a curated description of a biological process, not a circuit with a defined causal topology. Two genes can appear in the same pathway and never interact, act in different cellular compartments, or be expressed in different tissues.

**What mitigates the problem**: the cap on pathway size (`max_pathway_size`, default 200), the distance (hop) penalty, and the directional coherence component.
**What remains**: none of that verifies that the two genes actually interact in the context of the disease.

---

## 1-bis. The method does not see downstream pathophysiology

This emerged from the Niemann-Pick type C pilot (see `docs/PILOT_RESULTS.md`), and it is the most important limitation discovered by running the pilot rather than by reasoning about it.

Miglustat is a real, documented repurposing in NPC: it inhibits UGCG, reducing glucosylceramide synthesis. The tool **does not find it**, and not because of a too-narrow threshold: **NPC1 and UGCG share no Reactome pathway, at any size**. In Reactome, NPC1 sits in the lipoprotein transport branch and UGCG in the sphingolipid metabolism branch, and the two branches do not meet in any annotated unit.

The real link is not pathway co-membership: it is downstream pathophysiology. The cholesterol transport defect causes a **secondary** accumulation of sphingolipids, and the drug acts on that.

**Consequence**: the method captures cases where the drug acts on the **same disrupted process**, and not those where it acts on a **consequence** of that process. Tuberous sclerosis is of the first kind, Niemann-Pick C of the second. No parameter tuning changes this.

**What makes the problem worse**: the tool gives no signal that it is failing. In the NPC case it produces ten plausible-looking candidates, none of which is the right one. A full list is not evidence of success.

**Status**: partially mitigated by the **phenotype bridge** (see limitation 1-ter). On Niemann-Pick the bridge does reach UGCG, miglustat's target, by way of SMPD1 (Niemann-Pick type A). The blind spot nonetheless remains real whenever no phenotypically similar disease leads to the right target.

---

## 1-ter. The phenotype bridge is low-precision, by nature

The phenotype branch takes the causal genes of clinically similar diseases and uses them as an additional entry point. It exists to reach what the pathway branch cannot see, and on Niemann-Pick it works: UGCG is reached via SMPD1, the causal gene of Niemann-Pick type A.

But the price is high and should be stated:

- **Clinical similarity is not mechanistic kinship.** Hepatosplenomegaly and ataxia are common to many lysosomal storage diseases for mutually different reasons. Two diseases can resemble each other by symptomatic convergence while sharing nothing at the molecular level.
- **The branch enormously widens the search space.** On Niemann-Pick type C, 30 bridge diseases add about 2,100 genes to the direct branch's 75, and approved drug-gene interactions go from a few hundred to over five thousand. Almost all of that material is noise.
- **The threshold on the number of bridges is a compromise, not an optimum.** Measured: Gaucher disease, which carries the known repurposing for NPC, sits around the thirty-fifth position by similarity. No metric among those evaluated (IC-weighted Jaccard, asymmetric coverage, geometric mean) brings it into the top ten: NPC clinically resembles many diseases, and Gaucher is one of them.
- **The metric was not chosen by looking at the desired result.** The asymmetric variant would have raised Gaucher, but it puts generic, over-annotated syndromes on top, which is a known artefact. The weighted Jaccard was kept because it is symmetric and standard, not because it favoured the pilot case.

**How it is mitigated**: the `route_directness` component explicitly penalizes bridge candidates in proportion to their similarity (typically 0.15–0.35 against 1.0 for direct ones), and the report flags them one by one. `--no-phenotype-bridge` disables the branch for anyone wanting only the mechanistic path.

---

## 1-quater. The literature pre-selection can still lose candidates

PubMed is queried only on a selection of candidates, because querying a free public API for fifteen hundred entries would be an abuse. But the selection happens with a score that does not yet contain the literature component.

The defect was serious and measured: with a fixed selection of the top forty, miglustat — at preliminary rank 253 with 0.391, against 0.467 for the fortieth — was excluded **before** it could show the one piece of evidence that distinguishes it.

**Fixed** with a self-adjusting criterion: the selection includes every candidate within the omitted component's maximum weight (0.10) of the threshold. No excluded candidate can therefore overtake it.

**What remains**: a hard cap (`literature_shortlist_cap`, 400) to contain the cost. When that cap bites, the guarantee no longer holds. The tool states this on screen, but a truncated run may have lost legitimate candidates.

---

## 2. The direction of effect is only partly known

Directional assessment requires two ingredients: the **disease mechanism** (loss or gain of function) and the **sign of the relation** between causal gene and drug target. The status of the two is very different.

**Disease mechanism is largely solved.** Orphanet declares it explicitly in the gene-disease association type, and it is derived automatically for **1,025 diseases** resolvable to a Mondo term — against the 2 that were hand-curated. It stays `unknown` where not even Orphanet declares it, which is the majority of entries, and where the causal genes of the same disease carry conflicting annotations: in that case no majority is taken, the uncertainty is declared.

**The sign of the relation is still entirely by hand**, and covers three edges. No phase-1 source provides it: Reactome contains it at the reaction level, but the gene-pathway membership file used here does not expose it.

**What this means in practice**: for a candidate at distance zero — the drug acts on the causal gene itself — disease mechanism alone suffices, because identity counts as a positive edge. For a candidate one or two steps away the sign is also needed, and without it the direction stays unknown even when the mechanism is known.

**What it means, measured on the benchmark.** Before the derivation from Orphanet, only **3 of 22 cases** had a mechanism; now there are 7. But the benchmark already returned 17/21 found and a median rank of 2 **when there were 3**.

This **refutes** a claim that previously appeared here, according to which the tool would work at its documented capability only on tuberous sclerosis. That is not so, and the distinction matters:

- **The ranking holds up without the curated layer.** It is pathway proximity, source support and literature that carry the expected drug to the top. Seven of ten repurposings are found with unknown direction.
- **The evidence level does not.** With direction `unknown`, the cap pins it at `limited`, so for 19 of 22 cases the declared confidence is **systematically underestimated**. A correct, well-ranked candidate is presented to the reader as weaker than it is.

**So directional curation improves confidence calibration, not recall.** That is an important improvement — an always-cautious evidence level is nearly as useless as an always-optimistic one — but it is not the prerequisite it appeared to be before being measured.

**How it gets solved**: derive signed relations from Reactome's reaction-level regulation data.

---

## 3. The negative control is weaker than it looks

`--shuffle-control` replaces the causal gene with a random one and leaves the rest identical. In tests across three seeds, control candidates top out at scores of 0.33–0.53 with direction always `not determinable`, against 0.758 and direction `coherent` for the real case.

The control replaces **both** biological inputs: the causal gene and the phenotype profile feeding the bridge. In an earlier version the bridge was simply disabled during the control, which left half the pipeline unverified; feeding it the real profile, on the other hand, would have given it authentic neighbours — an advantage the control is not entitled to.

**A limitation nonetheless remains**: the random gene has, by construction, no curated relation in `mechanism.yaml`, so it cannot earn directional coherence points. The comparison partly measures "curated disease versus uncurated disease", not only "real biology versus random biology". A stricter control would require automatically derived signed edges, and therefore falls under limitation 2.

---

## 4. Literature counts measure attention, not efficacy

A drug-disease pairing heavily represented in the literature may be so because it is promising, or because it was studied and repeatedly refuted. The count does not distinguish the two, and the tool does not read abstracts.

There is also a structural bias: old, widely used, heavily studied drugs accumulate articles on any topic. This is why the literature component has the lowest weight (0.10) and uses a logarithmic scale with saturation.

---

## 5. The sources are incomplete and disagree with one another

- **DGIdb** aggregates dozens of upstream databases with different inclusion criteria. An interaction reported by a single source may derive from a single in vitro experiment at high concentration.
- **DGIdb's `approved` column is unreliable, and this is now measured.** In the tuberous sclerosis pilot, two of eight candidates marked `approved` have no FDA label: one of them is an mTOR inhibitor that remained experimental. openFDA confirmation makes the discrepancy visible but **does not resolve it**: it does not filter those candidates, it only flags them, because the absence of an FDA label can also mean approval is non-US.
- Some interactions are plainly noisy. In the pilot case, `ASPIRIN → TSC1` appears in sixth place: it is almost certainly an aggregation artefact, not a real pharmacological relation. The tool marks it `direction not determinable`, but does not exclude it.
- **Orphanet** is carefully curated but not exhaustive, and often places the gene association on clinical subtypes rather than on the parent term. The tool descends the Mondo hierarchy to compensate, but this descent can aggregate subtypes with different causal genes.
- **Reactome** annotates well-studied signalling pathways better. A little-studied gene has fewer pathways, and hence fewer candidates: an absence of results also reflects an absence of annotation, not only an absence of biology.

---

## 6. The score ranks, it does not quantify

The score is a weighted sum of components declared in `config/scoring.yaml`. The weights are argued design choices, not estimates calibrated on data.

**A score of 0.75 does not mean "75% probability of success".** It means no probability at all. It means only that this candidate precedes those with a lower score, according to those weights. Changing the weights changes the order, and this is why the configuration digest appears in every report: two reports with different digests are not comparable.

---

## 7. No learned model, by choice and by necessity

The project excludes training models. Besides being a declared constraint, it is also the correct choice: no credible training set exists. Documented successful repurposings number a few dozen, heavily skewed toward what someone already had reason to study. A model trained on those would mostly learn to recognize a drug's popularity.

A score with declared weights is worse than a good model, which is not available here, and better than a bad model that would look more authoritative than it is.

---

## 8. Limitations of the language layer

- The anti-hallucination validator recognizes PMIDs, structured identifiers, gene symbols and drug names. It **cannot** verify that a claim in prose is a correct logical consequence of the facts provided: it can say the model cited nothing nonexistent, not that it reasoned well.
- The list of forbidden expressions remains **incomplete by construction**. It has been extended twice, both times after watching a real model get around it unintentionally:
  - `qwen2.5:3b` wrote "the data **confirm that** the hypothesis is coherent and reliable". The list contained the exact phrase and did not survive inflection.
  - `qwen2.5:7b` wrote "the mechanism hypothesized for the **efficacy** of sirolimus". The list covered "demonstrated efficacy" and "is effective", but not the **nominal** use, which is the most insidious formulation: it does not assert efficacy, it presupposes it.

  Both cases are now regression tests, but the lesson is that **any new model may find an unanticipated formulation**. Falling back to the deterministic generator limits the damage; it does not eliminate it.

- **Large models are not immune, they are more dangerous.** The 7B overclaims less often than the 3B, but when it does it produces smoother prose and is therefore easier to absorb without friction. Linguistic quality and epistemic reliability do not grow together.
- The deterministic generator does not have this problem, because it does not generate: it copies structured fields.

---

## 9. Coverage limitations

- The **rare** subset of Mondo is loaded: non-rare diseases are not resolvable. This is intended.
- **Monogenic** diseases are handled. In a polygenic disease the very concept of "causal gene" does not hold, and the tool does not check for this: if Orphanet reports multiple causal genes, it uses them all.
- Human data only. Evidence from model organisms is ignored in phase 1.
- No model of pharmacokinetics, bioavailability or blood-brain barrier penetration. A directionally perfect candidate can be entirely useless because it does not reach the affected tissue. This dimension is **completely absent** from the score.
- **Reports are generated in Italian only.** The anti-overclaiming safeguards are built on Italian word roots, so an English report requires its own audited list of forbidden expressions, not a translation of strings. This is a real limitation on international use, and it is listed here rather than in a roadmap because it affects who can use the tool today.

---

## 10. The benchmark is an optimistic estimate

`config/benchmark.yaml` contains 22 pairs with known outcomes, and the numbers it produces should be read knowing what distorts them:

- **Circularity with the literature.** All cases are already-known, already-studied repurposings. The `literature_support` component rewards precisely the pairings already studied, so it favours them by construction. On a pairing nobody has yet examined the tool will be appreciably worse, and the benchmark neither measures this nor can measure it.
- **It measures coverage, not precision.** An unexpected candidate is not a false positive: it might be a legitimate hypothesis. There is no way to measure precision without experimental validation, which is outside the tool's scope.
- **Twenty-two cases are few** for distinguishing a real improvement from noise. A difference of one or two cases between two configurations is not significant.
- **Case selection.** These are the repurposings someone had reason to study and that ended up in the literature. Failed repurposings, and those never attempted, are not represented.

The benchmark serves to **compare two configurations with each other**, not to declare that the tool works.

---

## How to report a limitation not listed here

Open an issue. A documented limitation is worth more than a badly resolved one: the purpose of this tool is to help a researcher evaluate a hypothesis, and a researcher who knows the tool's limits is in a better position than one who trusts it.
