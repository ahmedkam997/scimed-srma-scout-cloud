from scimed_scout.discovery.registration_enrichment import extract_registration,enrich_records
from scimed_scout.discovery.trial_family import audit_trial_families

def row(pmid="123",pmcid="PMC123456",**meta):
    return {"source":"Europe PMC","source_record_id":pmid,"title":"Secondary analysis of trial",
        "payload":{"metadata":{"pmid":pmid,"pmcid":pmcid,**meta}}}

def xml(text,pmid="123",section="Methods"):
    return f'<article><front><article-meta><article-id pub-id-type="pmid">{pmid}</article-id><article-id pub-id-type="pmc">123456</article-id></article-meta></front><body><sec><title>{section}</title><p>{text}</p></sec></body></article>'.encode()

def test_identity_verified_methods_registration_collapses_known_family():
    a=row("999",trial_registration_id="NCT03619213")
    b=row()
    data=xml("The trial is registered with ClinicalTrials.gov (NCT03619213).")
    revised,report=enrich_records([a,b],fetcher=lambda _:data)
    assert report["source_calls"]==1 and report["records_linked"]==1
    assert audit_trial_families(revised)["conservative_family_lead_count"]==1
    assert not report["independence_confirmed"]
    assert revised[1]["payload"]["metadata"]["registration_enrichment_evidence"]["pmid"]=="123"
    assert "trial_registration_id" not in b["payload"]["metadata"]

def test_wrong_article_background_or_multiple_ids_not_linked():
    c=row()
    statement="The trial is registered with ClinicalTrials.gov (NCT03619213)."
    assert extract_registration(c,xml(statement,pmid="999")) is None
    assert extract_registration(c,xml(statement,section="Discussion")) is None
    assert extract_registration(c,xml("Previous studies included NCT03619213.")) is None
    assert extract_registration(c,xml(statement+" Comparison trial NCT00000001.")) is None

def test_budget_and_failed_access_not_negative_evidence():
    calls=[]
    def fetch(url):
        calls.append(url)
        raise TimeoutError()
    rows=[row(str(i),f"PMC12345{i}") for i in range(5)]
    revised,report=enrich_records(rows,fetcher=fetch,max_lookups=99)
    assert len(calls)==3 and revised==rows
    assert all(a["status"]=="ACCESS_UNRESOLVED" for a in report["attempts"])

def test_unsafe_xml_rejected():
    assert extract_registration(row(),b'<!DOCTYPE article [<!ENTITY x "abc">]><article/>') is None


def oai(article):
    return (b'<OAI-PMH xmlns="http://www.openarchives.org/OAI/2.0/"><GetRecord>'
            b'<record><metadata>'+article+b'</metadata></record></GetRecord></OAI-PMH>')

def test_official_oai_fallback_after_timeout_preserves_identity_and_provenance():
    a=row("999",trial_registration_id="NCT03619213")
    b=row()
    calls=[]
    def fetch(url):
        calls.append(url)
        if "ebi.ac.uk" in url:raise TimeoutError()
        return oai(xml("The trial is registered with ClinicalTrials.gov (NCT03619213)."))
    revised,report=enrich_records([a,b],fetcher=fetch,max_lookups=2)
    assert len(calls)==report["source_calls"]==2
    assert report["records_linked"]==1
    assert report["attempts"][0]["routes"][0]["error"]=="TIMEOUT"
    assert report["attempts"][0]["routes"][1]["route"]=="NCBI_PMC_OAI"
    evidence=revised[1]["payload"]["metadata"]["registration_enrichment_evidence"]
    assert evidence["source_url"]==calls[1]
    assert audit_trial_families(revised)["conservative_family_lead_count"]==1
    assert not report["independence_confirmed"]

def test_oai_wrong_article_and_rights_error_fail_closed():
    statement="The trial is registered with ClinicalTrials.gov (NCT03619213)."
    assert extract_registration(row(),oai(xml(statement,pmid="999"))) is None
    denied=b'<OAI-PMH xmlns="http://www.openarchives.org/OAI/2.0/"><error code="cannotDisseminateFormat">Rights</error></OAI-PMH>'
    assert extract_registration(row(),denied) is None
    revised,report=enrich_records([row()],fetcher=lambda _:denied,max_lookups=2)
    assert report["source_calls"]==2 and report["records_linked"]==0
    assert report["attempts"][0]["status"]=="ACCESS_UNRESOLVED"

def test_fallback_does_not_exceed_one_request_budget():
    calls=[]
    def fail(url):
        calls.append(url)
        raise TimeoutError()
    _,report=enrich_records([row()],fetcher=fail,max_lookups=1)
    assert len(calls)==report["source_calls"]==1
