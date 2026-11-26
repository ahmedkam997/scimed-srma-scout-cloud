from scimed_scout.discovery.rct_first import review_title_query
from scripts.external_reference_validation import metrics,linkage,retrieval
from scimed_scout.sources.base import SearchRecord

def test_competitor_recovery_is_title_based_and_not_population_required():
    q=review_title_query(("atrial fibrillation","pulsed field ablation",(),()),"thermal ablation")
    assert '"pulse field ablation"[ti]' in q
    assert '"thermal techniques"[tiab]' in q
    assert '"atrial fibrillation"' not in q
    assert "systematic" in q

def test_independent_proxy_metric_confusion_matrix():
    rows=[{"nctId":"NCT00000001","PMID":"1","label":"1","article_abstract":"Trial registration: NCT00000001"},
          {"nctId":"NCT00000002","PMID":"2","label":"0","article_abstract":"No registration mentioned"},
          {"nctId":"NCT00000003","PMID":"3","label":"2","article_abstract":"Trial registration: NCT00000003"},
          {"nctId":"NCT00000004","PMID":"4","label":"2","article_abstract":"Not linked"}]
    out=linkage(rows)
    assert (out["tp"],out["fp"],out["fn"],out["tn"])==(1,1,1,1)
    assert out["sensitivity"]==out["precision"]==0.5
    assert not out["independent_rct_eligibility_validated"]

def test_off_corpus_hits_not_false_positives():
    labels=[{"pmid":"1","label_included":"1"},{"pmid":"2","label_included":"0"},{"pmid":"3","label_included":"1"}]
    out=retrieval(labels,[SearchRecord("PubMed","1","A"),SearchRecord("PubMed","2","B"),SearchRecord("PubMed","999","Outside")])
    assert (out["tp"],out["fp"],out["fn"],out["tn"])==(1,1,1,0)
    assert out["retrieved_distinct_records"]==3
