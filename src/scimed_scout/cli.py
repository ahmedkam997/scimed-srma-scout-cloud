from __future__ import annotations
import argparse, json, platform
from . import __version__
from .domain import SourceStatus
from .gates import final_decision

def health() -> dict[str, object]:
    return {"app":"SciMed SRMA Scout Cloud","version":__version__,"python":platform.python_version(),"status":"OK","source_statuses":[s.value for s in SourceStatus]}

def main() -> None:
    parser = argparse.ArgumentParser(prog="scimed-scout")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("health")
    gate = sub.add_parser("evaluate-gates")
    gate.add_argument("json_file")
    args = parser.parse_args()
    if args.command == "health":
        print(json.dumps(health(), indent=2))
    else:
        with open(args.json_file, encoding="utf-8") as handle:
            payload = json.load(handle)
        print(json.dumps(final_decision(payload), ensure_ascii=False, indent=2, default=str))

if __name__ == "__main__": main()
