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
from scripts.v2_historical_replay_dev import REFERENCE, STRATEGIES, retrieve, full_id_diagnostic

ACTIONS = ("narrow_top", "dual_top", "narrow_ids", "dual_ids")
@dataclass
class State:
    tried: bool = False
    finished: bool = False
    unresolved: bool = False
    reward: float = 0.0
    trace: list = field(default_factory=list)

class RetrievalGym(Environment[State]):
    def __init__(self, client, reference, cache):
        self.client = client
        self._target = frozenset(reference["linked_reports"]) - set(reference["excluded_from_rct_oriented_report_metric"])
        if not self._target:
            raise ValueError("empty reference subset")
        self.cache = cache

    async def reset(self):
        self.state = State()
        self.tools = [Tool.from_function(self.narrow_top), Tool.from_function(self.dual_top),
                      Tool.from_function(self.narrow_ids), Tool.from_function(self.dual_ids)]
        return [Message(content="Development exercise: retrieve reports for statins in primary coronary prevention, publication cutoff 2017-10-31. Choose one strategy. IDs-only enumeration is not full-text screening. Reference labels withheld.")], self.tools

    def _execute(self, action):
        if self.state.tried:
            return "Episode already attempted."
        self.state.tried = True
        strategy, mode = action.rsplit("_", 1)
        routes = STRATEGIES[strategy]
        if action not in self.cache:
            if mode == "top":
                ids, audit = retrieve(self.client, routes)
                valid = all(a["status"] in {"SEARCHED_POSITIVE","SEARCHED_NEGATIVE"} for a in audit)
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
        """Retrieve up to 100 PubMed records using a narrow prevention query."""
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
    return {"aviary_version":version("fhaviary"),"reference_review":REFERENCE["review_pmid"],
            "reference_scope":"incomplete report-level development subset",
            "policy":"epsilon-greedy sample-average action values","seed":42,
            "episodes":history,"learned_values":values,"action_counts":counts,
            "preferred_action":preferred,"baseline_reward":history[0]["reward"],
            "preferred_reward":values[preferred],"distinct_live_actions":len(cache),
            "all_sources_resolved":all(not h["truncated"] for h in history),
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
