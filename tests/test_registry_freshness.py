from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

from scimed_scout.discovery.novelty import (
    registration_age_audit,
    published_review_update_audit,
)


def question():
    return SimpleNamespace(intervention_exposure_index_test="Ketone monoester")


def primary(title: str, year: int):
    return {
        "title": title, "source": "PubMed", "source_record_id": title,
        "payload": {"year": year, "doi": "10.1234/" + str(year) + title[:4]},
    }


def register(source: str, year: int | None = None, **metadata):
    if year is not None:
        metadata.setdefault("year_first_published" if source == "PROSPERO" else "date_registered", str(year))
    return {
        "title": "Ketone monoester systematic review", "source": source,
        "source_record_id": "CRD420190000001" if source == "PROSPERO" else "abc12",
        "payload": {"year": year, "metadata": metadata},
    }


def test_old_prospero_registration_is_an_update_lead_not_an_automatic_rejection():
    doc = register("PROSPERO", 2019, review_status="Ongoing")
    news = [primary("Ketone monoester endurance trial", 2025)]
    audit = registration_age_audit(question(), doc, news)
    assert audit["classification"] == "OLDER_REGISTRATION_UPDATE_OPPORTUNITY_TO_VERIFY"
    assert audit["registry_status"] == "Ongoing"
    assert audit["post_registration_bibliographic_leads"]["count"] == 1
    assert audit["post_registration_bibliographic_leads"]["eligible_studies_confirmed"] == 0
    assert audit["publication_status"] == "NOT_VERIFIED"
    assert audit["review_last_search_date"] == "NOT_VERIFIED"
    assert audit["novelty_confirmed"] is False


def test_recent_registered_protocol_stays_competing_even_with_newer_bibliography():
    doc = register("OSF Registries", datetime.now(timezone.utc).year,
                   registry_status="accepted", date_modified="2026-10-01")
    audit = registration_age_audit(question(), doc, [primary("Ketone monoester trial", 2026)])
    assert audit["classification"] == "RECENT_REGISTRATION_REVIEW_COMPETITION"
    assert audit["registry_metadata_modified_at"] == "2026-10-01"
    assert audit["publication_status"] == "NOT_VERIFIED"


def test_unknown_or_withdrawn_osf_registration_never_infers_no_competitor():
    unknown = registration_age_audit(question(), register("OSF Registries"), [])
    assert unknown["classification"] == "UNKNOWN_DATE_MANUAL_REVIEW"
    withdrawn = registration_age_audit(question(), register("OSF Registries", 2020, withdrawn=True), [])
    assert withdrawn["classification"] == "WITHDRAWN_REGISTRATION_VERIFY_PUBLICATION"
    assert withdrawn["novelty_confirmed"] is False


def test_old_publication_is_not_a_verified_search_cutoff():
    review = {
        "title": "Systematic review of ketone monoester",
        "source": "PubMed", "source_record_id": "R1",
        "payload": {"year": 2019, "metadata": {}},
    }
    audit = published_review_update_audit(question(), review, [primary("Ketone monoester trial", 2025)])
    assert audit["publication_year"] == 2019
    assert audit["classification"] == "OLD_REVIEW_POTENTIAL_UPDATE_SEARCH_DATE_UNVERIFIED"
    assert audit["post_cutoff_bibliographic_leads"]["count"] is None
    assert audit["post_publication_bibliographic_leads"]["count"] == 1
    assert audit["novelty_confirmed"] is False


def test_explicit_search_cutoff_supports_bibliographic_update_signal_only():
    review = {
        "title": "Systematic review of ketone monoester",
        "source": "PubMed", "source_record_id": "R1",
        "payload": {"year": 2023, "metadata": {"last_search_date": "2020-08-31"}},
    }
    audit = published_review_update_audit(question(), review, [
        primary("Ketone monoester randomized trial", 2024),
        primary("Unrelated fracture surgery trial", 2025),
    ])
    assert audit["classification"] == "POTENTIAL_UPDATE_VERIFY_NEW_STUDY_ELIGIBILITY"
    assert audit["last_search_date"] == "2020-08-31"
    assert audit["post_cutoff_bibliographic_leads"]["count"] == 1
    assert audit["novelty_confirmed"] is False


def test_old_registration_with_recent_metadata_edit_needs_recheck_not_auto_stale():
    audit = registration_age_audit(
        question(),
        register("OSF Registries", 2018, date_modified="2026-11-01",
                 registry_status="accepted"),
        [primary("Ketone monoester randomized clinical trial", 2025)],
    )
    assert audit["classification"] == "OLD_REGISTRATION_WITH_RECENT_METADATA_ACTIVITY"
    assert audit["recent_metadata_activity"] is True
    assert audit["post_registration_bibliographic_leads"]["count"] == 1
    assert audit["novelty_confirmed"] is False


