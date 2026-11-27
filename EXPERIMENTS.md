# Development experiments

- The Phase 3 nine-seed-result audit and source diagnostics are in
  [PHASE3_REPLAY_RESULTS.json](benchmarks/PHASE3_REPLAY_RESULTS.json).
- Reproduced the hosted SYNERGY+ Muthu workflow commands locally on CPU. The
  filtered corpus has 923 records and 20 positive labels. At seed 42 the
  ASReview TF-IDF SVM profile reached 95% observed recall at 700 decisions
  and the naive Bayes profile at 593 decisions. Each recovered 20/20 by the
  end. WSS@95 was 0.192 and 0.308, respectively. This is one development
  corpus and seed; no model selected for deployment.
- Live historical replay recorded an unresolved local PubMed search. Hosted
  replays were triggered by the development push. [Historical replay](https://github.com/ahmedkam997/scimed-srma-scout-cloud/actions/runs/45891090776)
  [Aviary/LDP](https://github.com/ahmedkam997/scimed-srma-scout-cloud/actions/runs/45891090634)
  [External data](https://github.com/ahmedkam997/scimed-srma-scout-cloud/actions/runs/45891090998)

- Hosted broad follow-up run `45891785512` recovered all six bounded
  routes but included reviews and unrelated interventions in trial hits.
  The first title-focused run `45891962418` retained those artifacts and
  failed because both TAVR routes were partial. A premature commit queued
  one repeat of the broad search before the title-filter code was applied.
  The corrected title-focused and search-method run `45892078476`
  succeeded with six positive bounded routes and no translation warning.
  [Corrected hosted run](https://github.com/ahmedkam997/scimed-srma-scout-cloud/actions/runs/45892078476)

- Full-text/family audit `45892325002` failed before artifact creation
  when checkout followed artifact download. Reordering the steps yielded
  artifact `15152072119` on run `45892409004` and recovered both family
  ledgers. The rerun exited nonzero because no Methods cutoffs resolved.
  Ten resolver and family tests passed locally, as did a synthetic EFetch
  linkage check. [Audit rerun](https://github.com/ahmedkam997/scimed-srma-scout-cloud/actions/runs/45892409004)

- Reconciled Europe PMC and PubMed by explicit PMID, rejecting conflicting
  identifiers within a source record. Added opt-in PMC OAI Methods retrieval
  and preserved exact DOI publisher leads. Thirty targeted tests passed;
  a synthetic OAI fixture recovered a dated Methods statement and rejected
  an identity mismatch.
- The outcome inventory records only explicit abstract count and ratio
  cues, preserving their original context in the artifact. It keeps
  independent usable trial counts unknown.

- Reused the completed alternate rotation artifact for a targeted renal
  denervation trial-family audit. The workflow restricts the competing
  review query to renal denervation, sham and synthesis terminology, samples
  six review hits, and preserves missing Methods and family uncertainty.
  [Renal triage run](https://github.com/ahmedkam997/scimed-srma-scout-cloud/actions/runs/45893203803)

- Exact-PMID RDN-CKD audit `45893689730` recovered the abstract but exited
  nonzero because no registration identifier was observed in source
  metadata. The alternate lookup queries the trial acronym and clinical
  scope in ClinicalTrials.gov and PubMed. Synthetic checks covered exact ID,
  mismatch, and unverified search candidates. [Registry recovery run](https://github.com/ahmedkam997/scimed-srma-scout-cloud/actions/runs/45893775017)

- The alternate cardiology audit saved artifact `15152293472` on
  run `45894079291`. Both bounded review searches responded and only
  one of eight sampled Methods dates resolved. The workflow preserved
  the artifact and exited nonzero. GitHub's public annotation limit
  hid the trial-family rows, so recovery run `45894258451` reads the
  preserved artifact without repeating source requests.

- Narrowed the alternate comparison recovery to AF with heart failure
  and sacubitril/valsartan versus enalapril with reduced EF. The AF
  publication date window starts on 1 February 2026 to cover the
  ambiguity within the comparator review's reported search month.
  The search is a bounded screen, so any date or comparator match
  requires verification against original trial methods.
  [Narrow follow-up](https://github.com/ahmedkam997/scimed-srma-scout-cloud/actions/runs/45894434834)

- Academy CPU screening paired two seeds on the same filtered SYNERGY+
  Muthu corpus, with one oracle positive and one oracle negative per
  seed. Naive Bayes reached 95% reference recall after 590 and 602
  decisions; SVM required 699 and 703. Expected random ordering
  required 836 decisions. These are in-corpus development simulations,
  with all 20 corpus positives eventually found in each run.
  [Paired CPU results](benchmarks/academy/screening-development.json)

- Imported and checksum-verified a completed original/update review
  pair from the Alharbi and Stevenson public corpus. Cochrane CD000160
  (patch angioplasty versus primary closure for carotid endarterectomy)
  has original and updated publications dated 17 May 1996 and 8 July
  2009. The imported reference lists have six original included reports
  and one report newly listed in the update. The hosted comparison uses
  equal budgets for a population-only search and explicit comparison.
  The publication-date window is a proxy. Actual review search
  cutoffs, new independent participants and usability are unresolved.
  [Pinned review update corpus](https://github.com/Amal-Alharbi/Systematic_Reviews_Update/tree/35a78b615d9c9dbdd889c55a61e5032b3cc309c6)

### Hosted Academy development results

The initial Academy run passed and reproduced the paired screening
results. PubMed retrieved all nine report controls. Explicit registry
linkage recovered four of six known within-family report pairs, with
zero false links across the 30 known cross-family pairs. The
singleton baseline recovered none. Eight of nine reports had the
expected registry link. This is a linkage proxy.

On four primary outcome controls, the first-ratio baseline and all
explicit ratio cues each matched all four named reference contrasts.
The baseline proposed four cues and all-ratio extraction proposed
11. Neither confirms endpoint direction or usability. The lexical
and hybrid BM25 competitor methods each placed zero known cardiology
references and one known surgery reference in the top five. Some
reference reviews were absent from the retrieved inventory. No
ranking or extraction expansion is promoted on this evidence.

The 60-record statin replay found two of 12 known reports with the
single-query and date-stratified routes, and three with the dual
route. Both bounded carotid strategies missed the one update-labeled
report. An exact, post-scoring PMID membership check established that
the 1998 report matched both queries and describes long-term follow-up.
The miss concerns bounded selection and ranking in this run. The
retrieval label does not establish a new independent trial.
[Hosted Academy run](https://github.com/ahmedkam997/scimed-srma-scout-cloud/actions/runs/45956921809)
[Post-scoring diagnostics](https://github.com/ahmedkam997/scimed-srma-scout-cloud/actions/runs/45957258604)
[Carotid follow-up PMID 9510277](https://pubmed.ncbi.nlm.nih.gov/9510277/)
