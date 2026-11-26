
"""Real publication-family and contrast controls. Labels never passed to extractors."""
import json
from pathlib import Path
from scimed_scout.sources.pubmed import PubMedSource
from scimed_scout.sources.pubmed_abstracts import parse_efetch,_fetch
from scimed_scout.discovery.structured_extraction_v2 import abstract_ratios,report_role_cues
from scimed_scout.discovery.trial_family import audit_trial_families
CASES={
 "31535829":("NCT03036124","primary",(.74,.65,.85)),
 "30895697":("NCT03036124","protocol",None),
 "33787831":("NCT03036124","secondary",None),
 "36027570":("NCT03619213","primary",(.82,.73,.92)),
 "36190011":("NCT03619213","secondary",None),
 "32865377":("NCT03057977","primary",(.75,.65,.86)),
 "34861154":("NCT03057977","secondary",None),
 "29067426":("ISRCTN80500123","primary",(.61,.31,1.21)),
 "29945673":("ISRCTN80500123","secondary",None),
}
def main():
    ids=list(CASES)
    report={"version":"V2_CONTRAST_AND_FAMILY_REAL_CONTROLS","source":"PubMed EFetch","requested":len(ids),"new_ai_requests":0,"qualification_granted":False,"reports":[]}
    try:
        found,diag=parse_efetch(_fetch(PubMedSource(),ids),ids)
        report.update(retrieved=len(found),**diag)
    except Exception as ex:
        report.update(retrieved=0,status="ACCESS_UNRESOLVED",error_type=type(ex).__name__);found={}
    rows=[]
    for pmid,(family,role,expected) in CASES.items():
        m=found.get(pmid)
        if not m:
            report["reports"].append({"pmid":pmid,"expected_family":family,"expected_role":role,"status":"NOT_RETRIEVED"});continue
        row={"source":"PubMed","source_record_id":pmid,"title":m["pubmed_efetch_title"],"payload":{"url":f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/","metadata":m}}
        rows.append(row)
        leads=abstract_ratios(row);roles=report_role_cues(row)
        report["reports"].append({"pmid":pmid,"expected_family":family,"expected_role":role,"role_cues":roles["cues"],"ratio_leads":len(leads),"expected_ratio":expected,
            "exact_ratio_match":any((r["ratio"],*r["reported_ci"])==expected for r in leads) if expected else None,"eligible":False})
    from scimed_scout.discovery.registration_enrichment import enrich_fair
    # Actual open-access recovery only for reports lacking explicit registry IDs.
    rows,first=enrich_fair(rows,max_lookups=3)
    rows,second=enrich_fair(rows,max_lookups=3,previous=first)
    report["fulltext_link_recovery"]={"first_calls":first["source_calls"],"second_calls":second["source_calls"],"attempts":second["attempts"]}
    audit=audit_trial_families(rows)
    actual={r["report_id"]:f["registration_id"] for f in audit["families"] for r in f["reports"]}
    report.update(registry_linked_families=audit["registry_linked_families"],linked_reports=audit["registry_linked_reports"],unlinked_reports=len(audit["unlinked_reports"]),ambiguous_reports=len(audit["ambiguous_reports"]),
        observed_families={f["registration_id"]:[r["report_id"] for r in f["reports"]] for f in audit["families"]},
        exact_family_matches=sum(actual.get(p)==f for p,(f,_,_) in CASES.items()),expected_family_count=len({x[0] for x in CASES.values()}),
        wrong_family_links=[p for p,v in actual.items() if CASES[p][0]!=v],independence_confirmed=False)
    Path("v2-real-family-contrast.json").write_text(json.dumps(report,indent=2)+"\n")
    print("V2_REAL_FAMILY_CONTRAST "+json.dumps(report),flush=True)
if __name__=="__main__":main()
