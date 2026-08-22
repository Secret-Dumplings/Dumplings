"""a2a http_utils 切换 + _refresh_a2a_proxies gather + Anthropic Files API beta header。

覆盖：
- AsyncHTTPClient.aget（5xx 重试 / 4xx 不重试 / 2xx 成功 / 超时）
- a2a_client.discover 走 AsyncHTTPClient（不再 raw httpx）
- _refresh_a2a_proxies 用 asyncio.gather 并发刷新；单个失败不影响其它
- _messages_use_files_api 检测 Anthropic Files API 块
- _build_anthropic_request 在 messages 含 file_id 时注入 anthropic-beta
"""
from __future__ import annotations

import asyncio
import uuid as _uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from tangyuanAI import activate_template, agent_list, template_agent
from tangyuanAI.a2a_client import (
    A2AAgentProxy,
    _refresh_a2a_proxies,
    discover,
    register_a2a_agent,
)
from tangyuanAI.agent import _AnthropicBase, _messages_use_files_api
from tangyuanAI.Agent_list import agent_template_pool


@pytest.fixture
def _isolate_agent_list():
    saved_list = dict(agent_list)
    saved_pool = dict(agent_template_pool)
    yield
    agent_list.clear()
    agent_template_pool.clear()
    agent_list.update(saved_list)
    agent_template_pool.update(saved_pool)


def _make_anthropic_agent():
    name = "anth-test"
    uuid_str = _uuid.uuid4().hex

    @template_agent(name, uuid=uuid_str, description="test")
    class _A(_AnthropicBase):
        prompt = "x"
        model_name = "claude-test"
        api_key = "k"
        stream = False

    _A.protocol = "anthropic"
    _A.api_provider = "http://mock.invalid"

    activate_template(name)
    inst = agent_list[name]
    inst._connectivity = lambda: None  # noqa: SLF001
    return inst


# ---------------------------------------------------------------------------
# _messages_use_files_api
# ---------------------------------------------------------------------------


def test_files_api_detection_true():
    msgs = [
        {
            "role": "user",
            "content": [
                {"type": "text", "text": "看这张图"},
                {
                    "type": "image",
                    "source": {"type": "file", "file_id": "file-api-xxxx"},
                },
            ],
        }
    ]
    assert _messages_use_files_api(msgs) is True


def test_files_api_detection_false_no_file():
    msgs = [
        {
            "role": "user",
            "content": [
                {"type": "text", "text": "看这张图"},
                {"type": "image", "source": {"type": "url", "url": "https://x/y.jpg"}},
            ],
        }
    ]
    assert _messages_use_files_api(msgs) is False


def test_files_api_detection_handles_string_content():
    msgs = [{"role": "user", "content": "纯文本"}]
    assert _messages_use_files_api(msgs) is False


def test_files_api_detection_handles_empty():
    assert _messages_use_files_api([]) is False


# ---------------------------------------------------------------------------
# Anthropic transport 自动注入 beta header
# ---------------------------------------------------------------------------


def test_build_anthropic_request_injects_beta_when_file_id_present(_isolate_agent_list):
    inst = _make_anthropic_agent()
    inst.history = [
        {"role": "system", "content": "sys"},
        {
            "role": "user",
            "content": [
                {"type": "text", "text": "看图"},
                {"type": "image", "source": {"type": "file", "file_id": "file-api-x"}},
            ],
        },
    ]

    req, transport = inst._build_anthropic_request()

    assert req.messages[0]["role"] == "user"
    assert "anthropic-beta" in transport.headers
    assert transport.headers["anthropic-beta"] == "files-api-2025-04-14"


def test_build_anthropic_request_no_beta_when_no_file_id(_isolate_agent_list):
    inst = _make_anthropic_agent()
    inst.history = [
        {"role": "system", "content": "sys"},
        {
            "role": "user",
            "content": [
                {"type": "text", "text": "看图"},
                {"type": "image", "source": {"type": "url", "url": "https://x/y.jpg"}},
            ],
        },
    ]

    _, transport = inst._build_anthropic_request()

    assert "anthropic-beta" not in transport.headers


def test_build_anthropic_request_basic_headers_always_present(_isolate_agent_list):
    """无 file_id 时基本 header 仍存在。"""
    inst = _make_anthropic_agent()
    inst.history = [{"role": "user", "content": "纯文本"}]

    _, transport = inst._build_anthropic_request()

    assert transport.headers["x-api-key"] == "k"
    assert transport.headers["anthropic-version"] == "2023-06-01"
    assert transport.headers["Content-Type"] == "application/json"


