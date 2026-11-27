"""Private held-out evaluation. Labels and keys never belong in scheduled CI."""
import argparse,json,math,re
from pathlib import Path
from scripts.academy_benchmark import audit_manifest,read_keys,model_observation
from scimed_scout.discovery.scientific_verification_v2 import digest,authenticated

def wilson(k,n):
    if not n:return None
    z=1.95996398454;p=k/n;den=1+z*z/n
    mid=(p+z*z/(2*n))/den;rad=z*math.sqrt(p*(1-p)/n+z*z/(4*n*n))/den
    return [max(0,mid-rad),min(1,mid+rad)]

def evaluate_frozen(manifest,keys,predictions,freeze):
    admission=audit_manifest(manifest,keys)
    if not admission["benchmark_ready"]:
        return {"status":"BENCHMARK_NOT_ADMITTED","admission":admission,"independent_validation_passed":False}
    # External independent operators must freeze predictions BEFORE unblinding;
    # the signed attestation binds the actual data, observations, model and output.
    signed,_=authenticated(freeze,keys)
    cases=[c for c in manifest["cases"] if c["split"]=="test"]
    obs=[model_observation(c) for c in cases]
    if (signed.get("schema")!="SCIMED_FROZEN_EVALUATION_V1"
        or signed.get("manifest_sha256")!=digest(manifest)
        or signed.get("observation_sha256")!=digest(obs)
        or signed.get("predictions_sha256")!=digest(predictions)
        or not re.fullmatch(r"[0-9a-f]{40}",str(signed.get("worker_commit","")))
        or signed.get("predictions_frozen_before_unblinding") is not True
        or signed.get("test_data_not_used_for_training") is not True):
        raise ValueError("missing independent frozen-evaluation attestation")
    if not isinstance(predictions,list):raise ValueError("predictions must be a list")
    by_id={r["case_id"]:r for r in predictions}
    if len(by_id)!=len(predictions) or set(by_id)!={c["case_id"] for c in cases}:
        raise ValueError("exact test-case inventory required")
    positives=negatives=tp=fp=missed=correct_route=abstained=0
    for c in cases:
        row=by_id[c["case_id"]];pred=row.get("prediction")
        if pred not in ("UPDATE","NOVEL","NEGATIVE","UNRESOLVED"):raise ValueError("invalid prediction")
        actual=c["opportunity"];pos=actual!="NEGATIVE";positive=pred in ("UPDATE","NOVEL")
        positives+=pos;negatives+=not pos
        tp+=pos and positive;fp+=(not pos) and positive
        missed+=pos and not positive;correct_route+=pos and pred==actual
        abstained+=pred=="UNRESOLVED"
    sensitivity=tp/positives if positives else None
    return {"status":"SCORED_INDEPENDENT_TEST","n":len(cases),"positives":positives,"negatives":negatives,
        "true_positive":tp,"false_positive":fp,"missed_positive":missed,"abstained":abstained,
        "positive_detection_sensitivity":sensitivity,"sensitivity_wilson95":wilson(tp,positives),
        "negative_case_false_positive_fraction":fp/negatives if negatives else None,
        "false_positive_wilson95":wilson(fp,negatives),"correct_positive_route":correct_route,
        "meets_exploratory_detection_targets":sensitivity is not None and sensitivity>=.8 and fp==0,
        "independent_validation_passed":False,
        "limitation":"Opportunity triage evaluation only. Scientific qualification, extraction accuracy and prospective clinical evaluation require separate validation. Attestation does not itself prove independence."}

def main():
    p=argparse.ArgumentParser()
    p.add_argument("manifest",type=Path);p.add_argument("--keys",type=Path,required=True)
    p.add_argument("--predictions",type=Path,required=True);p.add_argument("--freeze",type=Path,required=True)
    p.add_argument("--output",type=Path,required=True);a=p.parse_args()
    report=evaluate_frozen(json.loads(a.manifest.read_text()),read_keys(a.keys),
        json.loads(a.predictions.read_text()),json.loads(a.freeze.read_text()))
    a.output.write_text(json.dumps(report,indent=2)+"\n")

if __name__=="__main__":main()
