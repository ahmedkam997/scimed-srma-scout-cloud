from scripts.scimed_autonomous_worker import initial,run
from scripts.private_research_memory import load,brief
import json
import pytest

def test_dynamic_exploration_alternates_without_granting_qualification():
    state=initial();seen=[]
    def collect(*args,**kw):
        seen.append((args[0],kw["dynamic"]))
        return {"status":"SAMPLED","candidates":[],"dynamic_discovery":{"status":"SEARCHED_POSITIVE" if kw["dynamic"] else "NOT_SEARCHED"}}
    for i in range(4):
        result,_=run(state,collect,lambda x:None)
        assert result["qualification_granted"] is False and result["first_choice_count"]==0
    assert seen==[("Cardiology",True),("General Surgery",True),("Cardiology",False),("General Surgery",False)]

def test_private_memory_cannot_be_independent_or_qualified(tmp_path):
    p=tmp_path/"memory.json"
    data={"schema":"SCIMED_PRIVATE_RESEARCH_MEMORY_V1","external_transfer_allowed":False,"independent_test_use":False,"qualification_granted":False,"patterns":["compare trial outcomes"],"projects":[{"project_label":"Test surgery example","pattern_hypothesis":"surgery recovery","scientific_status":"DEVELOPMENT_EXAMPLE_ONLY","qualification_granted":False,"novelty_verified":False,"observed_distinct_labels":8}]}
    p.write_text(json.dumps(data))
    result=brief(load(p),"surgery recovery")
    assert result["examples"][0]["project_label"]=="Test surgery example"
    assert result["external_transfer_allowed"] is False
    data["independent_test_use"]=True;p.write_text(json.dumps(data))
    with pytest.raises(ValueError):load(p)
