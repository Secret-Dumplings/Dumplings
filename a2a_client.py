# -*- coding: utf-8 -*-
"""
A2A Client（kb/a2a_client.py）
==============================

**导入方向**：发现远端 A2A agent → 注册到本地 agent_list（标记 source="a2a:<url>"）。

- `discover(url)`：GET `{url}/.well-known/agent.json` 拿 Agent Card
- `send_task(url, message, task_id=None)`：POST `{url}/a2a/v1/tasks/send` 调远端
- `register_a2a_agent(url, alias=None)`：发现 + 注册 A2AAgentProxy 到 agent_list

**ask_for_help 集成**：注册的 A2AAgentProxy 是普通 Agent，本地 agent 用
`ask_for_help(agent_id="a2a_xxx", message=...)` 就能调远端 —— 走 proxy 的
`conversation_with_tool` → HTTP 调远端 A2A。

**依赖**：`httpx`（required dep）。
"""
from __future__ import annotations

import asyncio
from typing import Any, Optional

import httpx

from tangyuanAI.logging_config import logger

__all__ = ["discover", "send_task", "send_task_sync", "register_a2a_agent", "A2AAgentProxy"]


_DEFAULT_TIMEOUT = 30.0


def _normalize_base(url: str) -> str:
    """剥 trailing /；返回裸 base（不含 /.well-known 或 /a2a）。"""
    return url.rstrip("/")


async def discover(url: str, *, timeout: float = _DEFAULT_TIMEOUT) -> dict[str, Any]:
    """发现远端 A2A agent，返回 Agent Card。

    GET `{url}/.well-known/agent.json`

    Raises:
        httpx.HTTPStatusError: 非 200
        ValueError: card 缺 name
    """
    base = _normalize_base(url)
    async with httpx.AsyncClient(timeout=timeout) as client:
        resp = await client.get(f"{base}/.well-known/agent.json")
        resp.raise_for_status()
        card = resp.json()
    if not isinstance(card, dict) or not card.get("name"):
        raise ValueError(f"Agent Card 缺 name: {card}")
    logger.info(f"A2A 发现远端 agent: {card['name']} @ {base}")
    return card


async def send_task(
    url: str,
    message: str,
    *,
    task_id: str | None = None,
    timeout: float = _DEFAULT_TIMEOUT,
) -> dict[str, Any]:
    """调远端 A2A agent 的 tasks/send。

    POST `{url}/a2a/v1/tasks/send`（JSON-RPC 2.0）

    Returns: JSON-RPC result（含 status / artifacts）。
    """
    from .a2a_protocol import make_json_rpc_request, make_text_message

    base = _normalize_base(url)
    request = make_json_rpc_request(
        "tasks/send",
        {
            "id": task_id,
            "message": make_text_message(message, role="user"),
        },
    )
    async with httpx.AsyncClient(timeout=timeout) as client:
        resp = await client.post(f"{base}/a2a/v1/tasks/send", json=request)
        resp.raise_for_status()
        data = resp.json()
    if "error" in data:
        raise RuntimeError(f"A2A 远端返回错误: {data['error']}")
    logger.debug(f"A2A send 完成: task_id={data.get('result', {}).get('id')}")
    return data.get("result", {})


def send_task_sync(url: str, message: str, **kwargs) -> dict[str, Any]:
    """同步版 send_task。"""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(send_task(url, message, **kwargs))
    # 已有 running loop：在该 loop 里调度 + 阻塞等结果
    import concurrent.futures
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
        future = ex.submit(asyncio.run, send_task(url, message, **kwargs))
        return future.result()


class A2AAgentProxy:
    """远端 A2A agent 的本地代理。

    表现像本地 Agent：有 name / description；`conversation_with_tool(prompt)`
    把 prompt 转发到远端 `tasks/send`。
    """

    def __init__(
        self,
        name: str,
        url: str,
        description: str = "",
        skills: Optional[list[dict[str, Any]]] = None,
    ):
        self.name = name
        self.url = url
        self.description = description
        self.skills = skills or []
        self.source = f"a2a:{url}"

    def conversation_with_tool(self, prompt: str, **kwargs) -> str:
        """同步调远端 A2A agent。返回远端回复文本。"""
        from .a2a_protocol import extract_text_from_artifacts
        result = send_task_sync(self.url, prompt)
        return extract_text_from_artifacts(result.get("artifacts", []))

    async def aconversation_with_tool(self, prompt: str, **kwargs) -> str:
        """异步调远端 A2A agent。"""
        from .a2a_protocol import extract_text_from_artifacts
        result = await send_task(self.url, prompt)
        return extract_text_from_artifacts(result.get("artifacts", []))

    def __repr__(self) -> str:
        return f"A2AAgentProxy(name={self.name!r}, url={self.url!r})"


def register_a2a_agent(
    url: str,
    *,
    alias: Optional[str] = None,
    allow_ask_for_help: bool = True,
) -> A2AAgentProxy:
    """发现并把远端 A2A agent 注册到本地 agent_list。

    Args:
        url: 远端 A2A server 的 base URL（如 http://host:port）
        alias: 本地 agent 名（默认 f"a2a_{card['name']}"）
        allow_ask_for_help: 是否允许本地 agent 通过 ask_for_help 调它（默认 True）

    Returns: A2AAgentProxy 实例（已注册到 agent_list，source="a2a:<url>"）
    """
    from tangyuanAI.Agent_list import register_agent as _register

    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    if loop is None:
        card = asyncio.run(discover(url))
    else:
        import concurrent.futures
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
            card = ex.submit(asyncio.run, discover(url)).result()
    name = alias or f"a2a_{card['name']}"
    proxy = A2AAgentProxy(
        name=name,
        url=_normalize_base(url),
        description=card.get("description", ""),
        skills=card.get("skills", []),
    )
    _register(name, proxy, source=f"a2a:{url}")
    logger.info(f"A2A agent 已注册到 agent_list: {name} (source=a2a:{url})")
    return proxy


# ==================== reload 钩子 ====================
# agent.reload() 触发时，刷新所有已注册 A2A 代理的 Agent Card（description / skills）。
# 单个远端不可达不会影响其它代理；失败的代理保留旧 metadata。

from .reload_hooks import register_reload_hook  # noqa: E402


def _refresh_a2a_proxies() -> None:
    """遍历 agent_list，重新拉取所有 A2A 代理的 Agent Card。"""
    try:
        from tangyuanAI.Agent_list import agent_list
    except ImportError:
        return

    seen: set[int] = set()
    for entry in list(agent_list.values()):
        if not isinstance(entry, A2AAgentProxy) or id(entry) in seen:
            continue
        seen.add(id(entry))
        try:
            card = asyncio.run(discover(entry.url))
        except Exception:  # noqa: BLE001 — 单个远端不可达不影响其它代理
            continue
        if card.get("description"):
            entry.description = card["description"]
        if card.get("skills"):
            entry.skills = card["skills"]


register_reload_hook(_refresh_a2a_proxies)
