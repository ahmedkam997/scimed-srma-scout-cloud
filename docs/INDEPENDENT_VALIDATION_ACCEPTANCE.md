# Independent validation and production acceptance — 2026-11-26

Baseline actual run 45774443950: primary reference retrieval 4/4, comparison
retention 3/4, review retrieval 2/4, still 2/4 after citation expansion.
The two missed PFA reviews are PMID 41651311 and 41714974. Forward citations
for ADVENT failed; the first 12 backward references were mainly nonclinical
background. New title-focused comparator retrieval is a development fix
(not held-out validation), tested with the original pilot and independent
historical review corpora separately. No gate change.

External corpora pinned to source commits:
- CliniFact, https://doi.org/10.1038/s41597-025-04417-x. Registry result vs
  background reference roles are a proxy for article-trial linkage, not
  participant independence. All three splits deduplicated on NCT/PMID;
  contradictory reference labels excluded. Abstract-only, no registry IDs
  injected. Reference label 2 denotes no-info/background, not guaranteed
  true negative linkage. The accuracy numbers are proxy-only.
- SYNERGY, https://github.com/asreview/synergy-dataset. Oud_2018,
  van_Dis_2019 (RCT-focused), Moseng_2024 (review-of-reviews).
  Prespecified broad P/I queries drawn from review eligibility, no included
  IDs in retrieval. Limited 60-hit budgets, historical labels with DOI/PMID
  only; off-corpus hits remain unknown. Precision is within labelled corpus,
  not global. No report-level labels establish independent eligible RCTs.
- Smalheiser and Holt https://doi.org/10.5061/dryad.sqv9s4n5f multi-report
  linkage corpus is a stronger next-stage clustering reference; not yet
  imported. Dual independent full-text adjudication remains required.

Health probe uses actual configured free providers once each (tiny synthetic
JSON request), reports status and only reported quota; no key output.
Historical production job b668c855 had 86 logical calls and 45 failures;
new bounded budgets must be measured in a new real job.

Production canary creates one isolated owner through normal anon insert/RLS,
wakes actual worker, waits for genuine completed report, tests foreign-owner
rejection, honors 10-minute cooldown, calls ordinary resume RPC, verifies
unchanged prior report and worker seed/audit reuse. It does not fabricate a
resume flag, manipulate a user job, or force a failed source. If no machine
recovery is eligible, the result remains inconclusive. Workflow time budget
is bounded. The canary is an isolated production row, not a user's report.
