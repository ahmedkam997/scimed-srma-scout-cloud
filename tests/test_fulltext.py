from scimed_scout.fulltext import (
    EuropePMCFullTextFetcher,
    FullTextAcquisitionService,
    FullTextStatus,
    TextHTTPError,
    TextHttpClient,
    evidence_text_for_record,
    parse_jats_xml,
)
from scimed_scout.storage import CandidateRecord, ProjectRecord, SQLiteLedger


JATS = """<?xml version="1.0" encoding="UTF-8"?>
<article>
  <front>
    <article-meta>
      <abstract><p>This prospective study evaluated Test A against Histopathology in adults.</p></abstract>
    </article-meta>
  </front>
  <body>
    <sec>
      <title>Methods</title>
      <p>We enrolled 100 adults with suspected disease X. Every participant received Test A and Histopathology.</p>
      <p>The study used a prospective diagnostic accuracy design with consecutive recruitment.</p>
    </sec>
    <sec>
      <title>Results</title>
      <p>Test A correctly identified 40 of 50 diseased participants and 45 of 50 non-diseased participants.</p>
      <table-wrap>
        <label>Table 2</label>
        <caption><p>Diagnostic accuracy results</p></caption>
        <table><tbody><tr><td>TP 40</td><td>FN 10</td><td>FP 5</td><td>TN 45</td></tr></tbody></table>
      </table-wrap>
      <p>Sensitivity was 80% and specificity was 90%.</p>
    </sec>
  </body>
</article>
"""


def candidate():
    return CandidateRecord(
        candidate_id="C1",
        project_id="P1",
        title="Test A diagnostic accuracy",
        specialty="Radiology",
        question_type="DIAGNOSTIC_ACCURACY",
        review_question="What is the diagnostic accuracy of Test A?",
        population="Adults with suspected disease X",
        intervention_exposure_index_test="Test A",
        comparator_reference="Histopathology",
        outcomes=["sensitivity", "specificity"],
        eligible_designs=["diagnostic accuracy"],
    )


def test_jats_parser_preserves_sections_tables_and_chunks():
    full_text, chunks = parse_jats_xml(JATS, max_chunk_chars=220)
    assert "[Methods]" in full_text
    assert "[Results]" in full_text
    assert "TP 40" in full_text
    assert "TN 45" in full_text
    assert len(chunks) >= 3
    assert any(chunk.section == "Results" and "Sensitivity was 80%" in chunk.text for chunk in chunks)


def test_evidence_selector_prioritizes_results_for_synthesis():
    _, chunks = parse_jats_xml(JATS, max_chunk_chars=260)
    record = {
        "source_record_id": "S1",
        "title": "Test A study",
        "payload": {
            "metadata": {"abstract": "Test A diagnostic accuracy study."},
            "full_text": "present",
            "full_text_chunks": [chunk.to_dict() for chunk in chunks],
        },
    }
    selected = evidence_text_for_record(
        record,
        candidate(),
        purpose="SYNTHESIS",
        max_chunks=1,
        max_chars=4000,
    )
    assert "SECTION Results" in selected
    assert "Sensitivity was 80%" in selected or "TP 40" in selected


def test_europe_pmc_fetcher_uses_pmcid_and_returns_chunked_full_text():
    urls = []

    def loader(url):
        urls.append(url)
        return JATS

    fetcher = EuropePMCFullTextFetcher(TextHttpClient(loader=loader))
    result = fetcher.fetch({
        "source_record_id": "12345",
        "payload": {"metadata": {"pmcid": "PMC1234567", "isOpenAccess": "Y", "inEPMC": "Y"}},
    })

    assert result.status == FullTextStatus.ACQUIRED
    assert result.pmcid == "PMC1234567"
    assert urls == ["https://www.ebi.ac.uk/europepmc/webservices/rest/PMC1234567/fullTextXML"]
    assert "TP 40" in result.full_text
    assert result.chunks


