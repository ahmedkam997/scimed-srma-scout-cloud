"""Aviary-backed development gym. Never calls scientific qualification.
Real PubMed retrieval, reference-based feedback, tiny tabular policy learning.
The learner sees tool names, observation counts and scalar rewards, not reference IDs.
This is an in-process experiment, not a security sandbox for arbitrary code.
"""
import asyncio
import json
import random
from dataclasses import dataclass, field
from importlib.metadata import version
from pathlib import Path
from aviary.core import Environment, Message, Tool, ToolCall, ToolRequestMessage
from scimed_scout.sources.pubmed import PubMedSource
from scripts.v2_historical_replay_dev import REFERENCE, STRATEGIES, full_id_diagnostic

# Second development case: Pandey et al., ESC Heart Failure 2022, PMID 35112512.
# Search reported through September 2021; last day of month is a declared approximation.
# Four primary reports, NOT a seven-trial qualification candidate.
HF_REFERENCE={"review_pmid":"35112512","linked_reports":{
    "31535829":"DAPA-HF","32865377":"EMPEROR-Reduced",
    "34449189":"EMPEROR-Preserved","33200892":"SOLOIST-WHF"},
    "excluded_from_rct_oriented_report_metric":[]}
HF_DATE='("1800/01/01"[dp] : "2021/09/30"[dp])'
HF_DRUG='(SGLT2[tiab] OR "Sodium-Glucose Transporter 2 Inhibitors"[Mesh] OR dapagliflozin[tiab] OR empagliflozin[tiab] OR sotagliflozin[tiab] OR canagliflozin[tiab] OR ertugliflozin[tiab])'
HF_RCT='(randomized controlled trial[pt] OR random*[tiab] OR placebo[tiab])'
HF_NARROW='("heart failure"[tiab] OR "Heart Failure"[Mesh])'
HF_BROAD='(cardiovascular[tiab] OR ventricular[tiab] OR cardiac[tiab])'
HF_STRATEGIES={"narrow":[(f"{HF_DRUG} AND {HF_NARROW} AND {HF_RCT} AND {HF_DATE}",100)],
               "dual_route":[(f"{HF_DRUG} AND {HF_NARROW} AND {HF_RCT} AND {HF_DATE}",50),
                             (f"{HF_DRUG} AND {HF_BROAD} AND {HF_RCT} AND {HF_DATE}",50)]}

ACTIONS = ("narrow_top", "dual_top", "narrow_ids", "dual_ids")
@dataclass
class State:
    tried: bool = False
    finished: bool = False
    unresolved: bool = False
    reward: float = 0.0
    trace: list = field(default_factory=list)

def bounded_ids(client, routes):
    """Top-K ID-only comparator; no metadata fetch, same ESearch rank as enumeration."""
    ids, audits = set(), []
    for query, slots in routes:
        row={"query":query,"slots":slots,"complete_bounded":False}
        try:
            data=client.http.get_json(client.base+"esearch.fcgi",client._params({
                "db":"pubmed","term":query,"retmode":"json","retmax":slots,"sort":"relevance"}))
            block=data.get("esearchresult") or {}
            total=int(block["count"])
            found=[str(x) for x in block.get("idlist",[])]
            warning=block.get("warninglist") or {}
            valid=not (block.get("errorlist") or data.get("error") or data.get("ERROR")
                       or (isinstance(warning,dict) and warning.get("quotedphrasesnotfound")))
            complete=valid and total>=0 and len(found)==min(total,slots) and len(set(found))==len(found) and all(x.isdigit() for x in found)
            ids.update(found)
            row.update(total=total,retrieved_ids=len(found),complete_bounded=complete)
        except Exception as exc:
            row["error_type"]=type(exc).__name__
        audits.append(row)
    return ids,audits

