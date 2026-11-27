# SciMed Research Academy

The Academy is the development and evaluation program for the FIRST-CHOICE
mission. It keeps external proxy benchmarks, historical development replay,
and independent temporal opportunity evaluation distinct. No Academy result
grants scientific qualification. The live cardiology and surgery workflows
continue on the development branch.

## Evidence lanes

| Lane | Inputs and outputs | What is measured |
| --- | --- | --- |
| External data intake | Pinned acquisition manifest, hashes, observed schemas, label and provenance audit | Whether the intended dataset was obtained and is suitable for the claimed use |
| Historical reverse replay | Completed reviews, published additions and the report timeline | Whether a frozen policy surfaces an opportunity using only evidence available at its decision date |
| Component development | Prior source-linked trial and review controls | Retrieval at equal budgets, screening workload, registry linkage, abstract outcome cues, competitor rank and retrospective information-gain proxies |
| Independent benchmark | At least 30 signed cases across UPDATE, NOVEL and NEGATIVE | An independently adjudicated assessment with held-out opportunities and outcomes |
| Live discovery | Cardiology and fixed-anchor general surgery samples | Source-linked leads for verification under the existing mandatory scientific gates |

The independent benchmark starts with nominated opportunities. Two distinct
authorized reviewers must independently assess each case, reconcile their
findings against source evidence, and sign the frozen case packet. A case
without sufficient evidence or signatures stays pending. Preserve absence,
source access failure, and genuine verified absence as different states.
Do not create reviewer identities, keys, or judgments on behalf of humans.

For historical replay, prespecify the exact question and an index date.
Separate the evidence known at that date from later documents and adjudicated
labels. Use the later synthesis to assess what changed and when the change
was knowable. A publication year cannot substitute for a review search
cutoff. Reports from the same study, including interim, protocol, subgroup
and later follow-up reports, use one trial family across splits. Check DOI,
PMID, registry aliases, review family and topic overlap before sealing
distinct training, development and test sets. A registry link is never by
itself evidence of participant independence.

## Initial comparisons

| Task | Simple baseline | Academy development comparison |
| --- | --- | --- |
| Retrieval | One frozen relevance query | Date-stratified retrieval under the same requested record budget |
| Screening | Random workload expectation | Published ASReview TF-IDF SVM and naive Bayes with paired seeds and identical oracle priors |
| Trial-family linkage | Treat each report as separate | Explicit registration and exact report identity |
| Outcome extraction | First explicit ratio cue | All explicit ratio and confidence-interval cues with unresolved entry points kept visible |
| Competitor detection | Lexical rank | Existing lexical and BM25 hybrid on the same retrieved inventory |
| Information gain | Any later publication as a trigger | Independent eligible additions and changed outcome coverage assessed separately |

ASReview performs in-corpus active learning with historical labels as the
simulation oracle. These runs estimate screening workload for the pinned
closed corpus. They do not estimate open-world retrieval recall or justify
dropping unscreened records. The other initial comparisons exercise existing
fixed methods on development controls. Fine-tuning and independent
scientific performance claims require separate, admitted labels. Existing
Aviary/LDP replay tools can orchestrate later development policies. LEADS
model evaluation remains subject to source rights, available weights and
an independent task set. Preserve method, data revision, split, seed,
failure diagnostics and baseline for each experiment.

## Run and recover

- The Academy publishes a dataset audit, benchmark admission report,
  historical replay reports, and per-component development artifacts on
  GitHub Actions. Evidence paths and failure states appear in workflow
  summaries and checkpoint notes. [Academy workflow](../.github/workflows/phase3-research-academy.yml)
- Run the benchmark admission validator with a private reviewer key file
  only in an authorized adjudication environment. Use `--require-ready`
  before treating the held-out benchmark as ready.
- Track discrepancies and corrective actions in the [lesson ledger](../benchmarks/academy/LESSONS.md).
  Advance live candidate verification independently of training and never
  use benchmark success as a substitute for signed scientific adjudication.
