from scimed_scout.discovery.review_opportunity import assess_review_opportunity, date_bounds


def review(id="R", cutoff="2022-01-06", quote=None, **metadata):
    meta = {"last_search_date": cutoff,
            "search_date_evidence_quote": quote if quote is not None else f"We searched databases until {cutoff}.",
            "search_date_evidence_url": "https://example.org/review",
            "search_date_evidence_level": "FULL_TEXT_METHODS", **metadata}
    return {"source":"PubMed","source_record_id":id,"title":"Review "+id,"payload":{"year":2024,
            "url":"https://example.org/review/"+id,"metadata":meta,
            "discovery_semantic_assessment":{"overall_overlap":"HIGH","confidence":0.95,"unresolved":False,
                "dimensions":[{"name":name,"evidence":"Source citation cue"} for name in ("population","intervention","comparator","outcomes")]}}}


def report(id, year, registry="", **metadata):
    return {"source":"PubMed","source_record_id":id,"title":"Report "+id,"payload":{"year":year,
            "url":"https://example.org/study/"+id,"metadata":{"trial_registration_id":registry,**metadata}}}


def assess(reviews, records, all_records=None, **kwargs):
    return assess_review_opportunity(reviews, records, records if all_records is None else all_records,
                                     coverage_complete=True, **kwargs)


def test_exact_same_year_cutoff_and_uncertain_year_only():
    a=report("A",2022,"NCT00000001",firstPublicationDate="2022-03-15")
    b=report("B",2022,"NCT00000002")
    result=assess([review()], [a,b])
    assert result["route"]=="UPDATE_SIGNAL"
    assert result["post_cutoff_registered_family_leads"]==1
    assert result["uncertain_chronology_or_linkage_count"]==1
    assert result["confirmed_new_independent_eligible_studies"] is None
    assert result["qualified"] is False


def test_latest_cutoff_of_all_material_reviews_and_missing_cutoff():
    p=report("A",2023,"NCT00000001")
    result=assess([review("R1"),review("R2","2023-12-31")],[p])
    assert result["latest_source_linked_cutoff_end"]=="2023-12-31"
    assert result["post_cutoff_registered_family_leads"]==0
    result=assess([review("R1"),review("R2",quote="")],[p])
    assert result["route"]=="OVERLAP_NEEDS_ADJUDICATION"
    assert result["latest_source_linked_cutoff_end"] is None


def test_publication_year_not_substituted_for_search_date():
    result=assess([review(cutoff=None,quote="")],[report("A",2025,"NCT00000001")])
    assert result["route"]=="OVERLAP_NEEDS_ADJUDICATION"
    assert result["missing_material_review_cutoffs"]==1


def test_followup_not_new_independent_family_and_unlinked_not_counted():
    old=report("A",2020,"NCT00000001")
    new=report("B",2023,"NCT00000001")
    unlinked=report("C",2023)
    newfamily=report("D",2023,"NCT00000002")
    companion=report("E",2024,"NCT00000002")
    result=assess([review()],[new,unlinked,newfamily,companion],[old,new,unlinked,newfamily,companion])
    assert result["post_cutoff_registered_family_leads"]==1
    assert result["post_cutoff_known_family_followup_count"]==1
    assert result["post_cutoff_unlinked_report_count"]==1


def test_corrective_cue_is_not_verified_flaw_and_absent_text_not_failure():
    result=assess([review(abstractText="We searched only PubMed. A single reviewer screened titles.")],[])
    assert result["route"]=="CORRECTIVE_SIGNAL"
    assert len(result["correction_method_cues"])==2
    assert result["verified_material_methodological_flaws"] is None
    assert not result["qualified"]
    assert assess([review()],[])["correction_method_cues"]==[]


def test_unresolved_or_low_overlap_does_not_become_update_clearance():
    r=review()
    r["payload"]["discovery_semantic_assessment"]["unresolved"]=True
    result=assess([r],[report("A",2025,"NCT00000001")],competitor_scope_unresolved=True)
    assert result["route"]=="NOVEL_REVIEW_ASSESSMENT"
    assert result["competitor_scope_unresolved"] and not result["qualified"]


def test_date_precision_and_invalid_dates():
    assert date_bounds("February 2024")[1].isoformat()=="2024-02-29"
    assert date_bounds("2022-02-30") is None
    assert date_bounds("01/02/2022") is None
