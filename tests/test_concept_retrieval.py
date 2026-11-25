from scimed_scout.storage import CandidateRecord
from scimed_scout.discovery.concept_retrieval import match,experimental_queries
from scimed_scout.discovery.query_optimizer import optimized_queries

def candidate(pop,inter):
    return CandidateRecord("C","P","topic","Neurology",population=pop,intervention_exposure_index_test=inter)

def test_stroke_concepts_preserve_both_anchors_and_unfiltered_query():
    c=candidate("Adults with acute ischemic stroke due to large vessel occlusion","Endovascular thrombectomy")
    qs=experimental_queries(c,"PRIMARY",("stroke thrombectomy","endovascular therapy"))
    assert len(qs)==2
    assert all('"Ischemic Stroke"[MeSH Terms]' in q and '"Thrombectomy"[MeSH Terms]' in q for q in qs)
    assert "randomized controlled trial[pt]" in qs[0] and "randomized controlled trial[pt]" not in qs[1]
    assert '"occlusion"[Title/Abstract]' not in qs[0]
    review=experimental_queries(c,"REVIEW",("thrombectomy stroke systematic review","thrombectomy stroke meta analysis"))
    assert len(review)==2 and "Meta-Analysis" in review[0]

def test_unknown_negated_or_ambiguous_anchors_fall_back():
    for pop,inter in (("stroke without diabetes","endovascular thrombectomy"),("type 1 diabetes or type 2 diabetes","continuous glucose monitoring"),("acute kidney injury and ischemic stroke","renal replacement therapy"),("unknown condition","unknown intervention")):
        c=candidate(pop,inter);old=("legacy one","legacy two")
        assert experimental_queries(c,"PRIMARY",old)==optimized_queries(c,"PubMed","PRIMARY",old,max_queries=2)

def test_cgm_does_not_replace_type_1_by_generic_diabetes():
    c=candidate("Adults with type 1 diabetes using multiple daily insulin injections","Continuous glucose monitoring")
    qs=experimental_queries(c,"PRIMARY",("CGM type 1 diabetes","glucose sensor type 1 diabetes"))
    assert all('"Diabetes Mellitus, Type 1"[MeSH Terms]' in q for q in qs)
    assert all('"Diabetes Mellitus"[MeSH Terms]' not in q for q in qs)