class RetrievalGym(Environment[State]):
    def __init__(self, client, reference, cache, strategies=STRATEGIES, task="statins in primary coronary prevention, publication cutoff 2017-10-31"):
        self.client = client
        self._target = frozenset(reference["linked_reports"]) - set(reference["excluded_from_rct_oriented_report_metric"])
        if not self._target:
            raise ValueError("empty reference subset")
        self.cache = cache
        self.strategies = strategies
        self.task = task

    async def reset(self):
        self.state = State()
        self.tools = [Tool.from_function(self.narrow_top), Tool.from_function(self.dual_top),
                      Tool.from_function(self.narrow_ids), Tool.from_function(self.dual_ids)]
        return [Message(content=f"Development exercise: retrieve reports for {self.task}. Choose one strategy. IDs-only enumeration is not full-text screening. Reference labels withheld.")], self.tools

    def _execute(self, action):
        if self.state.tried:
            return "Episode already attempted."
        self.state.tried = True
        strategy, mode = action.rsplit("_", 1)
        routes = self.strategies["dual_route" if strategy == "dual" else strategy]
        if action not in self.cache:
            if mode == "top":
                ids, audit = bounded_ids(self.client, routes)
                valid = all(a["complete_bounded"] for a in audit)
            else:
                ids, audit = set(), []
                for query, _ in routes:
                    found, row = full_id_diagnostic(self.client, query)
                    ids.update(found)
                    audit.append(row)
                valid = all(a["complete"] for a in audit)
            self.cache[action] = (frozenset(ids), audit, valid)
        ids, audit, valid = self.cache[action]
        hits = len(ids & self._target)
        recall = hits / len(self._target) if valid else None
        # Penalize candidate workload, not unlabelled records as false positives.
        # Development-only scalar; NOT a clinical metric or qualification criterion.
        reward = recall - 0.1 * min(len(ids)/10000, 1) if valid else -1.0
        self.state.reward = reward
        self.state.unresolved = not valid
        self.state.finished = True
        self.state.trace.append({"action":action,"retrieved":len(ids),"reference_matches":hits if valid else None,
                                 "reference_count":len(self._target),"relative_recall":recall,
                                 "reward":reward,"source_complete_for_mode":valid,"audit":audit})
        return json.dumps({"retrieved":len(ids),"source_resolved":valid,"mode":mode})

    def narrow_top(self) -> str:
        """Retrieve up to 100 ranked PubMed identifiers using a narrow clinical query."""
        return self._execute("narrow_top")
    def dual_top(self) -> str:
        """Retrieve up to 100 PubMed records across two search routes."""
        return self._execute("dual_top")
    def narrow_ids(self) -> str:
        """Enumerate matching PubMed identifiers for the narrow query, up to 10000."""
        return self._execute("narrow_ids")
    def dual_ids(self) -> str:
        """Enumerate matching PubMed identifiers across both routes, up to 10000 per route."""
        return self._execute("dual_ids")

    async def step(self, action: ToolRequestMessage):
        if self.state.finished:
            raise RuntimeError("episode finished; reset required")
        if len(action.tool_calls)!=1 or action.tool_calls[0].function.name not in ACTIONS:
            self.state.finished = True
            self.state.reward = -1.0
            self.state.unresolved = True
            return [Message(content="Invalid action; exactly one known tool required.")], -1.0, False, True
        obs = await self.exec_tool_calls(action)
        if not self.state.finished:
            self.state.finished = True
            self.state.unresolved = True
            return obs, -1.0, False, True
        return obs, self.state.reward, not self.state.unresolved, self.state.unresolved

async def episode(env, action):
    _, tools = await env.reset()
    tool = next(t for t in tools if t.info.name == action)
    obs, reward, done, truncated = await env.step(ToolRequestMessage(tool_calls=[ToolCall.from_tool(tool)]))
    assert done != truncated
    assert env.state.trace
    return {**env.state.trace[-1],"done":done,"truncated":truncated,
            "observation":str(obs[0].content)}

async def train(client):
    cache = {}
    env = RetrievalGym(client, REFERENCE, cache)
    rng = random.Random(42)
    values = {a:0.0 for a in ACTIONS}
    counts = {a:0 for a in ACTIONS}
    history = []
    # Initial exploration, then epsilon-greedy; sample-average tabular action values.
    # This updates a policy, not an LLM. Repeated episodes reuse this development corpus.
    for i in range(12):
        action = ACTIONS[i] if i<len(ACTIONS) else (rng.choice(ACTIONS) if rng.random()<.2 else max(ACTIONS,key=values.get))
        result = await episode(env, action)
        history.append(result)
        counts[action]+=1
        values[action]+=(result["reward"]-values[action])/counts[action]
    preferred = max(ACTIONS,key=values.get)
    # Freeze policy before observing any reward from the second review.
    transfer_env=RetrievalGym(client,HF_REFERENCE,{},HF_STRATEGIES,"SGLT2 inhibitors in heart failure, publication cutoff 2021-09-30")
    transfer=await episode(transfer_env,preferred)
    transfer_baseline=await episode(transfer_env,"narrow_top")
    return {"aviary_version":version("fhaviary"),"reference_review":REFERENCE["review_pmid"],
            "reference_scope":"incomplete report-level development subset",
            "policy":"epsilon-greedy sample-average action values","seed":42,
            "episodes":history,"learned_values":values,"action_counts":counts,
            "preferred_action":preferred,"baseline_reward":history[0]["reward"],
            "preferred_reward":values[preferred],"distinct_live_actions":len(cache),
            "all_sources_resolved":all(not h["truncated"] for h in [*history,transfer,transfer_baseline]),
            "transfer_development_case":{"review_pmid":"35112512","cutoff":"2021-09-30 (month-end approximation)","frozen_policy":True,"policy_result":transfer,"baseline_result":transfer_baseline,"independent_final_test":False,"qualification_granted":False},
            "held_out":False,"historical_index_snapshot":False,
            "llm_weights_changed":False,"qualification_granted":False}

def main():
    report = asyncio.run(train(PubMedSource(sort="relevance")))
    Path("aviary-gym-report.json").write_text(json.dumps(report,indent=2)+"\n")
    print("AVIARY_GYM_RESULT "+json.dumps(report),flush=True)
    if not report["all_sources_resolved"]:
        raise SystemExit("Unresolved source access; training outcome not verified")

if __name__=="__main__":
    main()
