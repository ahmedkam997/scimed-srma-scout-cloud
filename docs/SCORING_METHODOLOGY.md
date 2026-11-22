# SciMed Review Scout: evidence-anchored discovery scoring (v1)

Status: **exploratory method, not externally validated**. Version: `SCIMED_DISCOVERY_MCDA_V1_EXPLORATORY`.

## Why this changed

Previous versions asked an AI model to return novelty, information gain and
publication-score numbers. Those outputs were subjective ratings, not computed
from study evidence. The current code **overrides** AI-provided numeric novelty,
information-gain and publication-oriented scores with deterministic functions.

This module **does not** perform article full-text screening, quality appraisal,
effect estimation or value-of-information modeling. The scores prioritize
questions for *further review*, not scientific findings about treatment effects.

## 1. Novelty: source-linked overlap index

For each published review and registered protocol, source-text-grounded
assessments classify overlap as:

| Overlap | Numeric severity |
|---|---:|
| NONE | 0.00 |
| LOW | 0.20 |
| MODERATE | 0.50 |
| HIGH | 0.80 |
| ESSENTIALLY_IDENTICAL | 1.00 |

A competitor's overall overlap is scored by a semantic assessor that must
provide source quotations for dimension evidence. When enough dimensions
are available, clinical overlap is an average with pre-set weights:

`S_clinical = Σ(w_d × severity_d) / Σ(w_d)`

Weights: population 0.20, intervention/exposure/index test 0.25,
comparator/reference 0.10, outcomes 0.20, design scope 0.10,
clinical decision 0.15. At least four quoted dimensions are required.
Missing dimensions are never silently set to zero.

`Clinical question novelty = 5 × (1 - max(S_clinical across assessed competitors))`

If fewer than four clinical dimensions have source-verified quotations,
the overlap score is **NOT_ESTIMABLE** and cannot pass the qualification gates.
Overall novelty (with adequate provenance):

`Overall novelty = 5 × (1 - max(overall overlap severity))`

Scores are rounded to two decimals. A HIGH overlap means 1/5. An essentially
identical review means 0/5. If no competitor was found, both novelty indices
are **provisionally 4/5**, not 5/5. The absence of a record is not proof of
absence; search-coverage gates are always checked independently.

Unresolved, low-confidence (<0.80), or unassessed/capped competitor records
result in `NOT_ESTIMABLE`, score 0/5 for gates, and a TYPE-A blocker.
Registration overlap is retained, including unresolved protocol duplication.

These ordinal severities and PICO weights are explicit local design choices,
**not** validated cut points from Cochrane.

## 2. Potential new evidence: bibliographic proxy, not true information gain

For a HIGH or ESSENTIALLY_IDENTICAL previous review, date data permit an
incremental-evidence signal:

`B = max(publication year among relevant related reviews)`

`f_new = number of distinct primary-study candidate records dated after B / number of distinct candidate records`

`Potential gain proxy = 5 × f_new`

This signal uses **publication year** only as a fallback proxy.
Review publication date is **not** its final search date, and a primary record
is not confirmed eligible until screening and full-text verification.

If fewer than 80% of primary-study candidate records have usable years,
or the most relevant review lacks its publication year,
the proxy is `NOT_ESTIMABLE` and is scored zero for qualification.

With **no identified high-overlap prior synthesis**, at least 4 unique primary
records and complete assessment of competitors, set a *provisional* synthesis
gap score of 4/5. This is an opportunity flag, not quantified information gain.

There is **no** formal expected value of information (EVI/EVSI) in this tool.
Those require posterior uncertainty about an effect and a decision utility
model. Never label the bibliographic ratio EVSI or an expected change in
clinical recommendations.

## 3. Research priority index: transparent exploratory MCDA

Weighted sum across five normalized 0–5 criteria:

`Priority index (0–100) = 20 × (0.30N + 0.25I + 0.20C + 0.15F + 0.10P)`

