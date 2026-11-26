# Evidence and scope

Use the [scientific verification contract](docs/SCIENTIFIC_VERIFICATION_V2.md)
for signed qualification and the [Phase 3 method inventory](docs/EVIDENCE_AUTOMATION_REUSE_V2_PHASE3.md)
for established alternatives. Keep retrieval, report-level screening,
trial eligibility, repeat publications and quantitative extraction distinct.

Prior [LAAO audit](research_audits/2026-11-24_LAAO_DOAC_ESRD_primary_study_audit.md)
and [CT-FFR ledger](research_audits/2026-11-24_CTFFR_LM_study_eligibility_ledger.md)
contain linked evidence and limitations. Neither provides an eligible
first-choice RCT-only evidence set. The appendectomy historical replay has
ten report references from a larger published review and remains a
development retrieval control. [Published review](https://pmc.ncbi.nlm.nih.gov/articles/PMC5446136/)

## Bounded competitor recovery

The initial hosted PubMed follow-up found direct and near-overlap review
leads for all three topics. None of these citations supplies a verified
review search cutoff from its Methods.

- TAVR/SAVR stroke review in non-high-risk patients and bicuspid aortic
  stenosis review are distinct scope signals; inspect their methods before
  claiming exact overlap or an update gap. [PMID 42985463](https://pubmed.ncbi.nlm.nih.gov/42985463/)
  [PMID 42340809](https://pubmed.ncbi.nlm.nih.gov/42340809/)
- Coronary antiplatelet networks returned PCI bleeding and stent thrombosis
  review leads. A TALOS-AMI age analysis is a report from an existing trial
  family and must not be counted as another trial. [PMID 43022463](https://pubmed.ncbi.nlm.nih.gov/43022463/)
  [PMID 42815042](https://pubmed.ncbi.nlm.nih.gov/42815042/)
- Pediatric uncomplicated appendicitis has a recent direct RCT review lead
  and appendicitis has a living evidence map. The delayed appendectomy
  publication explicitly describes secondary analysis of an existing
  randomized trial. [PMID 43090943](https://pubmed.ncbi.nlm.nih.gov/43090943/)
  [PMID 42384223](https://pubmed.ncbi.nlm.nih.gov/42384223/)
  [PMID 42976577](https://pubmed.ncbi.nlm.nih.gov/42976577/)

The date-sorted broad searches mixed published reviews and unrelated
interventions into the recent-RCT route. A title-focused supplementary
route checks whether that noise can be reduced. It cannot establish
comprehensive competitor coverage. [Initial live retrieval](https://github.com/ahmedkam997/scimed-srma-scout-cloud/actions/runs/45891785512)

The corrected title-focused retest resolved all six bounded PubMed routes.
The abstract of the pediatric uncomplicated appendicitis review reports
15 July 2026 for four databases and 13 October 2026 for CENTRAL and
ClinicalTrials.gov. The direct STEMI post-PCI mixed-design review reports
July 2025; the randomized three-agent PCI synthesis reports 15 November
2025. These are source-linked cutoff statements awaiting exact PICO and
full Methods comparison. No date was recovered from the short-term TAVR
stroke review abstract. The newer TAVR health-status record identifies
itself as a NOTION-2 analysis, so it provides a follow-up cue within an
existing family. [Corrected hosted run](https://github.com/ahmedkam997/scimed-srma-scout-cloud/actions/runs/45892078476)
[NOTION-2 follow-up, PMID 43053874](https://pubmed.ncbi.nlm.nih.gov/43053874/)

## Direct report-family and Methods audit

Hosted audit `45892409004` retrieved comparison metadata for the PubMed
subset of two shortlisted candidates. Five TAVR/SAVR registration-linked
reports were observed and two were unlinked. The ticagrelor/clopidogrel
subset contained four registration-linked reports. Reports from other
sources still require identity resolution. Registry links and publication
types do not establish independence, exact PICO eligibility or compatible
outcomes.

| Comparison | Registry-linked report leads | Unlinked PMIDs |
| --- | --- | --- |
| TAVR/SAVR | NCT01240902/32997095, NCT01586910/31476897, NCT02701283/30883053, NCT03383445/37883682, NCT03424941/39644913 | 35579641, 30409278 |
| Ticagrelor/clopidogrel | NCT01813435/30166073, NCT02018055/34627490, NCT04483583/38597172, NCT06318481/40892606 | None in the PubMed subset |

The open-access Methods resolver did not establish a cutoff for any of the
four target reviews (PMIDs 42985463, 42499063, 42201709 and 43090943).
This does not invalidate the abstract excerpts or show that full text is
unavailable from every authorized source. [Hosted family and Methods audit](https://github.com/ahmedkam997/scimed-srma-scout-cloud/actions/runs/45892409004)

### Cross-source reconciliation

The Europe PMC records in both cardiology shortlist rows carried exact
PubMed identifiers. Three additional reports per comparison were recovered
with PubMed EFetch. For ticagrelor/clopidogrel this added PMIDs 40886179,
38006237 and 38224415, with registrations NCT03465644, NCT02701140 and
NCT05516784. Seven distinct registration IDs are now observed in the sampled
report set. For TAVR/SAVR, PMID 40884768 added NCT02825134, PMID 27541162
shared NCT01240902 with PMID 32997095, and PMID 42032736 was unlinked.
TAVR/SAVR now has six registration-linked groups and three unlinked reports
in this set. Eligibility, participant independence and outcome
compatibility remain unverified. [Reconciled ledger](https://github.com/ahmedkam997/scimed-srma-scout-cloud/actions/runs/45892703433)

The PMC OAI audit returned publisher identifiers without establishing a
Methods cutoff. These exact DOI routes are now available for the hosted
publisher audit. [Pediatric appendicitis review](https://doi.org/10.3390/jcm15228910)
[Three-agent PCI synthesis](https://doi.org/10.1001/jamacardio.2026.1128)
[STEMI post-PCI review](https://doi.org/10.1097/md.0000000000049923)
[TAVR/SAVR stroke review](https://doi.org/10.31083/rcm49672)

### Renal denervation versus sham

The audit covered 12 reports, grouped 10 under seven distinct registration
identifiers and retained two unlinked records. RADIANCE-HTN TRIO and SOLO
returned the same registry identifier in the report evidence, which must
be reconciled with randomized cohorts before counting either as a new
population. SPYRAL HTN-ON and OFF MED reports also included repeated
analyses. The generic count/ratio extractor yielded no renal outcome
cues. Use continuous ambulatory blood-pressure data with a consistent
time point, medication status, and measure before judging usability.
[Renal family audit](https://github.com/ahmedkam997/scimed-srma-scout-cloud/actions/runs/45893203803)

The review query returned 33 hits, with six examined in this sample.
Full-text Methods yielded the following source-specific statements.

| Review PMID | Methods statement | Scope caveat |
| --- | --- | --- |
| 41205197 | PubMed, Ovid and Embase searched up to 4 September 2025 | Network meta-analysis across renal denervation approaches. |
| 40933009 | PubMed, Embase and Cochrane searched through 1 November 2024 | Ultrasound-specific synthesis. |
| 40478231 | Sources systematically searched for reports published before 31 December 2024 | Publication eligibility boundary. Actual last search run date remains unknown. |

The directly titled sham-controlled meta-analysis, PMID 40022571, did
not yield a Methods date through the tested open-access routes. One
sampled record, PMID 40640559, identifies itself as a comment. Treat the
network review date as an exploratory post-cutoff anchor and verify
exact overlap before asserting a review update. [Review and Methods audit](https://github.com/ahmedkam997/scimed-srma-scout-cloud/actions/runs/45893203803)

The bounded post-cutoff retrieval returned 38 hits and displayed the
first 12. The RDN-CKD Study title describes a randomized, blinded
sham-controlled comparison in chronic kidney disease. This is the
strongest newly sampled primary-report lead. Its registration identity,
participant independence, intervention details and compatible outcome
data are unverified. The 12-hit display also includes commentaries and
an atrial fibrillation protocol, so it is not an eligible-trial list.
The workflow remained nonzero because the competitor Methods audit was
incomplete. [Post-cutoff run](https://github.com/ahmedkam997/scimed-srma-scout-cloud/actions/runs/45893375836)
[RDN-CKD report](https://pubmed.ncbi.nlm.nih.gov/42937114/)

### RDN-CKD primary report check

PMID 42937114 describes a multicentre, blinded, randomized comparison of
ultrasound renal denervation versus sham in stage 3 CKD with uncontrolled
hypertension. The abstract reports early trial termination and 20
six-month completers (10 per arm). Six-month ambulatory and office BP are
reported outcome types. The 24-hour systolic ambulatory contrast is stated
as −5.60 mmHg (95% CI −10.7 to −0.54 mmHg; P=0.170). The interval excludes
zero while the reported P value exceeds 0.05. This could reflect different
analyses or an error and requires verification against the primary Methods,
tables or correction. Do not derive variance or pool that contrast from
the abstract alone. The abstract also reports diastolic contrasts, which
cannot substitute for systolic BP in a synthesis. Registration,
randomized denominators and independence remain unresolved.
[Source report](https://pubmed.ncbi.nlm.nih.gov/42937114/)
[Retrieval audit](https://github.com/ahmedkam997/scimed-srma-scout-cloud/actions/runs/45893689730)

ClinicalTrials.gov acronym and clinical-scope recovery surfaced
NCT04264403 (RDN-CKD, internal protocol RDN2019CKD). A same-titled record
also appeared for NCT07742787 (RDN-CKD GR, internal protocol
RDN2022CKDGR). Both are leads. Neither is counted as another trial.
The first hosted public annotation truncated the result; the next run
fetches and reports each exact registry record separately.
[Registry search](https://github.com/ahmedkam997/scimed-srma-scout-cloud/actions/runs/45893775017)
[Exact registry comparison](https://github.com/ahmedkam997/scimed-srma-scout-cloud/actions/runs/45893883613)

The two exact registry records both list a randomized crossover design
and six-month change in 24-hour ambulatory systolic BP. NCT04264403 is a
completed multicentre German study with 44 actual enrollees.
NCT07742787 is an Athens study with 20 actual enrollees, listed as
active, not recruiting. Neither record cited PMID 42937114 or supplied
posted results in the retrieved data. The multicentre German record
matches more of the published abstract's design cues. Its 44 enrolled
participants and the abstract's 20 six-month completers are different
denominators. Verify the publication linkage, pre-crossover allocation,
analysis denominator and missing participant handling before classifying
the estimate. No registry lead qualifies under the current strict
parallel-randomization gate. [Exact registry records audit](https://github.com/ahmedkam997/scimed-srma-scout-cloud/actions/runs/45893883613)
[German registry](https://clinicaltrials.gov/study/NCT04264403)
[Greek registry](https://clinicaltrials.gov/study/NCT07742787)

### Alternate cardiology shortlist

The bounded sacubitril/valsartan search returned 14 hits and inspected
four. It found a directly titled HFrEF synthesis (PMID 41773097) and
two Chagas cardiomyopathy syntheses (PMIDs 41941460 and 41923142). No
Methods cutoff was recovered for those reviews. Treat Chagas as a
distinct population and verify the matching review's included trials
and cutoff before inferring novelty.

The AF ablation search returned 91 hits and inspected four. Two were
close competitors in heart failure (PMIDs 42119914 and 42769399).
The second review's full-text Methods states that PubMed, Embase and
Cochrane were searched through February 2026. It addresses reduced or
mildly reduced ejection fraction. Neither the exact day nor overlap
with the broader AF comparison is established. The other two hits
concern discharge or delayed ablation, rather than medical therapy.
[Hosted competitor and Methods retrieval](https://github.com/ahmedkam997/scimed-srma-scout-cloud/actions/runs/45894079291)

The artifact replay recovered both trial-family ledgers. The
sacubitril/valsartan comparison contains five distinct registry links and
two unlinked reports. It mixes pediatric PANORAMA-HF, acute
decompensation, Chagas cardiomyopathy and renal outcome analyses. Check
adult HF phenotype, care setting, comparator and common endpoints before
counting any review-eligible trials. [PANORAMA-HF](https://pubmed.ncbi.nlm.nih.gov/39319469/)
[Acute decompensation report](https://pubmed.ncbi.nlm.nih.gov/30415601/)
[Chagas trial](https://pubmed.ncbi.nlm.nih.gov/41335448/)

The catheter ablation ledger has one explicit registration, CABANA
(NCT00911508), and six unlinked reports. Titles identify a second
CABANA report and two CASTLE-HTx reports. The ledger also contains a
cost-effectiveness report. Exclude the economic evaluation from the
primary-RCT inventory and verify the CASTLE-HTx primary publication,
registration, HF phenotype and comparator. Repeated reports do not
increase the independent trial count.
[CABANA primary report](https://pubmed.ncbi.nlm.nih.gov/30874766/)
[Artifact replay](https://github.com/ahmedkam997/scimed-srma-scout-cloud/actions/runs/45894258451)
