"""Aviary/LDP task-level curriculum pilot on published report controls.
Role cues and extracted ratio leads are not eligibility or verified endpoint data.
"""
import asyncio,json
from dataclasses import dataclass,field
from pathlib import Path
from aviary.core import Environment,Message,Tool,ToolCall,ToolRequestMessage
from ldp.agent import Agent
from scimed_scout.sources.pubmed import PubMedSource
from scimed_scout.sources.pubmed_abstracts import parse_efetch,_fetch
from scimed_scout.discovery.structured_extraction_v2 import abstract_ratios,report_role_cues
from scripts.v2_real_family_contrast import CASES

@dataclass
class State:
    phase:int=0
    decision:str=""
    cues:list=field(default_factory=list)
    leads:list=field(default_factory=list)

class ReportGym(Environment[State]):
    def __init__(self,row):
        self.row=row
    async def reset(self):
        self.state=State()
        self.tools=[Tool.from_function(x) for x in (self.inspect_report,self.extract_contrasts,self.defer_report)]
        return [Message(content=json.dumps({"phase":"start","task":"identify report role cues and retrieve explicit ratio leads"}))],self.tools
    def inspect_report(self)->str:
        """Inspect the publication metadata and abstract for role cues."""
        self.state.cues=report_role_cues(self.row)["cues"]
        self.state.phase=1
        return json.dumps({"phase":"inspected","cues":self.state.cues})
    def extract_contrasts(self)->str:
        """Extract explicit reported ratios and confidence intervals, without pooling."""
        self.state.leads=abstract_ratios(self.row)
        self.state.decision="extract"
        self.state.phase=2
        return json.dumps({"phase":"finished","candidate_leads":len(self.state.leads)})
    def defer_report(self)->str:
        """Defer this report to human review; never exclude it or count trial independence."""
        self.state.decision="defer"
        self.state.phase=2
        return json.dumps({"phase":"finished","disposition":"requires_review"})
    async def step(self,action):
        allowed={0:{"inspect_report"},1:{"extract_contrasts","defer_report"},2:set()}
        if len(action.tool_calls)!=1 or action.tool_calls[0].function.name not in allowed[self.state.phase]:
            return [Message(content="invalid sequence")],-1,False,True
        obs=await self.exec_tool_calls(action)
        return obs,0.0,self.state.phase==2,False

class CueAgent(Agent):
    async def init_state(self,tools): return tools
    async def get_asv(self,state,obs):
        m=json.loads(obs[-1].content)
        action="inspect_report"
        if m["phase"]=="inspected":
            cues=set(m["cues"])
            action="extract_contrasts" if "RCT_PUBLICATION_TYPE_CUE" in cues and not cues.intersection({"SECONDARY_ANALYSIS_CUE","PROTOCOL_CUE","REVIEW_CUE"}) else "defer_report"
        tool=next(t for t in state if t.info.name==action)
        return await Agent.wrap_action(ToolRequestMessage(tool_calls=[ToolCall.from_tool(tool)])),state,0.0

async def run_one(row):
    env=ReportGym(row);agent=CueAgent()
    obs,tools=await env.reset();state=await agent.init_state(tools)
    for _ in range(2):
        op,state,_=await agent.get_asv(state,obs)
        obs,_,done,trunc=await env.step(op.value)
        if trunc: raise RuntimeError("invalid sequence")
        if done:return env.state
    raise RuntimeError("unfinished")
async def main_async():
    ids=list(CASES)
    found,diag=parse_efetch(_fetch(PubMedSource(),ids),ids)
    rows=[]
    for pmid,m in found.items():
        if pmid not in CASES:continue
        row={"source":"PubMed","source_record_id":pmid,"title":m["pubmed_efetch_title"],
             "payload":{"url":f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/","metadata":m}}
        state=await run_one(row)
        _,role,expected=CASES[pmid] # scorer only, after episode
        match=any((r["ratio"],*r["reported_ci"])==expected for r in state.leads) if expected else None
        rows.append({"pmid":pmid,"expected_role":role,"decision":state.decision,"cues":state.cues,
                     "lead_count":len(state.leads),"reference_ratio_found":match,
                     "routing_match":state.decision==("extract" if role=="primary" else "defer"),
                     "eligibility_confirmed":False,"pooling_allowed":False})
    report={"retrieved":len(rows),"requested":len(ids),"source_diagnostics":diag,
            "routing_matches":sum(x["routing_match"] for x in rows),
            "primary_ratio_matches":sum(x["reference_ratio_found"] is True for x in rows),
            "primary_reference_count":sum(v[1]=="primary" for v in CASES.values()),
            "reports":rows,"llm_calls":0,"policy_trained":False,"qualification_granted":False,
            "limitations":["previously used development controls","cue routing only, not clinical eligibility screening","ratio lead matching, not verified primary endpoint selection"]}
    Path("report-gym.json").write_text(json.dumps(report,indent=2)+"\n")
    print("REPORT_GYM "+json.dumps(report),flush=True)
    if len(rows)!=len(ids):raise SystemExit("partial retrieval")
if __name__=="__main__":asyncio.run(main_async())
