from scimed_scout.discovery.registry_anchors import extract,derive_registry
from scimed_scout.discovery.rct_first import comparison_rows,family_summary
from scimed_scout.discovery.evidence_first import _record
from scimed_scout.sources.base import SearchRecord

def fixture():
    n="NCT05413447"
    r=_record(SearchRecord("PubMed","39217271","Digital consults in heart failure care: a randomized controlled trial.",year=2024,metadata={"pubtype":["Randomized Controlled Trial"],"trial_registration_ids":[n],"abstractText":"Patients with heart failure were randomized to receive usual care or digital consults."}))
    # Synthetic registry response for contract tests; real PubMed IDs are source references,
    # not a claim that this fixture is an exact downloaded registry response.
    s={"protocolSection":{"identificationModule":{"nctId":n},"designModule":{"studyType":"INTERVENTIONAL","designInfo":{"allocation":"RANDOMIZED","interventionModel":"PARALLEL"}},"conditionsModule":{"conditions":["heart failure"]},"armsInterventionsModule":{"armGroups":[{"type":"EXPERIMENTAL","interventionNames":["Behavioral: digital consults"]},{"type":"ACTIVE_COMPARATOR","interventionNames":["Other: usual care"]}]}}}
    return n,r,s

def test_registry_anchor_requires_corroborated_published_comparison():
    n,r,s=fixture()
    a,status=extract(s,n,r)
    assert status=="ANCHOR" and a["pair"][:2]==("heart failure","digital consults")
    assert a["family_cues"]==1 and a["comparator"]=="usual care"
    a,status=extract(s,"NCT00000000",r)
    assert a is None and status=="IDENTITY_MISMATCH"
    r["payload"]["metadata"]["abstractText"]="Patients received digital consults."
    assert extract(s,n,r)[0] is None

def test_complex_and_shared_arms_not_simplified():
    n,r,s=fixture()
    s["protocolSection"]["armsInterventionsModule"]["armGroups"][0]["interventionNames"].append("Other: usual care")
    assert extract(s,n,r)[0] is None

def test_registry_lookups_are_deduplicated_and_not_eligibility():
    n,r,s=fixture()
    calls=[]
    def lookup(k):
        calls.append(k);return s
    a,audit=derive_registry([r,r],[],lookup=lookup)
    assert len(calls)==1 and len(a)==1 and audit[0]["status"]=="ANCHOR"
    assert a[0]["family_cues"]==1
    _,buckets=comparison_rows(a[0]["pair"],[r],extra_controls=(a[0]["comparator"],))
    assert family_summary(buckets["usual care"])["confirmed_independent_eligible_trials"] is None
    assert family_summary(buckets["usual care"])["family_leads"]==1

def test_custom_comparator_not_limited_to_fixed_dictionary():
    r=_record(SearchRecord("PubMed","37634148","Pulsed field ablation versus conventional thermal ablation in atrial fibrillation: randomized trial",year=2023,metadata={"pubtype":["Randomized Controlled Trial"]}))
    p=("atrial fibrillation","pulsed field ablation",(),())
    _,b=comparison_rows(p,[r],extra_controls=("conventional thermal ablation",))
    assert len(b["conventional thermal ablation"])==1
