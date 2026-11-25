# SciMed Discovery benchmark v1

## Purpose
A small, reproducible, offline regression suite. It is NOT an externally validated gold standard for deciding whether a novel SRMA should be published. The synthetic cases exercise the existing discovery-only policy (four bibliographic leads, not four eligible trials); they do not calibrate clinical judgment or endorse a lower trial threshold for an RCT-only review.

## Evidence and methodology
- SYNERGY: https://doi.org/10.34894/HE6NAQ — labeled report-level screening data, appropriate for subsequent screening-recall validation, not topic novelty labels. No dataset download is required by v1.
- Cochrane Handbook chapter 4: https://www.cochrane.org/authors/handbooks-and-manuals/handbook/current/chapter-04 — distinguish study populations from reports.
- Garner et al. BMJ 2016;354:i3507: https://doi.org/10.1136/bmj.i3507 — update decisions require new information and current relevance, not publication dates alone.
- The published case citations, dates, and reference judgments are in discovery_v1.json. Only bibliographic relationships are checked. Clinical independence is not presumed for platform comparisons.

Run: `python -m scimed_scout.discovery.benchmark --output benchmark-report.json`. GitHub Actions also runs this command. The report explicitly exposes known scientific gaps rather than marking them resolved.

## Next external validation
Freeze dated PICO questions and full-text eligibility labels from independent reviewers. Include genuine redundant, underpowered, novel, update, and unresolved questions; preserve exact search cutoffs, evidence links and disagreements. Use separate development and holdout sets. Report precision, recall, false-positive qualification rate and abstention rate with denominators, stratified by question type. Compare current engine against baseline and blinded human assessment. Do not tune on held-out labels. Measure API costs and latency separately. For trial-family linkage, check protocol identifiers alongside comparison, recruitment period, and population; platform registration alone is insufficient.

## Limitations
Only 12 synthetic gate cases and three published bibliographic cases. The policy tests are deterministic; a pass says nothing about clinical novelty prediction, search sensitivity, LLM calibration or publication acceptance. R01 and R02 expose the current report counter's limitation. R03 tests chronology, not the full update-decision engine. No live APIs, model calls, or new cloud job are needed.
