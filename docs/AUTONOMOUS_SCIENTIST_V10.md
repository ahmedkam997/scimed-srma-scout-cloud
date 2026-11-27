# Autonomous Scientist V6–V10: implementation and scientific release boundary

Development-only integration of the existing scientific verification engine,
Research Academy, V2 recovery worker, and source adapters. No scientific
qualification threshold has been changed.

## Evidence-based design
- Cochrane Handbook chapter IV: https://www.cochrane.org/authors/handbooks-and-manuals/handbook/current/chapter-iv
- Garner et al. consensus on updating reviews: https://doi.org/10.1136/bmj.i3507
- Cochrane Handbook chapter 10: https://www.cochrane.org/authors/handbooks-and-manuals/handbook/current/chapter-10
- PRISMA-S: https://doi.org/10.1186/s13643-020-01542-z
- LEADS: https://doi.org/10.1038/s41467-025-62058-5
- SYNERGY: https://github.com/asreview/synergy-dataset
- Least privilege: https://docs.github.com/en/actions/reference/security/secure-use

## V6 novelty and information gain
Retain all possible reviews and registrations (including unclassified
records), preserve actual Methods cutoff cues, and carry full-text source
fingerprints into the evidence snapshot. The private operator path uses
the existing signed V2 evaluator and published common-effect reconstruction.
Report descriptive variance reduction and inverse-variance ratio only as
supplements, not replacements for clinical effect-change gates. Sparse
events, incompatible outcomes, other models, and unknown scope remain pending.
A publication date or new report is not proof of novelty or independent
new trial evidence.

## V7 improvement
Use bounded alternative PubMed/Europe PMC exact-ID retrieval, preserving
source identity, missing IDs, retry counts and both route outcomes.
Rotate registry sources and preserve unpersisted inventory counts.
Reuse V2 adaptive ordering and Academy development comparisons. The
shared pinned PROSPERO installer builds the known patched adapter.
Do not execute untrusted model-generated code in the public worker or
give a coding agent repository-write privileges. General autonomous
source-code repair via OpenCode is not implemented; requires an isolated
proposal/test workflow with separate credentials and review.

## V8 independent evaluation
scimed_independent_evaluation.py scores only an admitted independently
signed 30+ case manifest and signed frozen predictions. Exact test-case
inventory, model revision, observation and prediction digests are checked.
Report sensitivity, false-positive fraction, abstentions and Wilson
intervals. No claim of full validation from this triage scoring. Current
manifest contains 0 admitted cases. The 30 public development nominations
are exposed, not independent test data. Test keys and oracle predictions in
synthetic controls establish software behavior only.

## V9 private review
Download source-evidence.json from a packet cycle to an operator-owned
private directory. Never commit keys, approval bundles or private full texts.
Commands, from the tested development checkout:

    python -m scripts.scimed_private_review import-packet source-evidence.json candidate.sqlite --output packet.json
    python -m scripts.scimed_private_review recover candidate.sqlite RCT-... --seconds 300 --output recovered-packet.json
    python -m scripts.scimed_private_review adjudicate candidate.sqlite RCT-... --output decision.json

Import refuses an existing ledger, definitive public coverage, and snapshot
mismatch. Recovery uses the original strict seven-RCT engine without an AI
provider or verifier. Repeat until actual search logs and evidence are
adequate; then independently review the new snapshot. Two real independent
reviewers must use the existing signing utility and operator-protected
trusted directory/key-file configuration. Changed evidence invalidates the
approval. HMAC authenticates keys, not independent human identity.

## V10 orchestration
12-slot pattern: discovery, families, competitors, packet, discovery,
families, registry, learning, competitors, packet, diagnostic, validation.
Absent due work falls back to discovery. Registry/packet stages are bounded
and never assert definitive coverage. Candidate and inventory caps, finite
artifact retention and network failures are exposed rather than concealed.
The 30-minute scheduler can pin a tested revision after successful CI.
Do not merge the development engine into production.

## Recorded validation
Run 45971044843: real renal-denervation/sham provisional packet, 20
primary report cues and 20 possible competitor records, 2 full-text calls,
snapshot equality on import, private gate blocks missing reviewer keys.
Run 45971393316: PROSPERO CLI build successful but actual query ACCESS_FAILED;
OSF 1 record; ClinicalTrials.gov 242 returned, 20 retained and 222 explicitly
pending. Run 45971466186: 76 targeted tests, real packet roundtrip and
registry audits; full CI 603 passed, 2 skipped (45971466221).
No clinical eligibility, seven usable trials, complete novelty or actual
first-choice dossier established. No paid API or GPU used.
The later PROSPERO alternate-anchor recovery must be checked in its own CI.

## Remaining genuine release blockers
- Exhaustive systematic source search and independently verified scope.
- Complete eligible full texts, independent populations and outcome data.
- Clinical and statistical value on actual candidate, signed judgments.
- 30+ private independently adjudicated test cases and frozen predictions;
  prospective end-to-end evaluation.
- Two independent real reviewers, protected key provisioning and
  adjudication transport. No public scheduler is permitted to generate them.
- Long-term durable evidence archive beyond finite Actions artifact retention;
  public worker remains bounded. General-purpose automatic software patches
  and independent release validation not completed.

Do not report a fully qualified FIRST-CHOICE until the existing trusted
scientific gate actually passes on real evidence.
