# Phase 3 replay checkpoint

Baseline: PR #34 and `scientific-verification-v2-phase3-replay` both resolved to
`b8a7236931040d1457ad729460f6ec311eeab830`. Work here is development evaluation.
The decision from the earlier surgical transfer stands: retain conservative
search-route expansion. A ranking model can prioritize screening, but the
search, eligibility, novelty, seven independent RCTs, seven quantitatively
usable RCTs, and signed adjudication requirements still apply.

## Screening replay

ASReview 3.0.8 fits its published active-learning model within each closed
corpus. It starts with one oracle positive and one oracle negative, counts
both in workload, and uses the same run and prior seed (42, 17, or 73).
The audit counts individual screening decisions in the ungrouped simulation.
For a grouped simulation it measures duplicate-group decisions and expanded
row coverage separately. WSS@95 is 0.95 minus the fraction screened to reach
at least 95% of published positives. The random comparator is the expected
position of that positive in a uniformly random ordering without replacement.
Neither metric is evidence of safe stopping or overall search recall.

ASReview's default results export hides nonrepresentative duplicate rows even
when the simulation uses independent row decisions. In the statins seed-42
replay there were 85 of 85 positives in the full results and 84 in the default
view. Recalculating on the full results changed workload at 95% from 1,744 to
1,745. The input had 115 nonrepresentative rows across seven groups. Grouped
simulation refused one label-conflicted group. The recovery kept the original
labels and the ungrouped simulation. A separate synthetic grouped exercise with
consistent labels audited three screening decisions and five expanded rows.

The two Cohen drug corpora share 49 PubMed identifiers, and CSMeD includes the
Cohen collection. Treat these runs as related development controls. Use source
review and report identity, plus trial-family and temporal overlap checks,
before assigning any data to a final blind evaluation. The Muthu spine-surgery
review selected parallel RCTs with statistically significant dichotomous
outcomes. The official SYNERGY+ exporter retained 923 of 2,710 available
labels and 20 of 70 positive labels under its open-access and valid-abstract
filters. Its workload measures only that filtered corpus. The selection rule
and filtered-out positives preclude using the result as general surgical
recall.

All nine ungrouped runs reached every published positive in their input. The
workload varied substantially by corpus and seed.

| Corpus | Records / positives | Decisions to 95% recall, seeds 42 / 17 / 73 | WSS@95 range |
| --- | ---: | ---: | ---: |
| Cohen statins | 3,465 / 85 | 1,745 / 1,419 / 1,745 | 0.446–0.540 |
| Cohen ACE inhibitors | 2,544 / 41 | 506 / 1,156 / 507 | 0.496–0.751 |
| SYNERGY+ Muthu spine surgery | 923 / 20 | 700 / 699 / 703 | 0.188–0.193 |

At a 50% screening budget the Muthu replay found 16 of 20 positives in each
seed. This supports continuing the screening workload evaluation across
review families while preserving records for reviewer assessment.
[Aggregate results and provenance](../benchmarks/PHASE3_REPLAY_RESULTS.json)

Technical validation passed 570 Python tests with native Aviary/LDP installed,
68 web tests, the CLI health check and 15 discovery benchmark checks. The
discovery benchmark retains three documented scientific evidence gaps.
Both edited workflows passed local YAML and shell syntax validation.

## Reproduce or resume

- Use Python 3.12 and isolated environments for ASReview 3.0.8 and for
  `fhaviary==0.37.0` with `ldp[scg]==1.10.1`. The work used local CPU execution,
  without model API calls or paid services.
- Obtain `Statins.csv` and `ACEInhibitors.csv` from
  `datasets/Cohen_2006/output/online/` at the pinned Cohen revision below.
  Verify hashes against the JSON checkpoint.
- For SYNERGY+, download only `Muthu_2020/{metadata.json,labels.csv,works_1.zip}`
  from the pinned revision. Use `synergy-dataset==2.2` and
  `Dataset("Muthu_2020", path=Path("Muthu_2020")).to_frame()`. Export the
  `title`, `abstract`, and `label_included` columns in that order with
  `to_csv("muthu.csv", index=False)`. Preserve the count before filtering.
- Run from a scratch directory with `PYTHONPATH` pointing to the replay checkout.
  Use separate project paths per corpus and seed. For example:

  ```bash
  OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 asreview simulate statins.csv \
    -o statins-42.asreview --seed 42 --prior-seed 42 \
    --n-prior-included 1 --n-prior-excluded 1
  python -m scripts.asreview_screening_audit statins.csv statins-42.asreview \
    --seed 42 --output statins-42-audit.json
  ```

  Re-audit existing completed projects and run only missing seeds. Keep any
  interrupted `.asreview.tmp` directory available for diagnosis and use a fresh
  output path for the retry. Raw inputs, archives, and logs for this session
  are under `/workspace/scratch/scimed-phase3`. The versioned checkpoint holds
  the aggregate results and provenance. Dataset sources are pinned below.
  [Cohen collection](https://github.com/asreview/systematic-review-datasets/tree/38b35218e4d0f99621cec5a8a25a0147bb88c654/datasets/Cohen_2006)
  [SYNERGY+ Muthu cohort](https://github.com/asreview/synergy-dataset/tree/d6c46f32bd0e325a64eafa9da6dd3bdb9db5579f/Muthu_2020)
  [CSMeD source inventory](https://github.com/WojciechKusa/systematic-review-datasets/tree/b30e9739939f52b1e799295138791f1fd5b002a5)

## Blocked scientific checks

- The cloud proxy denied PubMed E-utilities requests. The native Aviary/LDP
  run now writes development route diagnostics and exits nonzero with no new
  policy when source access fails. The report curriculum writes an
  `ACCESS_FAILED` artifact and exits nonzero when the fetch fails. Retest both
  from a fresh output directory once authorized `eutils.ncbi.nlm.nih.gov`
  access is available. Keep failed-source observations unresolved.
- The proxy denied Hugging Face access and this machine has no GPU device.
  LEADS evaluation needs authorized model artifact access and a suitable
  existing compute allowance. Its assessment also needs independent PICO and
  outcome labels; the screening runs did not modify model weights.
- Release acceptance needs a frozen, representative and independently
  adjudicated corpus, including exact trial independence, outcome/arm/timepoint
  extraction and competitor decisions. Preserve the signed two-reviewer
  adjudication requirement. No model or retrieval policy was promoted.
  [Adjudication contract](SCIENTIFIC_VERIFICATION_V2.md)
  [LEADS paper](https://doi.org/10.1038/s41467-025-62058-5)
