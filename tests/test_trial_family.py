from scimed_scout.trials import (
    FamilyLinkStatus,
    TrialFamilyResolver,
    TrialPublication,
    extract_registry_ids,
    normalize_doi,
)


def verified_pub(pid, title, **kwargs):
    return TrialPublication(
        publication_id=pid,
        title=title,
        independence_verified=True,
        randomization_verified=True,
        eligibility_verified=True,
        **kwargs,
    )


def test_identifier_normalization_and_extraction():
    assert normalize_doi("https://doi.org/10.1000/ABC.") == "10.1000/abc"
    ids = extract_registry_ids("Registered as NCT12345678 and ISRCTN12345678.")
    assert ids == ["NCT12345678", "ISRCTN12345678"]


def test_shared_registry_id_merges_primary_and_followup():
    primary = verified_pub("P1", "Primary randomized trial", registry_ids=["NCT12345678"], randomized_n=200)
    followup = TrialPublication(
        publication_id="P2",
        title="Long-term follow-up of the randomized trial",
        registry_ids=["nct12345678"],
        randomized_n=200,
    )
    audit = TrialFamilyResolver().audit([primary, followup])
    assert len(audit.families) == 1
    assert audit.families[0].publication_ids == ["P1", "P2"]
    assert audit.verified_independent_population_count == 1
    assert audit.possible_links == []


def test_same_acronym_and_sample_size_is_possible_not_automatic_merge():
    a = verified_pub("A", "Trial of drug A in condition X", acronym="STAR", randomized_n=120)
    b = verified_pub("B", "STAR follow-up outcomes in condition X", acronym="STAR", randomized_n=120)
    audit = TrialFamilyResolver().audit([a, b])
    assert len(audit.families) == 2
    assert len(audit.possible_links) == 1
    assert audit.possible_links[0].status == FamilyLinkStatus.POSSIBLE_SAME_FAMILY


def test_title_similarity_alone_does_not_merge():
    a = verified_pub("A", "Randomized trial of therapy in severe disease")
    b = verified_pub("B", "Randomized trial of therapy in severe disease at one year")
    audit = TrialFamilyResolver().audit([a, b])
    assert len(audit.families) == 2
    assert audit.pair_links[0].status != FamilyLinkStatus.VERIFIED_SAME_FAMILY


def test_possible_link_is_type_a_only_when_it_can_drop_below_four():
    pubs = [
        verified_pub(f"P{i}", f"Independent randomized trial {i}", manually_verified_family_id=f"F{i}")
        for i in range(1, 5)
    ]
    pubs[0].acronym = "ALPHA"
    pubs[0].randomized_n = 100
    pubs[1].acronym = "ALPHA"
    pubs[1].randomized_n = 100

    audit = TrialFamilyResolver().audit(pubs)
    assert audit.verified_independent_population_count == 4
    assert audit.minimum_possible_verified_independent_count() == 3
    assert audit.family_uncertainty_is_decision_changing()

    extra = verified_pub("P5", "Independent randomized trial 5", manually_verified_family_id="F5")
    audit5 = TrialFamilyResolver().audit(pubs + [extra])
    assert audit5.verified_independent_population_count == 5
    assert audit5.minimum_possible_verified_independent_count() == 4
    assert not audit5.family_uncertainty_is_decision_changing()
