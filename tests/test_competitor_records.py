from scimed_scout.discovery.competitor_records import groups,audit,enrich_missing_abstracts
from scimed_scout.storage import CandidateRecord,ProjectRecord,SQLiteLedger
from scimed_scout.sources.base import SearchResult,SearchRecord
from scimed_scout.domain import SourceStatus

def row(source,rid,doi="",pmid="",title="Similar systematic review",text="",kind="PUBLISHED_REVIEW"):
    return {"source":source,"source_record_id":rid,"title":title,"evidence_type":kind,
            "payload":{"doi":doi,"metadata":{"pmid":pmid,"abstractText":text}}}

def test_identifier_bridge_is_order_independent_and_retains_richest():
    a=row("Crossref","a","https://doi.org/10.1000/a")
    b=row("Europe PMC","b","10.1000/a","123")
    c=row("PubMed","123",pmid="123",text="Abstract with source-backed methods and findings.")
    for records in ([a,b,c],[c,a,b]):
        g=groups(records)
        assert len(g)==1 and len(g[0]["variants"])==3
        assert g[0]["representative"]["source"]=="PubMed"
        assert audit(records)["duplicate_variants"]==2

def test_conflict_or_same_title_alone_does_not_merge():
    a=row("Crossref","a","10.1000/a",pmid="123")
    b=row("Europe PMC","b","10.1000/b",pmid="123")
    c=row("PubMed","456",pmid="456")
    assert len(groups([a,b,c]))==3
    assert audit([a,b,c])["conflicting_identifier_records"]==2
    assert len(groups([row("Crossref","x"),row("OpenAlex","y")]))==2

def test_registry_and_publication_stay_separate():
    a=row("PROSPERO","CRD123456789","10.1000/a",kind="REGISTRATION")
    b=row("Crossref","x","10.1000/a")
    assert len(groups([a,b]))==2

def test_enrichment_preserves_origin_and_rejects_conflicting_identity(tmp_path):
    a=row("Crossref","a","10.1000/a",pmid="123")
    b=row("Crossref","b","10.1000/b",pmid="456")
    class Client:
        def search(self,q,*,limit):
            records=[SearchRecord("Europe PMC","123","A review",doi="10.1000/a",
                metadata={"pmid":"123","abstractText":"Methods and results. "*20})] if "123" in q else [
                SearchRecord("Europe PMC","456","Other review",doi="10.1000/conflict",
                metadata={"pmid":"456","abstractText":"Unrelated evidence. "*20})]
            return SearchResult("Europe PMC",q,SourceStatus.SEARCHED_POSITIVE,records,len(records))
    with SQLiteLedger(tmp_path/"test.sqlite") as ledger:
        ledger.upsert_project(ProjectRecord("P","Cardiology"))
        ledger.upsert_candidate(CandidateRecord("C","P","Test","Cardiology"))
        for r in (a,b):
            ledger.upsert_external_evidence("C","PUBLISHED_REVIEW",r["source_record_id"],source=r["source"],title=r["title"],payload=r["payload"])
        out=enrich_missing_abstracts(ledger,"C",[a,b],Client(),limit=2)
        assert [x["status"] for x in out]==["ABSTRACT_ENRICHED","AMBIGUOUS_OR_MISSING_ABSTRACT"]
        saved={r["source_record_id"]:r for r in ledger.list_external_evidence("C","PUBLISHED_REVIEW")}
        assert saved["a"]["source"]=="Crossref"
        assert saved["a"]["payload"]["competitor_abstract_enrichment"]["source"]=="Europe PMC"
        assert not saved["b"]["payload"]["metadata"]["abstractText"]
