import json
import subprocess
from scimed_scout.domain import SourceStatus
from scimed_scout.sources.prospero import ProsperoCliSource

def fake(total,*,duplicate=False,short=False,overreported=False):
    calls=[]
    def run(cmd):
        page=int(cmd[cmd.index("--page")+1]);calls.append(page)
        start=(page-1)*50
        ids=list(range(start,min(start+50,total)))
        if duplicate and page==2:ids[0]=0
        if short and page==1:ids=ids[:-1]
        if overreported:ids.append(9999)
        hits=[{"record_id":str(i),"title":"Protocol "+str(i)} for i in ids]
        return subprocess.CompletedProcess(cmd,0,stdout=json.dumps({"ok":True,"data":{"page":page,"page_size":50,"total_hits":total,"hits":hits}}),stderr="")
    return calls,run

def test_prospero_five_page_production_budget():
    for total in (62,180,207,250):
        calls,run=fake(total)
        r=ProsperoCliSource(runner=run).search("x",limit=8)
        assert r.status==SourceStatus.SEARCHED_POSITIVE
        assert len(r.records)==total and len(calls)==(total+49)//50
    calls,run=fake(251)
    r=ProsperoCliSource(runner=run).search("x")
    assert r.status==SourceStatus.PARTIAL
    assert len(calls)<=6  # five full-scope pages, at most one title supplement

def test_prospero_rejects_overlap_short_page_and_extra_hits():
    for flags in ({"duplicate":True},{"short":True},{"overreported":True}):
        _,run=fake(62,**flags)
        assert ProsperoCliSource(runner=run).search("x").status==SourceStatus.PARTIAL

def test_prospero_rejects_wrong_page_and_noninteger_count():
    for data in ({"total_hits":0,"hits":[],"page":2},{"total_hits":False,"hits":[]},{"total_hits":"0","hits":[]}):
        def run(cmd):
            return subprocess.CompletedProcess(cmd,0,stdout=json.dumps({"ok":True,"data":data}),stderr="")
        assert ProsperoCliSource(runner=run).search("x").status==SourceStatus.PARTIAL
