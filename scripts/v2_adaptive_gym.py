"""Isolated LDP/Aviary sequential retrieval experiment; no clinical qualification.
Development labels used only by terminal evaluator. No LLM calls or weight training.
"""
import asyncio
import json
import math
from dataclasses import dataclass, field
from importlib.metadata import version
from pathlib import Path
from aviary.core import Environment, Message, Tool, ToolCall, ToolRequestMessage
from ldp.agent import Agent
from scimed_scout.sources.pubmed import PubMedSource
from scripts.v2_aviary_gym import (REFERENCE, STRATEGIES, HF_REFERENCE, HF_STRATEGIES, bounded_ids)
from scripts.v2_historical_replay_dev import full_id_diagnostic

# Published review PMID 28588886, March 2016 cutoff (month-end approximation).
# Ten directly linked citations from table 1, not a complete trial-family gold set.
SURG_REF={"review_pmid":"28588886","linked_reports":dict.fromkeys(
    ["7677456","9282768","9230853","9189105","10027359","15609378",
     "19943593","14691696","8693426","8661828"]),
    "excluded_from_rct_oriented_report_metric":[]}
D='("1800/01/01"[dp] : "2016/03/31"[dp])'
P='(appendicitis[tiab] OR appendectom*[tiab] OR appendicectom*[tiab] OR "Appendectomy"[Mesh])'
L='(laparoscop*[tiab] OR "Laparoscopy"[Mesh])'
R='(randomized controlled trial[pt] OR random*[tiab] OR trial[tiab])'
N=f'{P} AND {L} AND (open[tiab] OR conventional[tiab]) AND {R} AND {D}'
B=f'{P} AND {L} AND {R} AND {D}'
SURG_STRATEGIES={"narrow":[(N,100)],"dual_route":[(N,50),(B,50)]}
CASES=[
 ("statins",REFERENCE,STRATEGIES,"development"),
 ("sglt2_hf",HF_REFERENCE,HF_STRATEGIES,"development"),
 ("appendectomy",SURG_REF,SURG_STRATEGIES,"transfer_development"),
]
THRESHOLDS=[0.0,2.0,5.0,1000000.0]

@dataclass
class State:
    phase: int=0
    valid: bool=True
    finished: bool=False
    ids: set=field(default_factory=set)
    trace: list=field(default_factory=list)
    reward: float=0.0
    recall: float|None=None
    counts: dict=field(default_factory=dict)

class SequentialGym(Environment[State]):
    def __init__(self,client,case,cache):
        self.client=client
        self.name,ref,self.strategies,self.split=case
        self.target=set(ref["linked_reports"])-set(ref["excluded_from_rct_oriented_report_metric"])
        self.cache=cache
        assert self.target
    async def reset(self):
        self.state=State()
        self.tools=[Tool.from_function(f) for f in (self.probe,self.narrow_top,self.expand,self.finish)]
        return [Message(content=json.dumps({"phase":"start","task":self.name}))],self.tools
    def _remember(self,action,result):
        self.state.trace.append({"action":action,**result})
        return json.dumps(result)
    def _cached(self,key,fn):
        if key not in self.cache:
            self.cache[key]=fn()
        return self.cache[key]
    def probe(self)->str:
        """Retrieve PubMed counts for narrow and broad queries without fetching citations."""
        routes=self.strategies["dual_route"]
        _,rows=self._cached("probe",lambda:bounded_ids(self.client,[(q,0) for q,_ in routes]))
        self.state.valid=all(r["complete_bounded"] for r in rows)
        self.state.counts={"narrow":rows[0].get("total"),"broad":rows[1].get("total")}
        self.state.phase=1
        return self._remember("probe",{"phase":"probed","valid":self.state.valid,**self.state.counts})
    def narrow_top(self)->str:
        """Retrieve the first 100 ranked PubMed identifiers from the narrow query."""
        ids,rows=self._cached("top",lambda:bounded_ids(self.client,self.strategies["narrow"]))
        self.state.valid=self.state.valid and all(r["complete_bounded"] for r in rows)
        self.state.ids.update(ids)
        self.state.phase=2
        return self._remember("narrow_top",{"phase":"ranked","valid":self.state.valid,"retrieved":len(self.state.ids)})
    def expand(self)->str:
        """Enumerate all matching identifiers from both bounded query routes."""
        def fetch():
            ids=set(); rows=[]
            for q,_ in self.strategies["dual_route"]:
                found,row=full_id_diagnostic(self.client,q); ids.update(found); rows.append(row)
            return ids,rows
        ids,rows=self._cached("expanded",fetch)
        self.state.valid=self.state.valid and all(r["complete"] for r in rows)
        self.state.ids.update(ids)
        self.state.phase=3
        return self._remember("expand",{"phase":"expanded","valid":self.state.valid,"retrieved":len(self.state.ids)})
    def finish(self)->str:
        """End development episode. This is not a scientific search stopping rule."""
        self.state.finished=True
        self.state.recall=len(self.state.ids & self.target)/len(self.target) if self.state.valid else None
        # Identifiers are screening workload proxies. No unlabelled record is a false positive.
        self.state.reward=self.state.recall-0.1*min(len(self.state.ids)/10000,1) if self.state.valid else -1.0
        return self._remember("finish",{"phase":"finished","valid":self.state.valid,"retrieved":len(self.state.ids)})
    async def step(self,action:ToolRequestMessage):
        if self.state.finished: raise RuntimeError("reset required")
        allowed={0:{"probe"},1:{"narrow_top"},2:{"expand","finish"},3:{"finish"}}
        if len(action.tool_calls)!=1 or action.tool_calls[0].function.name not in allowed[self.state.phase]:
            self.state.valid=False;self.state.finished=True
            return [Message(content="Invalid sequence")],-1.0,False,True
        obs=await self.exec_tool_calls(action)
        if not self.state.valid:
            self.state.finished=True
            return obs,-1.0,False,True
        return obs,self.state.reward if self.state.finished else 0.0,self.state.finished,False

