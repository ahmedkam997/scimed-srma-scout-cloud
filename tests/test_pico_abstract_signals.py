from scimed_scout.discovery.review_package import _pico_fit_signals
from scimed_scout.storage import CandidateRecord


def candidate():
    return CandidateRecord(
        candidate_id="T",project_id="P1",title="Ketone intervention in endurance heat stress",
        specialty="Cardiology",question_type="EFFECTIVENESS",
        population="Endurance athletes exercising under heat stress",
        intervention_exposure_index_test="Ketone monoester",
        comparator_reference="Placebo",
        outcomes=["Cardiac strain", "Troponin"],
        eligible_designs=["RCTs"],
    )


def record(title, *, abstract="", doi="", source="Europe PMC"):
    return {
        "source_record_id": title,
        "source": source,
        "title": title,
        "payload": {
            "doi": doi,
            "url": "https://europepmc.org/article/MED/12345",
            "metadata": {"abstractText": abstract},
        },
    }


def test_abstract_pico_cues_are_deduplicated_and_not_counted_as_verified_trials():
    a=record(
        "Ketone monoester supplementation for endurance athletes",
        abstract="Randomized placebo controlled trial in endurance athletes."
                 " We measured cardiac strain and troponin during heat stress.",
        doi="10.0001/foo",
    )
    b=record(a["title"], source="PubMed", abstract="No abstract available")
    c=record("Ketone monoester ingestion improves monocyte phenotype",
             abstract="A study in healthy cells unrelated to endurance athletes.")
    signals=_pico_fit_signals(candidate(),[a,b,c])
    assert signals["total_unscreened_records"]==3
    assert signals["distinct_bibliographic_titles_screened"]==2
    assert signals["abstract_or_title_full_pico_signals"]==1
    assert signals["intervention_outcome_text_matches"]==1
    assert signals["source_linked_full_pico_clues"][0]["doi"]=="10.0001/foo"
    assert signals["independent_studies_confirmed"] is False
    assert signals["direct_head_to_head_trials_confirmed"] is False


def test_unrelated_outcomes_and_missing_abstract_do_not_claim_eligible_studies():
    r=record("Ketone monoester intake in adult marathon runners",
             abstract="This trial focused on muscle glycogen only.")
    signals=_pico_fit_signals(candidate(),[r])
    assert signals["abstract_or_title_full_pico_signals"]==0
    assert signals["intervention_outcome_text_matches"]==0
    assert signals["independent_studies_confirmed"] is False
