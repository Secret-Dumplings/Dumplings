# -*- coding: utf-8 -*-
"""
Agent 注册表 API 包装（v0.4.2+）。

之前 ``dumplingsAI.agent_list`` 是个裸 dict，外部代码可以直接
``agent_list.clear()`` / ``agent_list["foo"] = bar`` 破坏全局状态。

v0.4.2+ 包装：
- ``register_agent(name, instance)`` —— 注册一个 agent 实例
- ``unregister_agent(name)`` —— 注销（name 不存在不抛）
- ``agent_list`` 保留（向后兼容），但推荐用 wrapper

真实任务：用户用 ``@register_agent`` 装饰器注册了一个类，再用
``unregister_agent`` / ``register_agent`` 显式控制生命周期（替代手改 dict）。
"""
from __future__ import annotations

import pytest
from dumplingsAI import (
    Agent,
    activate_template,
    agent_list,
    register_agent,
    template_agent,
    unregister_agent,
)


@pytest.fixture(autouse=True)
def _clean_globals():
    agent_list.clear()
    yield
    agent_list.clear()


def test_register_and_unregister_agent_api():
    """v0.4.2+：``register_agent(name, instance)`` / ``unregister_agent(name)``
    包装裸 dict 操作，避免外部代码直接 mutate agent_list。
    """
    @template_agent("api-wrap", uuid="11111111-1111-1111-1111-111111111111", description="t")
    class _A(Agent):
        protocol = "openai"
        prompt = "x"
        model_name = "m"
        api_key = "k"
        api_provider = "http://x"

    activate_template("api-wrap")
    inst = agent_list["api-wrap"]

    # unregister + register 走 wrapper API
    unregister_agent("api-wrap")
    assert "api-wrap" not in agent_list

    register_agent("api-wrap", inst)
    assert "api-wrap" in agent_list
    assert agent_list["api-wrap"] is inst

    # unregister 不存在的 key 不抛
    unregister_agent("does-not-exist")  # 不应崩


def test_unregister_then_re_register_resets_instance():
    """unregister 后用 register 重注册，agent_list 状态正确。"""
    @template_agent("re-reg", uuid="22222222-2222-2222-2222-222222222222", description="t")
    class _A(Agent):
        protocol = "openai"
        prompt = "v1"
        model_name = "m"
        api_key = "k"
        api_provider = "http://x"

    activate_template("re-reg")
    inst1 = agent_list["re-reg"]
    unregister_agent("re-reg")
    assert "re-reg" not in agent_list

    # 用同一个类新建实例（__init__ 重新跑），prompt 不同
    @template_agent("re-reg", uuid="33333333-3333-3333-3333-333333333333", description="t")
    class _A2(Agent):
        protocol = "openai"
        prompt = "v2"
        model_name = "m"
        api_key = "k"
        api_provider = "http://x"

    activate_template("re-reg")
    inst2 = agent_list["re-reg"]
    assert inst2 is not inst1  # 不同实例
    assert inst2.prompt == "v2"
