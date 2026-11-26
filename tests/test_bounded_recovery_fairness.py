from scimed_scout.discovery.novelty import DiscoveryNoveltyService
from scimed_scout.storage import CandidateRecord,ProjectRecord,SQLiteLedger

class Assessor:
    def __init__(self):self.batches=[]
    def assess_many(self,c,rows):
        self.batches.append([r["evidence_type"] for r in rows])
        return []
    def assess(self,c,r):raise AssertionError("bounded recovery must not starve registration queue with individual review repairs")

def test_bounded_recovery_reserves_registration_batch_slots(tmp_path):
    a=Assessor()
    with SQLiteLedger(tmp_path/"fair.sqlite") as ledger:
        ledger.upsert_project(ProjectRecord("P","Cardiology"))
        ledger.upsert_candidate(CandidateRecord("C","P","Question","Cardiology",population="hypertension",intervention_exposure_index_test="renal denervation"))
        for kind,total in (("PUBLISHED_REVIEW",35),("REGISTRATION",25)):
            for i in range(total):
                ledger.upsert_external_evidence("C",kind,f"{kind}-{i}",source="PubMed" if kind=="PUBLISHED_REVIEW" else "OSF Registries",title=f"Review {i} of renal denervation",payload={"year":2025})
        service=DiscoveryNoveltyService(ledger,a,max_reviews=12,max_registrations=8,batch_size=5,bounded_recovery=True)
        out=service.assess_candidate("C",recovery=True)
        assert [len(x) for x in a.batches]==[5,5,2,5,3]
        assert a.batches[-1][0]=="REGISTRATION"
        assert out["published_reviews_prefiltered_out"]==23
        assert out["registrations_prefiltered_out"]==17
        assert not ledger.get_candidate("C").metadata["discovery_competitor_assessment_complete"]

def test_unverified_cutoff_retried_and_date_attempts_rotate(tmp_path):
    class Resolver:
        def __init__(self):self.ids=[]
        def resolve(self,r):
            self.ids.append(r["source_record_id"])
            return None
    resolver=Resolver()
    with SQLiteLedger(tmp_path/"dates.sqlite") as ledger:
        ledger.upsert_project(ProjectRecord("P","Cardiology"))
        ledger.upsert_candidate(CandidateRecord("C","P","Question","Cardiology"))
        for i in range(3):
            ledger.upsert_external_evidence("C","PUBLISHED_REVIEW",str(i),source="PubMed",title=f"Review {i}",payload={"year":2025,"metadata":{"last_search_date":"2024"}})
        service=DiscoveryNoveltyService(ledger,Assessor(),search_date_resolver=resolver,max_fulltext_reviews=1)
        for _ in range(3):
            service._resolve_search_dates("C",ledger.list_external_evidence("C","PUBLISHED_REVIEW"))
        assert resolver.ids==["0","1","2"]
        assert all(r["payload"]["discovery_search_date_attempts"]==1 for r in ledger.list_external_evidence("C","PUBLISHED_REVIEW"))


def test_failed_date_attempt_survives_semantic_persistence(tmp_path):
    class Resolver:
        def resolve(self,r):return None
    with SQLiteLedger(tmp_path/"persist.sqlite") as ledger:
        ledger.upsert_project(ProjectRecord("P","Cardiology"))
        ledger.upsert_candidate(CandidateRecord("C","P","Question","Cardiology"))
        ledger.upsert_external_evidence("C","PUBLISHED_REVIEW","1",source="PubMed",title="Review",payload={"year":2025})
        service=DiscoveryNoveltyService(ledger,Assessor(),search_date_resolver=Resolver(),max_fulltext_reviews=1)
        service.assess_candidate("C")
        assert ledger.list_external_evidence("C","PUBLISHED_REVIEW")[0]["payload"]["discovery_search_date_attempts"]==1
