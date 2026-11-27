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
    cdata=dict(raw["candidate"]);cdata["status"]=CandidateStatus(cdata["status"])
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

def write_private(path,result):
    fd=os.open(path,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600)
    with os.fdopen(fd,"w") as f:json.dump(result,f,indent=2)

def main():
    p=argparse.ArgumentParser(description=__doc__)
    sub=p.add_subparsers(dest="command",required=True)
    a=sub.add_parser("import-packet");a.add_argument("packet",type=Path);a.add_argument("db",type=Path);a.add_argument("--output",type=Path,required=True)
    b=sub.add_parser("adjudicate");b.add_argument("db",type=Path);b.add_argument("candidate_id");b.add_argument("--output",type=Path,required=True)
    args=p.parse_args()
    if args.command=="import-packet":result=import_packet(json.loads(args.packet.read_text()),args.db)
    else:
        if not args.db.is_file():raise ValueError("existing operator ledger required")
        result=private_adjudicate(args.db,args.candidate_id)
    write_private(args.output,result)
    print("qualification_granted",result.get("qualification_granted",False))

if __name__=="__main__":main()
