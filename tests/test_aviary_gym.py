import asyncio
from types import SimpleNamespace
import pytest
pytest.importorskip("aviary.core")
from aviary.core import ToolCall, ToolRequestMessage
from scripts.v2_aviary_gym import RetrievalGym, episode, ACTIONS

REF={"linked_reports":{"101":"a","102":"b"},"excluded_from_rct_oriented_report_metric":[]}

def test_real_aviary_tool_interface_and_hidden_labels():
    async def check():
        env=RetrievalGym(None, REF, {"narrow_top":(frozenset({"101","999"}),[],True)})
        obs,tools=await env.reset()
        assert "101" not in obs[0].content and "102" not in obs[0].content
        assert {t.info.name for t in tools}==set(ACTIONS)
        obs,reward,done,trunc=await env.step(ToolRequestMessage(tool_calls=[ToolCall.from_tool(tools[0])]))
        assert done and not trunc and 0<reward<.5
        assert "101" not in obs[0].content and "102" not in obs[0].content
        with pytest.raises(RuntimeError):
            await env.step(ToolRequestMessage(tool_calls=[ToolCall.from_tool(tools[0])]))
    asyncio.run(check())

def test_source_failure_is_truncated():
    env=RetrievalGym(None,REF,{"dual_ids":(frozenset(),[],False)})
    result=asyncio.run(episode(env,"dual_ids"))
    assert result["truncated"] and result["relative_recall"] is None and result["reward"]==-1

def test_unlabelled_not_false_positive_and_episode_resets():
    env=RetrievalGym(None,REF,{"dual_ids":(frozenset({"101","102","999"}),[],True)})
    for _ in range(2):
        result=asyncio.run(episode(env,"dual_ids"))
        assert result["relative_recall"]==1 and result["retrieved"]==3
        assert result["done"] and not result["truncated"]

def test_invalid_tool_request_truncates():
    async def check():
        env=RetrievalGym(None,REF,{})
        await env.reset()
        _,reward,done,trunc=await env.step(ToolRequestMessage(tool_calls=[ToolCall.from_name("invalid")]))
        assert reward==-1 and not done and trunc
    asyncio.run(check())
