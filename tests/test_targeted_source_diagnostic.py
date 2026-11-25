from scripts.targeted_source_diagnostic import jats_status,bioc_status,registry_refs
import json

def test_oai_diagnostics():
    assert jats_status(b'<OAI-PMH xmlns="http://www.openarchives.org/OAI/2.0/"><error code="cannotDisseminateFormat"/></OAI-PMH>')=="OAI_cannotDisseminateFormat"
    assert jats_status(b'<article><front/></article>')=="METADATA_ONLY"
    assert jats_status(b'<article><body/></article>')=="JATS_BODY_PRESENT"
    assert jats_status(b'<html/>')=="NOT_JATS_ARTICLE"
    assert jats_status(b'not XML')=="NOT_XML"

def test_bioc_own_trial_only_and_identity():
    obj=[{"documents":[{"id":"123","passages":[{"infons":{"section_type":"METHODS"},"text":"The trial is registered with ClinicalTrials.gov (NCT03619213)."}]}]}]
    raw=json.dumps(obj).encode()
    assert bioc_status(raw,"123","PMC123456")["registration_leads"]==["NCT03619213"]
    assert bioc_status(raw,"999","PMC999999")["status"]=="IDENTITY_UNRESOLVED"
    obj[0]["documents"][0]["passages"][0]["infons"]["section_type"]="DISCUSS"
    assert bioc_status(json.dumps(obj).encode(),"123","PMC123456")["status"]=="NO_UNAMBIGUOUS_METHODS_LINK"

def test_registry_reference_types_are_not_merged():
    obj={"protocolSection":{"identificationModule":{"nctId":"NCT03619213"},"referencesModule":{"references":[{"pmid":"123","type":"BACKGROUND"},{"pmid":"456","type":"RESULT"},{"pmid":"789","type":"DERIVED"}]}}}
    r=registry_refs(json.dumps(obj).encode(),"NCT03619213",["123","456","789","000"])
    assert r["exact_pmids"]=={"123":["BACKGROUND"],"456":["RESULT"],"789":["DERIVED"],"000":[]}
    assert r["auto_merge"] is False
    assert registry_refs(json.dumps(obj).encode(),"NCT00000001",[])["status"]=="REGISTRY_ID_MISMATCH"