where:
- `N`: source-anchored overall novelty
- `I`: bibliographic potential information gain proxy
- `C`: clinical importance, **AI preliminary judgment requiring clinician review**
- `F`: feasibility, a provisional categorical rating (HIGH=5,
  STRONG MODERATE=4, MODERATE=2.5, LOW=1)
- `P`: publication potential, **AI preliminary judgment requiring editorial review**

This is an **MCDA prioritization index, not a probability of publication**.
The local weights are transparent assumptions pending prospective stakeholder
elicitation and external validation. They are not Cochrane-specified weights.
The scoring trace includes a sensitivity interval created by shifting 10
percentage points between novelty and clinical importance.

The remaining eligibility, source completeness, clinical coherence, fatal
redundancy, and unresolved-methodology checks operate as mandatory
independent gates. An excellent aggregate index **never** overrides a failed gate.

## 4. Interpretation and missing data

- `QUALIFIED` means first-choice *topic for full systematic-review evaluation*,
  not that at least 4 studies have already passed full-text eligibility.
- A zero due to `NOT_ESTIMABLE` means **insufficient information**, not evidence
  of zero novelty or zero utility.
- The app displays each candidate's metrics, score weights, sensitivity range,
  failed gates, and missing information on completed jobs.
- AI judgments of clinical importance, feasibility and editorial interest
  remain unvalidated subjective estimates, clearly marked in the trace.
- Source record identifiers and competitor titles are stored for audit.
- Cutoffs must be registered a priori and revalidated against clinician/expert
  ratings before public research use.

## 5. Future quantitative upgrades when eligible primary studies are established

- **Corrected Covered Area (CCA)** for study overlap across two or more reviews:
  `CCA = (N - r) / (r × c - r)`, where N = total study appearances,
  r = distinct studies, c = reviews. Requires inclusion citation matrices.
  Do not compute using search result counts.
- **Formal expected value of information (EVSI)** after a decision model has
  been parameterized with evidence and uncertainty. Not estimable from
  PubMed titles alone.
- **Validation**: two blinded expert raters per topic, weighted kappa for ordinal
  overlap, ICC or rank correlation for scores, calibration against independent
  expert priority rankings, sensitivity to weight changes and coverage.
- **Decision contexts**: add patient-important outcomes, guideline uncertainty,
  evidence certainty and available synthesis protocols before claiming
  clinical benefit.

## Methodological references

1. Cochrane Handbook, Chapter 2, determining the scope and question:
   https://www.cochrane.org/authors/handbooks-and-manuals/handbook/current/chapter-02
2. Cochrane Handbook, Chapter IV, updating a review:
   https://www.cochrane.org/authors/handbooks-and-manuals/handbook/current/chapter-iv
3. Garner et al., When and how to update systematic reviews: consensus and
   checklist. BMJ 2016. https://www.bmj.com/content/354/bmj.i3507
4. Hennessy and Johnson, Examining Overlap of Included Studies in Meta-Reviews.
   https://pmc.ncbi.nlm.nih.gov/articles/PMC8555740/
5. Cochrane Handbook, Chapter V: Overviews of Reviews (CCA):
   https://www.cochrane.org/authors/handbooks-and-manuals/handbook/current/chapter-v
6. Optimizing Research Impact: A Toolkit for Stakeholder-Driven Prioritization
   of Systematic Review Topics:
   https://pmc.ncbi.nlm.nih.gov/articles/PMC12362723/
7. A common framework of steps and criteria for prioritizing topics for
   evidence syntheses:
   https://pubmed.ncbi.nlm.nih.gov/31846688/
8. Systematizing the Use of Value of Information Analysis in Prioritizing
   Systematic Reviews, AHRQ:
   https://www.ncbi.nlm.nih.gov/sites/books/NBK107294/
9. ISPOR Value of Information Analytical Methods Task Force:
   https://pmc.ncbi.nlm.nih.gov/articles/PMC7373630/
