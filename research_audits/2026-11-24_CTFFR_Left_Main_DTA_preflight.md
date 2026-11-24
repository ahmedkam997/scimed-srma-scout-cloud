# SciMed Final Evidence Audit: FFR-CT in Intermediate Left Main Stenosis

Date: 24 November 2026  
Saved candidate: `CAND-090E5F562A951667`  
Parent discovery job: `4d10637b-b367-474c-b588-770b5834764b`  
Original state: `PROVISIONAL_BACKUP` (unchanged)  
Analyst recommendation: **REFINE — DO NOT REGISTER NOW** pending full-text LM-specific DTA verification.

## A. First fix the uploaded audit's methodological mismatch

The exported Final Evidence Audit from the prior application version contained `DOAC_ONLY_DIALYSIS_COMPARATIVE_OUTCOMES` despite the title `Computed Tomography Fractional Flow Reserve in Left Main Disease`. That gate was inherited from a separate LAAO-versus-DOACs ESRD comparison and has no valid relationship with a diagnostic-test-accuracy (DTA) review. The old export's 58 bibliographic primary-study leads, 21 published-review hits, and 52 registration hits do **not** prove independent eligible LM accuracy datasets. It was correct to keep the eligible count **unknown**.

The corrected Final Evidence Audit determines question type from the saved PICO, eligible designs and endpoints. This DTA case now receives index test, reference standard, clinically relevant threshold, TP/FP/FN/TN, unit-of-analysis and QUADAS-3 feasibility checks. The Cochrane DTA Handbook and PRISMA-DTA are preferable methods here, rather than a comparative-treatment risk-of-bias template.

## B. Define the question and reference standard precisely

| PICO/measurement | Target requirement |
|---|---|
| Population | Adults with intermediate stenosis of the left main coronary artery; separate isolated LM from downstream LAD/LCx or multivessel stenosis when source reports allow |
| Index test | Coronary CTA-derived fractional flow reserve, with algorithm, interpretation site and thresholds documented |
| Reference standard | **Invasive pressure-wire FFR** measuring the hemodynamic significance of LM disease; angiographic diameter stenosis alone is not the same comparator |
| Target condition | Functionally significant intermediate LM stenosis according to a prespecified invasive FFR threshold |
| Extractable diagnostic outcome | Left-main-specific TP, FP, FN, TN at the same index-test/reference cutoffs, or source data sufficient to derive them |
| Analysis unit | One of patient, vessel or LM lesion, defined explicitly; do not treat multiple vessels from one patient as independent people |
| Study independence | Deduplicated independent cohorts, with clear follow-up or duplicate publications linked by a stable study-family ID |

A minimum of four independent studies is a **SciMed project feasibility preference**, not a universal Cochrane or statistical prerequisite for meta-analysis.

## C. Scientific and clinical findings from checked sources

**2026 SCCT/SCAI consensus:** [Journal of Cardiovascular Computed Tomography](https://www.journalofcardiovascularct.com/article/S1934-5925%2826%2900101-2/fulltext), doi: 10.1016/j.jcct.2026.05.006. Its Table 3 explicitly warns against using CT-FFR to determine the functional significance of left main coronary disease under current evidence because optimal thresholds, including downstream LAD/LCx pressure-drop interpretation, still require validation. This is clinical motivation for a focused DTA evidence audit, **not proof four eligible DTA studies exist**.

**2021 LM-specific report:** [Riedl et al., Coronary CT angiography-derived FFR in patients with left main disease](https://pubmed.ncbi.nlm.nih.gov/34383150/), doi: 10.1007/s10554-021-02371-4. The objective was description of FFR-CT findings and clinical utility in LM disease. A directly paired invasive-FFR reference and full left-main 2×2 diagnostic counts for intermediate LM stenosis were **not verified**. Potentially informative but not yet eligible.

**2025 pre-TAVI report:** [*Two birds with one stone: pre-TAVI coronary CT angiography combined with FFR helps screen for coronary stenosis*](https://link.springer.com/article/10.1186/s12880-025-01704-2), doi: 10.1186/s12880-025-01704-2. Contains a segment-level LM CT-FFR table but evaluates against invasive coronary angiographic (ICA) findings rather than a documented paired invasive pressure-wire FFR reference. **Comparator mismatch pending original methods verification**; do not pool its LM accuracy estimates into invasive-FFR DTA without verification.

**2026 CAD diagnostic accuracy report:** [*Diagnostic performance of on-site, CT-derived fractional flow reserve in predicting invasive fractional flow reserve and absolute myocardial blood flow*](https://www.journalofcardiovascularct.com/article/S1934-5925%2826%2900050-X/fulltext), doi: 10.1016/j.jcct.2026.02.007. Reports an individual false-negative left-main quadrifurcation lesion. A single example is not an LM-specific independent accuracy cohort with TP/FP/FN/TN, so **no eligibility confirmation**.

**Broader published competitors:** [2025 machine-learning CT-FFR meta-analysis](https://pmc.ncbi.nlm.nih.gov/articles/PMC11795686/) pooled 17 studies of general coronary accuracy using patient/vessel analyses. A [2026 conference review of CT-FFR versus invasive FFR in stable CAD](https://heart.bmj.com/content/112/Suppl_1/A154) searched to September 2024. Neither was independently verified to analyze the precise intermediate-left-main PICO. This is **broad-topic overlap**, not confirmed identical-question redundancy.

**PROSPERO/OSF:** The uploaded source report showed 52 registry hits but no validated full-text protocol screening for this particular candidate. No PROSPERO match was claimed absent registry-level evidence. `REGISTRATION_STATUS=UNRESOLVED` is correct.

## D. Comparable open-source methods and their role

- [Cochrane DTA Handbook](https://www.cochrane.org/authors/handbooks-and-manuals/handbook-systematic-reviews-diagnostic-test-accuracy): select appropriate index tests, reference standard, study designs, and meta-analysis unit.
- [PRISMA-DTA](https://www.prisma-statement.org/dta): DTA reporting and transparency; 2×2 counts and diagnostic estimates.
- [QUADAS-3 (2026)](https://pubmed.ncbi.nlm.nih.gov/41698208/): contemporary risk-of-bias and applicability judgments for DTA studies. Confirm journal/protocol requirements before choosing the tool.
- [MetaDTA on GitHub](https://github.com/CRSU-Apps/MetaDTA): open-source R Shiny tool implementing bivariate DTA meta-analysis. Adapt or use for quantitative synthesis *after* eligibility/2×2 confirmation; not a substitute for novelty or primary-study verification.
- [Meta-DiSc 2.0](https://pmc.ncbi.nlm.nih.gov/articles/PMC9707040/): published web-based DTA meta-analysis implementation. Compare supported analyses and maintenance before choosing an analysis platform.

The Scout audit remains a pre-synthesis verification tool; no statistical meta-analysis was run.

## E. Decision and next checks

**REFINE (not immediately registrable):** Assess whether a narrower LM-only DTA review is feasible, but do not conclude novelty or quantitative extractability based on the generic CAD literature. The existing expert warning creates a meaningful clinical question, yet the number of LM-specific invasive-FFR cohorts remains **UNKNOWN**.

Next steps: (1) obtain complete LM-specific primary papers and supplements; (2) verify paired index/reference measurements and actual LM 2×2 counts, thresholds, analysis units and independence; (3) complete PROSPERO, OSF and published-review overlap audit; (4) decide whether an SR without meta-analysis, methodological scoping review or a different research question is better if independent eligible data are sparse.

No original job status, source coverage flag or clinical result was rewritten by this audit. Do not confuse `COMPLETED` cloud jobs with scientific qualification.
