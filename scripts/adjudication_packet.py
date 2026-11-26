"""Export or mechanically validate the adjudication packet from a report JSON."""
import argparse,json
from pathlib import Path
from scimed_scout.discovery.adjudication import validate
def main():
    p=argparse.ArgumentParser();p.add_argument("report",type=Path);p.add_argument("candidate_id");p.add_argument("--submission",type=Path);p.add_argument("--output",type=Path,required=True);a=p.parse_args()
    report=json.loads(a.report.read_text());package=report.get("package",report)
    candidates=[*package.get("options",[]),*package.get("provisional_options",[])]
    match=[c for c in candidates if c.get("candidate_id")==a.candidate_id]
    if len(match)!=1:raise SystemExit("candidate not found or ambiguous")
    packet=match[0]["research_dossier"]["study_centric_adjudication"]
    result=validate(packet,json.loads(a.submission.read_text())) if a.submission else packet
    a.output.write_text(json.dumps(result,ensure_ascii=False,indent=2)+"\n")
if __name__=="__main__":main()
