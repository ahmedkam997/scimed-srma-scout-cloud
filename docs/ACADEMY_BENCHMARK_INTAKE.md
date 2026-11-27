# Academy temporal opportunity benchmark intake

The benchmark starts empty at
[benchmarks/academy/benchmark.json](../benchmarks/academy/benchmark.json).
Nominate development cases in the
[separate public queue](../benchmarks/academy/nominations.json). Admit a minimum of 30
independently adjudicated test cases covering updates, novel opportunities
and negative controls. An opportunity label describes the scientific
question at its historical index date. A later publication can help
ascertain the label and can establish a completed review lineage.

- For an update, document the exact baseline PICO and what materially
  changed by the index date. Reconcile later review inclusion with the
  trial-family and endpoint ledger.
- For a novel opportunity, verify adequate eligible evidence at the index
  date and audit overlapping reviews and registrations using actual
  source coverage and cutoffs.
- For a negative control, document a specific evidenced failure such as
  an already up-to-date equivalent synthesis, incompatible outcomes, or
  too few confirmed independent trials. Missing labels, failed searches,
  and unresolved evidence stay pending.

## Case manifest

The top-level object has `schema: SCIMED_ACADEMY_BENCHMARK_V1` and a
`cases` array. Each case requires the following fields.

| Field | Contents |
| --- | --- |
| `case_id` | Unique opaque case ID. |
| `topic_family_id` | Canonical ID shared by closely related review questions. Reconcile synonyms before assigning splits. |
| `split` | `train`, `development`, or `test`. |
| `opportunity` | `UPDATE`, `NOVEL`, or `NEGATIVE`. |
| `index_date` | Historical date at which the question is evaluated as a prediction. |
| `evaluation_date` | Latest date permitted for retrospective reference evidence. |
| `question` | Object with `population`, `intervention`, `comparator`, and `outcome` strings. |
| `evidence` | Source record list, including material negative and uncertain evidence. |
| `reverse_replay` | For updates, a completed baseline and follow-up review pair. |
| `adjudication` | Signed reconciliation bundle, required for admission. |

Each evidence row has a case-local `record_id`, a `kind` of `STUDY`,
`REVIEW`, `REGISTRATION`, or `OTHER`, a public HTTPS `source_url`,
an evidence `locator`, and `available_on`. Dates require source-backed
day-level precision in YYYY-MM-DD. Keep cases with unresolved dates in
the nomination queue.

Provide an `identifiers` object with lists of applicable `pmid`, `doi`,
`registration_ids`, and `trial_family_ids`. Study rows require a canonical
trial-family ID. Use the same ID across primary reports, registry variants,
and secondary analyses of the same randomized population. Record conflicting
registrations as evidence and resolve them before admission. Keep canonical
PMIDs as strings. Reconcile external corpus study and question identities
before putting any intersecting examples into training.

For an update, `reverse_replay` specifies `baseline_review_id`,
`followup_review_id`, `baseline_search_through`, `followup_search_through`,
and nonempty `added_report_ids`. The baseline review must be publicly
available by the prediction date. The completed follow-up appears later
and uses a later search cutoff. Added study reports must date after the
baseline search, within the follow-up search horizon and by the prediction
date. Reconcile the reviews' inclusion tables and trial families before
signing. Repeated publications can support an existing family. A new report
of a pre-baseline family cannot establish a new trial in this benchmark.

`model_observation(case)` exposes the prespecified question and pre-index
reference pointers. Freeze prediction inputs to contemporaneous sources.
Retrospective publications, rationale and labels stay in the held-out
reference manifest. A known-at-index citation can still point to a
subsequently updated page, so use archived versions when extracting
historical features.

## Independent review and admission

Two reviewers independently screen the full texts and sources and record
their decision, evidence and reasons. Reconcile disagreements without
revealing model scores and preserve the independent review records
privately. An operator verifies the reviewers and provisions distinct
trusted keys. The reconciled submission must contain:

- `schema` equal to `SCIMED_ACADEMY_BENCHMARK_V1`.
- `case_id` from the case and `case_sha256` from
  `scripts.academy_benchmark.case_digest(case)`.
- `independent_extraction_and_screening_attested` set by the reviewers
  after the independent checks are completed.
- A nonempty `rationale` and nonempty `rationale_record_ids` drawn from
  the case's evidence IDs.

Store `adjudication` as an object with `submission` and `approvals`.
The two approvals use the repository's trusted HMAC signature format
and bind the exact case payload. The existing operator utility
`scripts/sign_scientific_adjudication.py` signs each private submission.
Keep keys outside the checkout and use a private local reviewer-key JSON
object mapping reviewer IDs to their hexadecimal keys. Automated signature
checks authenticate trusted distinct keys and the bound attestation.
Real independence and source accuracy require the reviewers' work.

Use the same temporal order for input and labeling. The last train
evaluation date precedes the first development prediction date, and the
last development evaluation date precedes the first independent test
prediction date. Any shared normalized report, source URL, trial family,
review family, or registration alias across splits blocks readiness.
Exact label-independent matches to the public nomination topics and
source URLs also block test admission. The check resolves recognized PMID,
DOI and ClinicalTrials.gov URL identifiers. Additional aliases and
previously exposed material require independent inventory and review.

```bash
python -m scripts.academy_benchmark benchmarks/academy/benchmark.json
python -m scripts.academy_benchmark /path/to/private-benchmark.json \
  --reviewer-keys /path/to/private-reviewer-keys.json --require-ready
```

The structural audit can run on the empty public manifest and reports
that benchmark readiness is false. Use the readiness check for the
frozen test manifest. Keep test cases and labels out of development
replay, model selection and tuning. Benchmark admission never grants
first-choice qualification.
