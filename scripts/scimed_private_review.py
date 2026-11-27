"""Private operator utility. Never run this with reviewer secrets in public CI.
Imports an immutable provisional packet into a new local SQLite ledger.
It does not convert a bounded search into conclusive coverage.
"""
import argparse,json,os
from pathlib import Path
from scimed_scout.storage import SQLiteLedger,ProjectRecord,CandidateRecord,SearchLogRecord
from scimed_scout.domain import SourceStatus,CandidateStatus
from scimed_scout.discovery.scientific_verification_v2 import snapshot
from scripts.scimed_autonomous_scientist import private_adjudicate

def import_packet(raw,path):
    if path.exists():raise ValueError("refusing to overwrite an existing ledger")
    cdata=dict(raw["candidate"]);cdata["status"]=CandidateStatus.DISCOVERED
    c=CandidateRecord(**cdata)
    if c.project_id!="autonomous-scientist" or raw["packet"]["qualification_granted"] is not False:
        raise ValueError("expected provisional scientist packet")
    # A public artifact is an untrusted source of bibliographic leads. Preserve
    # no definitive coverage from it; independent operator must run real searches.
    if any(x["status"] not in ("PARTIAL","ACCESS_FAILED","NOT_SEARCHED") for x in raw["search_log"]):
        raise ValueError("public packet must not assert definitive search coverage")
    fd=os.open(path,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600);os.close(fd)
    try:
        with SQLiteLedger(path) as ledger:
            ledger.initialize()
            ledger.upsert_project(ProjectRecord(c.project_id,c.specialty,c.question_type))
            ledger.upsert_candidate(c)
            for r in raw["raw_source_rows"]:
                ledger.upsert_external_evidence(c.candidate_id,r["evidence_type"],str(r["source_record_id"]),source=r["source"],title=r["title"],payload=r["payload"])
            for row in raw["search_log"]:
                x=dict(row);x["status"]=SourceStatus(x["status"])
                if x["candidate_id"]!=c.candidate_id or x["project_id"]!=c.project_id:raise ValueError("cross-candidate log")
                ledger.append_search_log(SearchLogRecord(**x))
            if raw["packet"]["verification_v2"]["legacy_evidence_collision_risk"]:ledger.mark_legacy_evidence(c.candidate_id)
            p=snapshot(ledger,c)
            if p["verification_v2"]["snapshot_sha256"]!=raw["packet"]["verification_v2"]["snapshot_sha256"]:
                raise ValueError("snapshot mismatch: original evidence has changed")
            return p
    except Exception:
        path.unlink(missing_ok=True)
        raise


def recover_private(db,cid,seconds=300):
    """Run existing comprehensive source plan on operator-owned durable ledger.
    A timeout preserves committed rows; next invocation resumes failed routes.
    No LLM, no reviewer keys read, no auto qualification.
    """
    import time
    from scimed_scout.discovery.orchestrator import ReviewDiscoveryOrchestrator
    from scimed_scout.sources import build_default_source_clients
    if not db.is_file():raise ValueError("existing operator ledger required")
    if not 30<=seconds<=900:raise ValueError("recovery time outside 30–900 seconds")
    end=time.monotonic()+seconds
    def check():
        if time.monotonic()>end:raise TimeoutError("bounded recovery checkpoint")
    with SQLiteLedger(db) as ledger:
        c=ledger.get_candidate(cid)
        if c is None:raise ValueError("candidate not found")
        runner=ReviewDiscoveryOrchestrator(ledger,build_default_source_clients(),
           strict_rct_minimum=7,require_pico_signals=True,adaptive_search=True,
           adaptive_retrieval=True,cancellation_check=check)
        status="RECOVERY_COMPLETED"
        try:
            runner.verify_candidate(cid,limit_per_query=40,recover_only=True)
        except TimeoutError:status="TIME_BUDGET_CHECKPOINT"
        # Always export new source snapshot; prior signatures cannot authorize it.
        c=ledger.get_candidate(cid)
        result=snapshot(ledger,c)
        result["recovery_status"]=status
        result["qualification_granted"]=False
        return result

def write_private(path,result):
    fd=os.open(path,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600)
    with os.fdopen(fd,"w") as f:json.dump(result,f,indent=2)

def main():
    p=argparse.ArgumentParser(description=__doc__)
    sub=p.add_subparsers(dest="command",required=True)
    a=sub.add_parser("import-packet");a.add_argument("packet",type=Path);a.add_argument("db",type=Path);a.add_argument("--output",type=Path,required=True)
    b=sub.add_parser("adjudicate");b.add_argument("db",type=Path);b.add_argument("candidate_id");b.add_argument("--output",type=Path,required=True)
    d=sub.add_parser("recover");d.add_argument("db",type=Path);d.add_argument("candidate_id");d.add_argument("--seconds",type=int,default=300);d.add_argument("--output",type=Path,required=True)
    args=p.parse_args()
    if args.command=="import-packet":result=import_packet(json.loads(args.packet.read_text()),args.db)
    elif args.command=="recover":result=recover_private(args.db,args.candidate_id,args.seconds)
    else:
        if not args.db.is_file():raise ValueError("existing operator ledger required")
        result=private_adjudicate(args.db,args.candidate_id)
    write_private(args.output,result)
    print("qualification_granted",result.get("qualification_granted",False))

if __name__=="__main__":main()
