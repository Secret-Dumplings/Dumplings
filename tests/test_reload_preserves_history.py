"""验证 agent.reload() 保留对话历史 + 触发 reload 钩子。

覆盖：
- reload 后 history 中 user/assistant 消息仍在
- reload 后 history[0]（system 消息）内容被刷新
- reload 触发已注册的 reload 钩子
- 钩子抛错时不阻断 reload
- OpenAI / Anthropic 两协议都覆盖
"""
from __future__ import annotations

import uuid as _uuid

import pytest
from tangyuanAI import activate_template, agent_list, template_agent
from tangyuanAI.agent import _AnthropicBase, _OpenAIBase
from tangyuanAI.Agent_list import agent_template_pool
from tangyuanAI.reload_hooks import register_reload_hook, unregister_reload_hook


@pytest.fixture
def _isolate_agent_list():
    """每个测试隔离 agent_list / agent_template_pool。

    非 autouse：避免跨文件污染（pytest 同一 session 内 autouse fixture 会作用于所有测试）。
    """
    saved_list = dict(agent_list)
    saved_pool = dict(agent_template_pool)
    yield
    agent_list.clear()
    agent_template_pool.clear()
    agent_list.update(saved_list)
    agent_template_pool.update(saved_pool)


def _make_agent(cls, name: str, *, protocol: str, api_provider: str):
    """构造最小 Agent（不连真 LLM），返回实例。"""
    uuid_str = _uuid.uuid4().hex

    @template_agent(name, uuid=uuid_str, description="test")
    class _A(cls):
        prompt = "you are a test agent"
        model_name = "test-model"
        api_key = "test-key"
        stream = False

    # 类 body 不能直接引用外层局部变量；在装饰后赋值
    _A.protocol = protocol
    _A.api_provider = api_provider

    activate_template(name)
    inst = agent_list[name]
    inst._connectivity = lambda: None  # noqa: SLF001
    return inst


def test_openai_reload_preserves_user_assistant_history(_isolate_agent_list):
    inst = _make_agent(
        _OpenAIBase,
        "reload-keep-oa",
        protocol="openai",
        api_provider="http://mock.invalid/v1/chat/completions",
    )

    inst.history = [
        {"role": "system", "content": "sys-original"},
        {"role": "user", "content": "remembered question"},
        {"role": "assistant", "content": "old answer"},
    ]
    original_user = inst.history[1]
    original_assistant = inst.history[2]

    result = inst.reload()

    assert result == "reloaded"
    # user / assistant 必须保留（对象身份 + 内容）
    assert inst.history[1] is original_user
    assert inst.history[2] is original_assistant
    assert inst.history[1]["content"] == "remembered question"
    assert inst.history[2]["content"] == "old answer"
    # system 消息被刷新
    assert "you are a test agent" in inst.history[0]["content"]
    assert inst.history[0]["content"] != "sys-original"


def test_openai_reload_fires_registered_hooks(_isolate_agent_list):
    inst = _make_agent(
        _OpenAIBase,
        "reload-fire-hooks",
        protocol="openai",
        api_provider="http://mock.invalid/v1/chat/completions",
    )

    calls: list[str] = []

    def my_hook():
        calls.append("hit")

    register_reload_hook(my_hook)
    try:
        inst.reload()
        assert calls == ["hit"]
    finally:
        unregister_reload_hook(my_hook)


def test_openai_reload_does_not_break_when_hook_raises(_isolate_agent_list):
    inst = _make_agent(
        _OpenAIBase,
        "reload-hook-fail",
        protocol="openai",
        api_provider="http://mock.invalid/v1/chat/completions",
    )

    def bad_hook():
        raise RuntimeError("boom")

    def good_hook():
        pass

    register_reload_hook(bad_hook)
    register_reload_hook(good_hook)
    try:
        result = inst.reload()
        assert result == "reloaded"
    finally:
        unregister_reload_hook(bad_hook)
        unregister_reload_hook(good_hook)


def test_anthropic_reload_preserves_history(_isolate_agent_list):
    inst = _make_agent(
        _AnthropicBase,
        "reload-keep-anth",
        protocol="anthropic",
        api_provider="http://mock.invalid",
    )

    # 真实 Anthropic 流程：history[0] 是 system（_AgentCommon._build_system_prompt 写入），
    # 发送时 _build_anthropic_request 用 _extract_system_and_messages 拆出。
    # reload 必须保留 user/assistant。
    inst.history = [
        {"role": "system", "content": "sys-original"},
        {"role": "user", "content": "remembered question"},
        {"role": "assistant", "content": "kept answer"},
    ]
    original_user = inst.history[1]
    original_assistant = inst.history[2]

    result = inst.reload()

    assert result == "reloaded"
    # user / assistant 必须保留（对象身份 + 内容）
    assert inst.history[1] is original_user
    assert inst.history[2] is original_assistant
    assert inst.history[1]["content"] == "remembered question"
    assert inst.history[2]["content"] == "kept answer"
    # system 被刷新；anthropic 还有独立 self.system_prompt 字段
    assert "you are a test agent" in inst.history[0]["content"]
    assert "you are a test agent" in inst.system_prompt