def test_old_completed_prospero_record_still_needs_publication_lookup():
    audit = registration_age_audit(
        question(),
        register("PROSPERO", 2017, review_status="Completed and published"),
        [primary("Ketone monoester study", 2025)],
    )
    assert audit["classification"] == "OLDER_COMPLETED_REGISTRATION_CHECK_PUBLISHED_REVIEW"
    assert audit["publication_status"] == "NOT_VERIFIED"
    assert audit["review_last_search_date"] == "NOT_VERIFIED"


def test_exact_prospero_accession_in_published_review_finds_publication_candidate():
    from scimed_scout.discovery.novelty import _attach_publication_linkage
    reg = registration_age_audit(question(), register("PROSPERO", 2018), [])
    published = [{
        "title": "Systematic review and meta-analysis of ketone monoester",
        "source": "PubMed", "source_record_id": "PMID-5",
        "payload": {
            "year": 2022,
            "metadata": {
                "abstract": "PROSPERO registration number CRD420190000001 and included trials."
            },
        },
    }]
    _attach_publication_linkage(reg, published)
    assert reg["publication_status"] == "PUBLICATION_CANDIDATE_LINKED_BY_REGISTRY_ID"
    assert reg["linked_publication_candidates"][0]["year"] == 2022
    assert reg["linked_publication_candidates"][0]["full_text_linkage_verified"] is False


def test_similar_title_without_exact_registry_id_does_not_claim_publication():
    from scimed_scout.discovery.novelty import _attach_publication_linkage
    reg = registration_age_audit(question(), register("PROSPERO", 2019), [])
    published = [{
        "title": "Systematic review and meta-analysis of ketone monoester",
        "source": "PubMed", "source_record_id": "PMID-6",
        "payload": {"year": 2025, "metadata": {
            "abstract": "The intervention was reviewed among endurance athletes."
        }},
    }]
    _attach_publication_linkage(reg, published)
    assert reg["publication_status"] == "NOT_VERIFIED"


def test_osf_publication_link_requires_full_registration_url_not_short_id():
    from scimed_scout.discovery.novelty import _attach_publication_linkage
    reg = registration_age_audit(question(), register("OSF Registries", 2019), [])
    published = [{
        "title": "Systematic review of ketone monoester",
        "source": "PubMed", "source_record_id": "PMID-8",
        "payload": {"year": 2023, "metadata": {
            "abstract": "Our OSF protocol is at https://osf.io/abc12/ ."
        }},
    }]
    _attach_publication_linkage(reg, published)
    assert reg["publication_status"] == "PUBLICATION_CANDIDATE_LINKED_BY_REGISTRY_ID"


def test_unrelated_prospero_hit_does_not_claim_newer_evidence_for_another_pico():
    from scimed_scout.discovery.novelty import registration_pico_preflight
    registration = {
        "source": "PROSPERO",
        "source_record_id": "CRD420180000101",
        "title": "Effect of vitamin D supplementation on dental implant stability",
        "payload": {"year": 2018, "metadata": {"review_status": "Completed"}},
    }
    observed = registration_pico_preflight(question(), registration)
    assert observed["status"] == "BROAD_SEARCH_HIT_NO_INTERVENTION_MATCH"
    audit = registration_age_audit(
        question(), registration,
        [primary("Ketone monoester randomized trial in endurance athletes", 2025)],
    )
    assert audit["pico_relevance_preflight"]["status"] == "BROAD_SEARCH_HIT_NO_INTERVENTION_MATCH"
    assert audit["post_registration_bibliographic_leads"]["count"] is None
    assert audit["post_registration_bibliographic_leads"]["scope_note"] == "NOT_ESTIMABLE_FOR_UNMATCHED_REGISTRY_TOPIC"
    assert audit["novelty_confirmed"] is False


def test_intervention_matched_registered_review_retains_newer_study_leads():
    from scimed_scout.discovery.novelty import registration_pico_preflight
    registration = {
        "source": "PROSPERO", "source_record_id": "CRD420190000102",
        "title": "Ketone monoester supplementation during exercise: a review",
        "payload": {"year": 2019, "metadata": {"review_status": "Ongoing"}},
    }
    preflight = registration_pico_preflight(question(), registration)
    assert preflight["status"] == "POTENTIAL_INTERVENTION_MATCH"
    assert set(preflight["matched_intervention_terms"]) == {"ketone", "monoester"}
    audit = registration_age_audit(
        question(), registration,
        [primary("Ketone monoester randomized trial in endurance athletes", 2025)],
    )
    assert audit["post_registration_bibliographic_leads"]["count"] == 1
    assert audit["novelty_confirmed"] is False


def test_generic_intervention_requires_manual_relevance_check_not_false_exclusion():
    from scimed_scout.discovery.novelty import registration_pico_preflight
    candidate = SimpleNamespace(intervention_exposure_index_test="Standard care")
    registration = {
        "source": "OSF Registries", "source_record_id": "abc12",
        "title": "A clinical trial review", "payload": {},
    }
    audit = registration_pico_preflight(candidate, registration)
    assert audit["status"] == "UNKNOWN_INTERVENTION_TERMS"
    assert audit["scientific_exclusion_confirmed"] is False
