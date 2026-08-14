"""
示例：协议无关的 Agent 工厂

**推荐写法**：继承 ``tangyuanAI.Agent`` + 类属性 ``protocol = "openai" | "anthropic" | "openai-responses"``。
不再需要 import `BaseAgent` / `AnthropicAgent`（这两个旧入口在 v1.3.0 删除）。

本文件演示 3 种写法：
1. 直接选基类（旧写法，已 deprecated 但仍兼容）
2. 用 Agent + protocol 字段（推荐新写法）
3. 动态按环境变量切协议
"""
import os
import uuid

import tangyuanAI
from dotenv import load_dotenv
from tangyuanAI.Agent_list import activate_template

load_dotenv()


# ---------- 方式 1（已 deprecated 的旧写法，仅为对比保留） ----------
@tangyuanAI.template_agent(
    "openai_legacy",
    uuid=uuid.uuid4().hex,
    description="直接继承 BaseAgent（已 deprecated 旧写法演示）",
)
class OpenAILegacy(tangyuanAI.BaseAgent):                      # noqa: F401  已 deprecated，v1.3.0 删除
    """直接继承 BaseAgent —— OpenAI 协议（已 deprecated）"""
    prompt = "你是一个助手"
    api_provider = "https://api.example.com/v1/chat/completions"
    model_name = os.getenv("OPENAI_MODEL")
    api_key = os.getenv("API_KEY")


@tangyuanAI.template_agent(
    "anthropic_legacy",
    uuid=uuid.uuid4().hex,
    description="直接继承 AnthropicAgent（已 deprecated 旧写法演示）",
)
class AnthropicLegacy(tangyuanAI.Agent):                      # 推荐写法：Agent + protocol
    """Anthropic 协议 + Agent 基类（推荐写法）"""
    protocol = "anthropic"
    prompt = "你是一个助手"
    model_name = os.getenv("ANTHROPIC_MODEL")
    api_key = os.getenv("ANTHROPIC_API_KEY")


# ---------- 方式 2（推荐写法：Agent + protocol 字段） ----------
@tangyuanAI.template_agent(
    "openai_factory",
    uuid=uuid.uuid4().hex,
    description="用 Agent + protocol 字段选 OpenAI（推荐写法）",
)
class OpenAIViaFactory(tangyuanAI.Agent):
    """用 Agent + protocol 选 OpenAI"""
    protocol = "openai"
    prompt = "你是一个助手"
    api_provider = "https://api.example.com/v1/chat/completions"
    model_name = os.getenv("OPENAI_MODEL")
    api_key = os.getenv("API_KEY")


@tangyuanAI.template_agent(
    "anthropic_factory",
    uuid=uuid.uuid4().hex,
    description="用 Agent + protocol 字段选 Anthropic（推荐写法）",
)
class AnthropicViaFactory(tangyuanAI.Agent):
    """用 Agent + protocol 选 Anthropic"""
    protocol = "anthropic"
    prompt = "你是一个助手"
    model_name = os.getenv("ANTHROPIC_MODEL")
    api_key = os.getenv("ANTHROPIC_API_KEY")


# ---------- 方式 3（动态切换：根据配置决定协议） ----------
# Python class body 的 name resolution 不会向 enclosing scope 找同名变量，
# 所以这里把协议值取到不冲突的变量名 ``_proto`` 上，再在类里用 ``protocol = _proto``。
def _make_agent(name: str):
    """从环境变量读协议，动态构造 Agent 类。"""
    _proto = os.getenv("AGENT_PROTOCOL", "openai").lower()  # 没设 AGENT_PROTOCOL 就默认 openai
    _model = os.getenv("AGENT_MODEL")
    _provider = os.getenv("AGENT_API_PROVIDER", "https://api.example.com/v1/chat/completions")

    @tangyuanAI.template_agent(
        name,
        uuid=uuid.uuid4().hex,
        description="动态协议 Agent（由 AGENT_PROTOCOL 环境变量决定）",
    )
    class DynamicAgent(tangyuanAI.Agent):
        protocol = _proto
        prompt = "你是一个助手"
        model_name = _model
        api_provider = _provider
        api_key = os.getenv("API_KEY")

    return DynamicAgent


DynamicAgentCls = _make_agent("dynamic_agent")


if __name__ == "__main__":
    from tangyuanAI import BaseAgent
    # 注：AnthropicAgent 仍可从 tangyuanAI.anthropic_agent 导入（v1.3.0 删），
    # 但推荐用 tangyuanAI.AnthropicAgent（始终指向 _AnthropicBase）。

    # v0.3.0+ 模板池：全部激活后才能在 agent_list 里看到
    for n in ("openai_legacy", "anthropic_legacy",
              "openai_factory", "anthropic_factory",
              "dynamic_agent"):
        activate_template(n)

    # 验证派发结果
    cases = [
        ("OpenAILegacy",       OpenAILegacy,       BaseAgent),
        ("AnthropicLegacy",    AnthropicLegacy,    tangyuanAI.Agent),  # 现在也是 Agent + protocol
        ("OpenAIViaFactory",   OpenAIViaFactory,   BaseAgent),
        ("AnthropicViaFactory",AnthropicViaFactory,tangyuanAI.Agent),
        ("DynamicAgentCls",    DynamicAgentCls,    None),  # 看环境变量
    ]
    for name, cls, expected_base in cases:
        bases = [b.__name__ for b in cls.__mro__ if b.__name__ in ("Agent", "BaseAgent", "AnthropicAgent")]
        ok = expected_base is None or issubclass(cls, expected_base)
        marker = "OK" if ok else "FAIL"
        print(f"[{marker}] {name:25s} MRO 含协议基类: {bases}")
    print()
    print("所有 Agent 都在 tangyuanAI.agent_list 里可用：")
    for name in sorted(tangyuanAI.agent_list):
        print(f"  - {name}")
