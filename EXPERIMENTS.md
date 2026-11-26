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