def test_europe_pmc_fetcher_finds_pmcid_in_pubmed_articleids():
    fetcher = EuropePMCFullTextFetcher(TextHttpClient(loader=lambda url: JATS))
    result = fetcher.fetch({
        "source_record_id": "12345",
        "payload": {
            "metadata": {
                "articleids": [
                    {"idtype": "pubmed", "value": "12345"},
                    {"idtype": "pmc", "value": "PMC7654321"},
                ]
            }
        },
    })
    assert result.status == FullTextStatus.ACQUIRED
    assert result.pmcid == "PMC7654321"


def test_europe_pmc_fetcher_is_fail_closed_for_missing_or_unavailable_content():
    missing = EuropePMCFullTextFetcher(TextHttpClient(loader=lambda url: JATS)).fetch({
        "source_record_id": "12345",
        "payload": {"metadata": {}},
    })
    assert missing.status == FullTextStatus.NO_PMCID

    unavailable = EuropePMCFullTextFetcher(TextHttpClient(loader=lambda url: (_ for _ in ()).throw(
        TextHTTPError(404, "not found")
    ))).fetch({
        "source_record_id": "S1",
        "payload": {"metadata": {"pmcid": "PMC1234567"}},
    })
    assert unavailable.status == FullTextStatus.NOT_AVAILABLE


def test_acquisition_service_targets_uncertain_eligibility_and_persists_chunks(tmp_path):
    with SQLiteLedger(tmp_path / "fulltext.sqlite3") as ledger:
        ledger.upsert_project(ProjectRecord("P1", "Radiology"))
        ledger.upsert_candidate(candidate())
        ledger.upsert_external_evidence(
            "C1",
            "PRIMARY_STUDY",
            "S1",
            source="PubMed",
            title="Study 1",
            payload={
                "metadata": {"pmcid": "PMC1234567"},
                "study_eligibility_extraction": {"eligibility": "UNCERTAIN"},
            },
        )
        ledger.upsert_external_evidence(
            "C1",
            "PRIMARY_STUDY",
            "S2",
            source="PubMed",
            title="Study 2",
            payload={
                "metadata": {"pmcid": "PMC2222222"},
                "study_eligibility_extraction": {"eligibility": "ELIGIBLE"},
            },
        )

        service = FullTextAcquisitionService(
            ledger,
            EuropePMCFullTextFetcher(TextHttpClient(loader=lambda url: JATS)),
        )
        summary = service.run("C1", purpose="ELIGIBILITY")

        assert summary.records_considered == 1
        assert summary.acquired == 1
        records = {x["source_record_id"]: x for x in ledger.list_external_evidence("C1", "PRIMARY_STUDY")}
        assert "full_text" in records["S1"]["payload"]
        assert records["S1"]["payload"]["full_text_chunks"]
        assert "full_text" not in records["S2"]["payload"]


def test_manual_jats_attachment_is_normalized_and_chunked(tmp_path):
    with SQLiteLedger(tmp_path / "manual.sqlite3") as ledger:
        ledger.upsert_project(ProjectRecord("P1", "Radiology"))
        ledger.upsert_candidate(candidate())
        ledger.upsert_external_evidence(
            "C1",
            "PRIMARY_STUDY",
            "S1",
            source="PubMed",
            title="Study 1",
            payload={"metadata": {}},
        )

        result = FullTextAcquisitionService(ledger).attach_text(
            "C1",
            "S1",
            JATS,
            source_label="USER_JATS",
        )
        assert result["status"] == FullTextStatus.MANUAL_ATTACHED.value
        assert result["format"] == "JATS_XML"
        assert result["chunks"] >= 2
        stored = ledger.list_external_evidence("C1", "PRIMARY_STUDY")[0]["payload"]
        assert "TP 40" in stored["full_text"]
        assert stored["full_text_source"] == "USER_JATS"