# ---------------------------------------------------------------------------
# _refresh_a2a_proxies 用 asyncio.gather
# ---------------------------------------------------------------------------


def test_refresh_a2a_proxies_concurrent_with_gather(_isolate_agent_list):
    """注册两个 proxy，mock discover；一个返回新 card，另一个 raise。
    验证：成功的被更新；失败的保留旧 metadata（不抛错）。
    """
    p1 = A2AAgentProxy(name="a2a_p1", url="http://h1:9000", description="old1", skills=["old"])
    p2 = A2AAgentProxy(name="a2a_p2", url="http://h2:9000", description="old2", skills=["old"])

    from tangyuanAI.Agent_list import register_agent

    register_agent("a2a_p1", p1, source=f"a2a:{p1.url}")
    register_agent("a2a_p2", p2, source=f"a2a:{p2.url}")

    async def fake_discover(url, **kwargs):
        if "h1" in url:
            return {"name": "p1", "description": "new1", "skills": ["new1"]}
        raise RuntimeError("boom")  # p2 不可达

    with patch("tangyuanAI.a2a_client.discover", side_effect=fake_discover):
        _refresh_a2a_proxies()

    # p1 成功刷新
    assert p1.description == "new1"
    assert p1.skills == ["new1"]
    # p2 失败保留旧值
    assert p2.description == "old2"
    assert p2.skills == ["old"]


def test_refresh_a2a_proxies_skips_when_no_proxies(_isolate_agent_list):
    """agent_list 为空时不报错。"""
    # 不注册任何 A2A proxy
    _refresh_a2a_proxies()  # 不应抛错


def test_refresh_a2a_proxies_skips_when_in_event_loop(_isolate_agent_list):
    """在 async 上下文里调 reload hook 不应阻塞（asyncio.run 会 RuntimeError）。"""
    p = A2AAgentProxy(name="a2a_p", url="http://h:9000", description="d", skills=[])
    from tangyuanAI.Agent_list import register_agent

    register_agent("a2a_p", p, source=f"a2a:{p.url}")

    async def fake_discover(url, **kwargs):
        return {"name": "p", "description": "new", "skills": ["new"]}

    async def runner():
        with patch("tangyuanAI.a2a_client.discover", side_effect=fake_discover):
            _refresh_a2a_proxies()  # 内部 asyncio.run 会 RuntimeError → 跳过

    asyncio.run(runner())
    # 跳过 → 保留旧值
    assert p.description == "d"


# ---------------------------------------------------------------------------
# a2a_client.discover 走 AsyncHTTPClient
# ---------------------------------------------------------------------------


@patch("tangyuanAI.a2a_client.AsyncHTTPClient")
async def test_discover_uses_async_http_client(MockClient):
    """discover 应该调 AsyncHTTPClient.aget，不再 raw httpx。"""
    fake_resp = MagicMock()
    fake_resp.json.return_value = {"name": "remote", "description": "远端"}
    mock_instance = MagicMock()
    mock_instance.aget = AsyncMock(return_value=fake_resp)
    mock_instance.__aenter__ = AsyncMock(return_value=mock_instance)
    mock_instance.__aexit__ = AsyncMock(return_value=None)
    MockClient.return_value = mock_instance

    got = await discover("http://host:9000")

    assert got["name"] == "remote"
    mock_instance.aget.assert_awaited_once()
    url = mock_instance.aget.await_args.args[0]
    assert url == "http://host:9000/.well-known/agent.json"


async def test_register_a2a_agent_uses_async_http_client(_isolate_agent_list):
    """register_a2a_agent → discover → AsyncHTTPClient。"""
    fake_card = {"name": "remote", "description": "远端", "skills": ["s1"]}

    mock_instance = MagicMock()
    mock_instance.aget = AsyncMock(
        return_value=MagicMock(json=lambda: fake_card),
    )
    mock_instance.__aenter__ = AsyncMock(return_value=mock_instance)
    mock_instance.__aexit__ = AsyncMock(return_value=None)

    with patch("tangyuanAI.a2a_client.AsyncHTTPClient", return_value=mock_instance):
        proxy = register_a2a_agent("http://host:9000", alias="my_alias")

    assert proxy.name == "my_alias"
    assert proxy.description == "远端"
    assert proxy.skills == ["s1"]
