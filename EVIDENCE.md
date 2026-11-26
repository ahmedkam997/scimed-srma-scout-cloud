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
