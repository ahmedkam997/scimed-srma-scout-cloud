"""Trusted operator utility: sign one reconciled submission with one reviewer key.
The output approval is not scientific evidence by itself. Never commit keys,
submissions containing copyrighted full texts, or private reviewer material.
"""
import argparse,json,os
from pathlib import Path
from scimed_scout.discovery.scientific_verification_v2 import signature
def main():
    p=argparse.ArgumentParser();p.add_argument("submission",type=Path);p.add_argument("reviewer");p.add_argument("--key-file",type=Path,required=True);p.add_argument("--output",type=Path,required=True);a=p.parse_args()
    data=json.loads(a.submission.read_text());key=bytes.fromhex(a.key_file.read_text().strip())
    if len(key)<32:raise SystemExit("reviewer key must have at least 32 random bytes")
    a.output.write_text(json.dumps({"reviewer":a.reviewer,"signature":signature(data,a.reviewer,key)},indent=2)+"\n")
if __name__=="__main__":main()