class AdaptiveAgent(Agent):
    def __init__(self,threshold):
        super().__init__()
        self.threshold=threshold
    async def init_state(self,tools):
        return {"tools":tools,"ratio":None}
    async def get_asv(self,agent_state,obs):
        msg=json.loads(obs[-1].content)
        phase=msg["phase"]
        new=dict(agent_state)
        if phase=="start": action="probe"
        elif phase=="probed":
            new["ratio"]=msg["broad"]/max(msg["narrow"],1)
            action="narrow_top"
        elif phase=="ranked": action="expand" if new["ratio"]>=self.threshold else "finish"
        elif phase=="expanded": action="finish"
        else: raise ValueError("unexpected observation")
        tool=next(t for t in new["tools"] if t.info.name==action)
        return await Agent.wrap_action(ToolRequestMessage(tool_calls=[ToolCall.from_tool(tool)])),new,0.0

async def rollout(env,threshold):
    agent=AdaptiveAgent(threshold)
    obs,tools=await env.reset()
    state=await agent.init_state(tools)
    for _ in range(4):
        op,state,_=await agent.get_asv(state,obs)
        obs,reward,done,truncated=await env.step(op.value)
        if done or truncated:
            return {"threshold":threshold,"reward":reward,"recall":env.state.recall,
                    "retrieved":len(env.state.ids),"reference_count":len(env.target),
                    "actions":env.state.trace,"resolved":done and not truncated}
    raise RuntimeError("step budget exhausted")

def save_policy(path,threshold,train_cases,scores):
    payload={"schema":1,"threshold":threshold,"training_cases":train_cases,"scores":scores,
             "production_approved":False,"qualification_granted":False}
    path.write_text(json.dumps(payload,indent=2)+"\n")
def load_policy(path):
    data=json.loads(path.read_text())
    if data["schema"]!=1 or data["threshold"] not in THRESHOLDS or data["production_approved"]:
        raise ValueError("invalid experimental policy")
    return data["threshold"]

def assess_transfer(adaptive,baseline):
    """Fail closed: this gate is for experimental strategy selection only."""
    ok=(adaptive.get("resolved") is True and baseline.get("resolved") is True
        and adaptive.get("recall") is not None and baseline.get("recall") is not None
        and adaptive["recall"]>=0.95 and adaptive["recall"]>=baseline["recall"])
    return {"passed":ok,"experimental_policy_accepted":ok,
            "fallback":"always_expand" if not ok else None,
            "production_approved":False,"scientific_search_complete":False,
            "reason":"relative recall below conservative control or unresolved" if not ok else "single development transfer check only"}

async def run(client):
    train_results={}
    for case in CASES[:2]:
        env=SequentialGym(client,case,{})
        train_results[case[0]]=[await rollout(env,t) for t in THRESHOLDS]
    scores={t:sum(next(row["reward"] for row in rows if row["threshold"]==t) for rows in train_results.values())/len(train_results) for t in THRESHOLDS}
    valid=all(r["resolved"] for rows in train_results.values() for r in rows)
    if not valid: raise RuntimeError("unresolved development source; no policy saved")
    # Prefer simpler/high threshold in ties, never touch transfer labels during selection.
    chosen=max(THRESHOLDS,key=lambda t:(scores[t],t))
    path=Path("adaptive-policy.json")
    save_policy(path,chosen,list(train_results),scores)
    frozen=load_policy(path)
    env=SequentialGym(client,CASES[2],{})
    transfer=await rollout(env,frozen)
    baselines={"always_expand":await rollout(env,0.0),"never_expand":await rollout(env,1000000.0)}
    decision=assess_transfer(transfer,baselines["always_expand"])
    memory={"schema":1,"case":CASES[2][0],"trained_policy_threshold":frozen,"decision":decision,
            "observed_recall":transfer["recall"],"conservative_control_recall":baselines["always_expand"]["recall"],
            "recovery_strategy":"always_expand","qualification_granted":False}
    Path("adaptive-experience.json").write_text(json.dumps(memory,indent=2)+"\n")
    return {"aviary":version("fhaviary"),"ldp":version("ldp"),"development":train_results,
            "chosen_threshold":chosen,"policy_reloaded":True,"scores":scores,"transfer_safety_decision":decision,
            "transfer":{"case":CASES[2][0],"review":SURG_REF["review_pmid"],"adaptive":transfer,"baselines":baselines},
            "all_resolved":all(x["resolved"] for x in [transfer,*baselines.values()]),
            "independent_final_test":False,"llm_calls":0,"llm_weights_changed":False,
            "qualification_granted":False,"limitations":["two training cases","ten linked report references not complete RCT gold set","current PubMed index with publication-date cutoff","development-only stop and reward","policy selected on two cases, not validated scientific stopping rule"]}

def main():
    report=asyncio.run(run(PubMedSource(sort="relevance")))
    Path("adaptive-gym-report.json").write_text(json.dumps(report,indent=2)+"\n")
    print("ADAPTIVE_GYM "+json.dumps(report),flush=True)
    if not report["all_resolved"]:raise SystemExit("transfer unresolved")
if __name__=="__main__":main()
