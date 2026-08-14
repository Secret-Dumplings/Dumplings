# -*- coding: utf-8 -*-
"""
LLM Transport 抽象层
====================

为什么需要这一层
----------------
原 ``BaseAgent.conversation_with_tool`` / ``AnthropicAgent.conversation_with_tool``
把 provider 协议相关的东西（payload 拼装、HTTP header、SSE 解析、tool_call 抽取、
token 统计）都写在 Agent 类里。一旦底层 API 换协议（OpenAI → Anthropic → 自家网关 →
OpenRouter…），Agent 的代码要跟着大改。

LLM Transport 把这些 provider 细节**封装到独立的 transport 类**里，Agent 只
看到一份中性的 ``LLMResponse`` / ``LLMEvent``。换底层只换一个 transport 实现，
Agent 本身不动。

层次
----
```
BaseAgent
   │
   ▼  transport.chat(...) / transport.chat_stream(...)
   │
LLMTransport  (抽象：chat / achat / chat_stream / achat_stream)
   │
   ├── HttpxOpenAITransport   (现状：OpenAI-compatible 协议)
   ├── HttpxAnthropicTransport (现状：Anthropic Messages 协议)
   └── …                      (未来：OpenAI SDK / aiohttp / 自家 SDK)
```

Httpx 仍然藏在 ``http_utils.HTTPClient`` 里；transport 用 ``HTTPClient``
做实际的 HTTP 调用。任何"换底层 HTTP 库"的工作量仅限于
``http_utils.py`` + transport 实现本身。
"""
from __future__ import annotations

import json
import uuid as _uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Dict, Iterator, List, Optional

import httpx

from .http_utils import HTTPClient

# ============================================================================
# Provider-neutral 数据类型
# ============================================================================

@dataclass
class ToolCall:
    """Provider 无关的 tool_call"""
    id: str
    name: str
    arguments: Dict[str, Any]


@dataclass
class UsageInfo:
    """Token 用量（可能 provider 没给）"""
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    raw: Optional[Dict[str, Any]] = None


@dataclass
class LLMResponse:
    """单次模型返回的 provider-neutral 视图"""
    text: str = ""
    tool_calls: List[ToolCall] = field(default_factory=list)
    stop_reason: Optional[str] = None     # "end_turn" / "stop" / "tool_use" / "max_tokens" …
    usage: Optional[UsageInfo] = None
    raw: Any = None                       # 原始 provider 响应（供高级用法）


@dataclass
class LLMEvent:
    """流式响应里的一帧"""
    type: str                            # "text" | "tool_call" | "usage" | "done" | "error"
    text: str = ""
    tool_call: Optional[ToolCall] = None
    usage: Optional[UsageInfo] = None
    stop_reason: Optional[str] = None     # "end_turn" / "stop" / "tool_use" / "max_tokens" …
    raw: Any = None


@dataclass
class ChatRequest:
    """Agent 传给 transport 的请求（中性的）"""
    model: str
    system: str
    messages: List[Dict[str, Any]]        # [{"role": "user|assistant|tool", "content": ...}]
    tools: List[Dict[str, Any]] = field(default_factory=list)   # OpenAI-style tool schema
    stream: bool = False
    temperature: Optional[float] = None
    max_tokens: Optional[int] = None
    # provider 特定透传
    extra: Dict[str, Any] = field(default_factory=dict)


# ============================================================================
# Transport 抽象
# ============================================================================

class LLMTransport(ABC):
    """
    LLM Transport 抽象接口。

    实现需要提供：
    - ``chat(req) -> LLMResponse``         同步非流
    - ``achat(req) -> LLMResponse``        异步非流
    - ``chat_stream(req) -> Iterator[LLMEvent]``       同步流
    - ``achat_stream(req) -> AsyncIterator[LLMEvent]``  异步流
    """

    @abstractmethod
    def chat(self, req: ChatRequest) -> LLMResponse: ...

    @abstractmethod
    async def achat(self, req: ChatRequest) -> LLMResponse: ...

    @abstractmethod
    def chat_stream(self, req: ChatRequest) -> Iterator[LLMEvent]: ...

    @abstractmethod
    async def achat_stream(self, req: ChatRequest) -> AsyncIterator[LLMEvent]: ...


# ============================================================================
# HttpxOpenAITransport — OpenAI-compatible Chat Completions
# ============================================================================

class HttpxOpenAITransport(LLMTransport):
    """
    任何兼容 OpenAI Chat Completions 的 endpoint（OpenAI、Azure、Qwen、vLLM、Ollama…）
    """

    def __init__(
        self,
        endpoint: str,
        api_key: str,
        *,
        client: Optional[HTTPClient] = None,
        default_timeout: float = 60.0,
    ):
        self.endpoint = endpoint
        self.headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
        self._client = client or HTTPClient(default_timeout=default_timeout)

    def _build_payload(self, req: ChatRequest) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "model": req.model,
            "messages": [{"role": "system", "content": req.system}, *req.messages],
            "stream": req.stream,
        }
        if req.tools:
            payload["tools"] = req.tools
            payload["tool_choice"] = "auto"
        if req.temperature is not None:
            payload["temperature"] = req.temperature
        if req.max_tokens is not None:
            payload["max_tokens"] = req.max_tokens
        payload.update(req.extra)
        return payload

    def _response_to_llm(self, data: Dict[str, Any]) -> LLMResponse:
        choice = (data.get("choices") or [{}])[0]
        message = choice.get("message") or {}
        text = message.get("content") or ""
        tool_calls: List[ToolCall] = []
        for tc in message.get("tool_calls") or []:
            fn = tc.get("function") or {}
            args = _parse_json_args(fn.get("arguments") or "")
            tool_calls.append(ToolCall(
                id=tc.get("id", str(_uuid.uuid4())),
                name=fn.get("name", ""),
                arguments=args,
            ))
        return LLMResponse(
            text=text if isinstance(text, str) else "",
            tool_calls=tool_calls,
            stop_reason=choice.get("finish_reason"),
            usage=_parse_usage_safe(data),
            raw=data,
        )

    def chat(self, req: ChatRequest) -> LLMResponse:
        payload = self._build_payload(req)
        rsp = self._client.post(
            self.endpoint,
            headers=self.headers,
            json=payload,
            stream=False,
        )
        return self._response_to_llm(rsp.json())

    async def achat(self, req: ChatRequest) -> LLMResponse:
        from .http_utils import AsyncHTTPClient
        async with AsyncHTTPClient(default_timeout=60.0) as c:
            payload = self._build_payload(req)
            rsp = await c.apost(self.endpoint, headers=self.headers, json=payload)
            return self._response_to_llm(rsp.json())

    def chat_stream(self, req: ChatRequest) -> Iterator[LLMEvent]:
        payload = self._build_payload(req)
        # 走 stream=True：HTTPClient 返回的 Response 需要 iter_lines
        rsp = self._client.post(
            self.endpoint,
            headers={**self.headers, "Accept": "text/event-stream"},
            json=payload,
            stream=True,
        )
        return self._iter_openai_sse(rsp)

    async def achat_stream(self, req: ChatRequest) -> AsyncIterator[LLMEvent]:
        from .http_utils import AsyncHTTPClient
        async with AsyncHTTPClient(default_timeout=60.0) as c:
            payload = self._build_payload(req)
            rsp = await c.apost(
                self.endpoint,
                headers={**self.headers, "Accept": "text/event-stream"},
                json=payload,
                stream=True,
            )
            async for evt in self._aiter_openai_sse(rsp):
                yield evt

    def _iter_openai_sse(self, rsp: httpx.Response) -> Iterator[LLMEvent]:
        """OpenAI-style SSE（每行 ``data: {json}``，最后 ``data: [DONE]``）。
        sync 迭代：逐行喂给共享状态机 ``_process_openai_sse_line``。"""
        state = _OpenAISSEState()
        for line in rsp.iter_lines():
            yield from _process_openai_sse_line(line, state)

    async def _aiter_openai_sse(self, rsp: httpx.Response) -> AsyncIterator[LLMEvent]:
        """同上，但 httpx aiter_lines() 是异步的。"""
        state = _OpenAISSEState()
        async for line in rsp.aiter_lines():
            for evt in _process_openai_sse_line(line, state):
                yield evt


# ============================================================================
# OpenAI Chat Completions SSE 共享状态机（chat_stream / achat_stream 共用）
# ============================================================================

class _OpenAISSEState:
    """OpenAI Chat Completions SSE 解析状态。"""

    def __init__(self) -> None:
        self.current_calls: Dict[int, Dict[str, Any]] = {}
        self.finish_reason: Optional[str] = None
        self.usage: Optional[UsageInfo] = None


def _process_openai_sse_line(line, state: _OpenAISSEState) -> List[LLMEvent]:
    """处理一行 OpenAI Chat Completions SSE，返回要 yield 的 LLMEvent 列表。"""
    out: List[LLMEvent] = []
    if not line or not line.startswith("data: "):
        return out
    data = line[len("data: "):]
    if data == "[DONE]":
        # flush 累积的 tool_calls + 终止事件
        for slot in state.current_calls.values():
            args = _parse_json_args(slot["arguments"])
            out.append(LLMEvent(
                type="tool_call",
                tool_call=ToolCall(
                    id=slot["id"] or str(_uuid.uuid4()),
                    name=slot["name"],
                    arguments=args,
                ),
            ))
        out.append(LLMEvent(type="done", stop_reason=state.finish_reason, usage=state.usage, raw=None))
        return out
    try:
        chunk = json.loads(data)
    except json.JSONDecodeError:
        return out
    for choice in chunk.get("choices") or []:
        delta = choice.get("delta") or {}
        state.finish_reason = choice.get("finish_reason") or state.finish_reason
        content = delta.get("content")
        if content:
            out.append(LLMEvent(type="text", text=content))
        for tc in delta.get("tool_calls") or []:
            idx = tc.get("index", 0)
            slot = state.current_calls.setdefault(idx, {
                "id": tc.get("id", ""),
                "name": (tc.get("function") or {}).get("name", ""),
                "arguments": "",
            })
            if "id" in tc and tc["id"]:
                slot["id"] = tc["id"]
            fn = tc.get("function") or {}
            if fn.get("name"):
                slot["name"] = fn["name"]
            if fn.get("arguments"):
                slot["arguments"] += fn["arguments"]
    u = chunk.get("usage")
    if u:
        state.usage = _parse_usage_safe(chunk)
    return out


def _parse_json_args(raw: str) -> Dict[str, Any]:
    """JSON 解析失败时把原文包到 ``{"_raw": raw}``。"""
    if not raw:
        return {}
    try:
        args = json.loads(raw)
    except json.JSONDecodeError:
        return {"_raw": raw}
    if not isinstance(args, dict):
        return {}
    return args


def _parse_usage_safe(raw: Optional[Dict[str, Any]]) -> Optional[UsageInfo]:
    if not isinstance(raw, dict):
        return None
    u = raw.get("usage") or {}
    if not isinstance(u, dict):
        return None
    return UsageInfo(
        prompt_tokens=int(u.get("prompt_tokens", 0)),
        completion_tokens=int(u.get("completion_tokens", 0)),
        total_tokens=int(u.get("total_tokens", 0)),
        raw=u,
    )


def _parse_usage_anthropic(raw: Optional[Dict[str, Any]]) -> Optional[UsageInfo]:
    """Anthropic Messages API 的 usage 字段：``input_tokens`` / ``output_tokens``，无 ``prompt_tokens`` alias。"""
    if not isinstance(raw, dict):
        return None
    u = raw.get("usage") or {}
    if not isinstance(u, dict):
        return None
    in_t = int(u.get("input_tokens", 0))
    out_t = int(u.get("output_tokens", 0))
    return UsageInfo(
        prompt_tokens=in_t,
        completion_tokens=out_t,
        total_tokens=in_t + out_t,
        raw=u,
    )


# ============================================================================
# HttpxOpenAIResponsesTransport — OpenAI Responses API（v0.4.2+）
# ============================================================================
#
# 兼容 OpenAI 新接口 https://platform.openai.com/docs/api-reference/responses
# 区别于 Chat Completions：
#   - endpoint: /v1/responses
#   - 请求体：input（typed items）替代 messages，instructions 替代 system，
#             max_output_tokens 替代 max_tokens，tools.parameters 替代 tools.function.parameters
#   - 响应体：output 数组（每项 type: "message" | "function_call" | …）替代 choices
#   - 流事件：response.created / response.output_item.added / response.output_text.delta / …
#
# 用法：register_protocol("openai-responses", _OpenAIResponsesBase)，
# 用户的 Agent class 写 protocol = "openai-responses"。

class HttpxOpenAIResponsesTransport(LLMTransport):
    """OpenAI Responses API 兼容 transport（v0.4.2+）。"""

    def __init__(
        self,
        endpoint: str,
        api_key: str,
        *,
        client: Optional[HTTPClient] = None,
        default_timeout: float = 60.0,
    ):
        self.endpoint = endpoint
        self.headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
        self._client = client or HTTPClient(default_timeout=default_timeout)

    def _build_payload(self, req: ChatRequest) -> Dict[str, Any]:
        """把中性 ChatRequest 转成 Responses API 请求体。"""
        # messages → input（typed items）
        input_items: List[Dict[str, Any]] = []
        for m in req.messages:
            role = m.get("role")
            content = m.get("content")
            if isinstance(content, list):
                # 多模态 / 复杂 content：直接展开
                input_items.append({"role": role, "content": content})
            else:
                input_items.append({"role": role, "content": content or ""})

        payload: Dict[str, Any] = {
            "model": req.model,
            "input": input_items,
            "stream": req.stream,
        }
        if req.system:
            payload["instructions"] = req.system
        if req.tools:
            # Chat Completions schema: {type:"function", function:{name,description,parameters}}
            # → Responses schema: {type:"function", name, description, parameters}
            converted = []
            for t in req.tools:
                if t.get("type") == "function" and "function" in t:
                    fn = t["function"]
                    converted.append({
                        "type": "function",
                        "name": fn.get("name"),
                        "description": fn.get("description", ""),
                        "parameters": fn.get("parameters", {"type": "object", "properties": {}}),
                    })
                else:
                    converted.append(t)
            payload["tools"] = converted
            payload["tool_choice"] = "auto"
        if req.temperature is not None:
            payload["temperature"] = req.temperature
        if req.max_tokens is not None:
            payload["max_output_tokens"] = req.max_tokens  # Responses API 用这个名字
        payload.update(req.extra)
        return payload

    def _parse_usage(self, raw: Optional[Dict[str, Any]]) -> Optional[UsageInfo]:
        if not isinstance(raw, dict):
            return None
        u = raw.get("usage") or {}
        if not isinstance(u, dict):
            return None
        # Responses API: input_tokens / output_tokens / total_tokens
        prompt = int(u.get("input_tokens", u.get("prompt_tokens", 0)))
        completion = int(u.get("output_tokens", u.get("completion_tokens", 0)))
        total = int(u.get("total_tokens", prompt + completion))
        return UsageInfo(
            prompt_tokens=prompt,
            completion_tokens=completion,
            total_tokens=total,
            raw=u,
        )

    def _output_to_text_and_tools(self, output: List[Dict[str, Any]]):
        """Responses API output[] → (text, tool_calls, stop_reason)。"""
        text_parts: List[str] = []
        tool_calls: List[ToolCall] = []
        stop_reason: Optional[str] = None
        for item in output or []:
            t = item.get("type")
            if t == "message":
                # content 通常是 [{type:"output_text", text:"..."}]
                for c in item.get("content", []) or []:
                    if c.get("type") == "output_text":
                        text_parts.append(c.get("text", ""))
            elif t == "function_call":
                args_raw = item.get("arguments", "")
                if isinstance(args_raw, str):
                    try:
                        args = json.loads(args_raw) if args_raw else {}
                    except json.JSONDecodeError:
                        args = {"_raw": args_raw}
                else:
                    args = args_raw
                if not isinstance(args, dict):
                    args = {}
                tool_calls.append(ToolCall(
                    id=item.get("call_id", item.get("id", str(_uuid.uuid4()))),
                    name=item.get("name", ""),
                    arguments=args,
                ))
            elif t == "reasoning":
                # 推理 token：忽略文本
                pass
        return "".join(text_parts), tool_calls, stop_reason

    def _response_to_llm(self, data: Dict[str, Any]) -> LLMResponse:
        text, tool_calls, _ = self._output_to_text_and_tools(data.get("output", []))
        return LLMResponse(
            text=text,
            tool_calls=tool_calls,
            stop_reason=data.get("status"),
            usage=self._parse_usage(data),
            raw=data,
        )

    def chat(self, req: ChatRequest) -> LLMResponse:
        payload = self._build_payload(req)
        rsp = self._client.post(
            self.endpoint,
            headers=self.headers,
            json=payload,
            stream=False,
        )
        return self._response_to_llm(rsp.json())

    async def achat(self, req: ChatRequest) -> LLMResponse:
        from .http_utils import AsyncHTTPClient
        async with AsyncHTTPClient(default_timeout=60.0) as c:
            payload = self._build_payload(req)
            rsp = await c.apost(self.endpoint, headers=self.headers, json=payload)
            return self._response_to_llm(rsp.json())

    def chat_stream(self, req: ChatRequest) -> Iterator[LLMEvent]:
        payload = self._build_payload(req)
        rsp = self._client.post(
            self.endpoint,
            headers={**self.headers, "Accept": "text/event-stream"},
            json=payload,
            stream=True,
        )
        state = _ResponsesSSEState(self._parse_usage)
        for line in rsp.iter_lines():
            yield from _process_responses_sse_line(line, state)

    async def achat_stream(self, req: ChatRequest) -> "AsyncIterator[LLMEvent]":
        from .http_utils import AsyncHTTPClient
        async with AsyncHTTPClient(default_timeout=60.0) as c:
            payload = self._build_payload(req)
            rsp = await c.apost(
                self.endpoint,
                headers={**self.headers, "Accept": "text/event-stream"},
                json=payload,
                stream=True,
            )
            state = _ResponsesSSEState(self._parse_usage)
            async for line in rsp.aiter_lines():
                for evt in _process_responses_sse_line(line, state):
                    yield evt


# ============================================================================
# Responses API SSE 共享状态机（chat_stream / achat_stream 共用）
# ============================================================================

class _ResponsesSSEState:
    """Responses API SSE 解析状态（同步 / 异步两条流共用）。

    单轮 Responses API 可发多个 function_call，因此 tool_calls 用 list 累积。
    """

    def __init__(self, parse_usage):
        self.parse_usage = parse_usage
        self.text_chunks: List[str] = []
        self.tool_calls: List[Dict[str, Any]] = []
        self._current_idx: int = 0
        self.final_usage: Optional[UsageInfo] = None
        self.final_stop_reason: Optional[str] = None

    def _current_call(self) -> Dict[str, Any]:
        """拿到当前 in-progress tool_call 槽位；必要时补一个空槽。"""
        while len(self.tool_calls) <= self._current_idx:
            self.tool_calls.append({"id": "", "name": "", "arguments": ""})
        return self.tool_calls[self._current_idx]

    def _next_call(self) -> None:
        """前进到下一个 tool_call 槽位。"""
        self._current_idx += 1


def _process_responses_sse_line(line, state) -> List[LLMEvent]:
    """处理一行 Responses SSE，返回要 yield 的 LLMEvent 列表。

    Responses API 事件：
      response.created / response.output_item.added /
      response.content_part.added / response.output_text.delta / .done /
      response.function_call_arguments.delta / .done /
      response.output_item.done / response.completed
    """
    out: List[LLMEvent] = []
    if not line or not line.startswith("data: "):
        return out
    payload = line[len("data: "):]
    if payload == "[DONE]":
        # flush 累积的所有 tool_calls（同一轮 Responses API 可发多个 function_call）
        for slot in state.tool_calls:
            args_raw = slot["arguments"]
            try:
                args = json.loads(args_raw) if args_raw else {}
            except json.JSONDecodeError:
                args = {"_raw": args_raw}
            if not isinstance(args, dict):
                args = {}
            out.append(LLMEvent(
                type="tool_call",
                tool_call=ToolCall(
                    id=slot["id"] or str(_uuid.uuid4()),
                    name=slot["name"],
                    arguments=args,
                ),
                raw=None,
            ))
        state.tool_calls.clear()
        return out
    try:
        evt = json.loads(payload)
    except json.JSONDecodeError:
        return out

    etype = evt.get("type", "")
    if etype == "response.output_text.delta":
        delta = evt.get("delta", "")
        if delta:
            state.text_chunks.append(delta)
            out.append(LLMEvent(type="text", text=delta, raw=evt))
    elif etype == "response.function_call_arguments.delta":
        # 把累积挂到当前 slot
        cur = state._current_call()
        cur["arguments"] += evt.get("delta", "")
    elif etype == "response.function_call_arguments.done":
        cur = state._current_call()
        args_raw = cur["arguments"]
        try:
            args = json.loads(args_raw) if args_raw else {}
        except json.JSONDecodeError:
            args = {"_raw": args_raw}
        if not isinstance(args, dict):
            args = {}
        out.append(LLMEvent(
            type="tool_call",
            tool_call=ToolCall(
                id=cur["id"] or str(_uuid.uuid4()),
                name=cur["name"],
                arguments=args,
            ),
            raw=evt,
        ))
        state._next_call()
    elif etype == "response.output_item.added":
        item = evt.get("item", {})
        if item.get("type") == "function_call":
            slot = state._current_call()
            slot["id"] = item.get("call_id", item.get("id", ""))
            slot["name"] = item.get("name", "")
    elif etype == "response.completed":
        resp = evt.get("response", {})
        state.final_usage = state.parse_usage(resp)
        state.final_stop_reason = resp.get("status")
        out.append(LLMEvent(
            type="done",
            stop_reason=state.final_stop_reason,
            usage=state.final_usage,
            raw=evt,
        ))
    elif etype == "error":
        out.append(LLMEvent(type="error", text=evt.get("message", ""), raw=evt))
    return out


# ============================================================================
# HttpxAnthropicTransport — Anthropic Messages API
# ============================================================================

class HttpxAnthropicTransport(LLMTransport):
    """
    Anthropic Messages API（claude 系列；model_name 由用户显式提供）
    """

    def __init__(
        self,
        endpoint: str,
        api_key: str,
        *,
        anthropic_version: str = "2023-06-01",
        max_tokens: int = 4096,
        client: Optional[HTTPClient] = None,
    ):
        self.endpoint = endpoint
        self.headers = {
            "x-api-key": api_key,
            "anthropic-version": anthropic_version,
            "Content-Type": "application/json",
        }
        self.max_tokens = max_tokens
        self._client = client or HTTPClient(default_timeout=60.0)

    @staticmethod
    def _convert_tools(tools: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        out: List[Dict[str, Any]] = []
        for s in tools:
            if s.get("type") == "function" and "function" in s:
                fn = s["function"]
                out.append({
                    "name": fn.get("name"),
                    "description": fn.get("description", ""),
                    "input_schema": fn.get("parameters") or {"type": "object", "properties": {}},
                })
            else:
                out.append(s)
        return out

    def _build_payload(self, req: ChatRequest) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "model": req.model,
            "system": req.system,
            "messages": req.messages,
            "max_tokens": req.max_tokens or self.max_tokens,
            "stream": req.stream,
        }
        if req.tools:
            payload["tools"] = self._convert_tools(req.tools)
        if req.temperature is not None:
            payload["temperature"] = req.temperature
        payload.update(req.extra)
        return payload

    def _response_to_llm(self, data: Dict[str, Any]) -> LLMResponse:
        blocks = data.get("content") or []
        text = "".join(b.get("text", "") for b in blocks if b.get("type") == "text")
        tool_calls: List[ToolCall] = []
        for b in blocks:
            if b.get("type") == "tool_use":
                args = b.get("input") or {}
                tool_calls.append(ToolCall(
                    id=b.get("id", str(_uuid.uuid4())),
                    name=b.get("name", ""),
                    arguments=args if isinstance(args, dict) else {},
                ))
        return LLMResponse(
            text=text,
            tool_calls=tool_calls,
            stop_reason=data.get("stop_reason"),
            usage=_parse_usage_anthropic(data),
            raw=data,
        )

    def chat(self, req: ChatRequest) -> LLMResponse:
        payload = self._build_payload(req)
        rsp = self._client.post(self.endpoint, headers=self.headers, json=payload, stream=False)
        return self._response_to_llm(rsp.json())

    async def achat(self, req: ChatRequest) -> LLMResponse:
        from .http_utils import AsyncHTTPClient
        async with AsyncHTTPClient(default_timeout=60.0) as c:
            payload = self._build_payload(req)
            rsp = await c.apost(self.endpoint, headers=self.headers, json=payload)
            return self._response_to_llm(rsp.json())

    def chat_stream(self, req: ChatRequest) -> Iterator[LLMEvent]:
        payload = self._build_payload(req)
        rsp = self._client.post(
            self.endpoint,
            headers={**self.headers, "Accept": "text/event-stream"},
            json=payload,
            stream=True,
        )
        return self._iter_anthropic_sse(rsp)

    async def achat_stream(self, req: ChatRequest) -> AsyncIterator[LLMEvent]:
        from .http_utils import AsyncHTTPClient
        async with AsyncHTTPClient(default_timeout=60.0) as c:
            payload = self._build_payload(req)
            rsp = await c.apost(
                self.endpoint,
                headers={**self.headers, "Accept": "text/event-stream"},
                json=payload,
                stream=True,
            )
            async for evt in self._aiter_anthropic_sse(rsp):
                yield evt

    def _iter_anthropic_sse(self, rsp: httpx.Response) -> Iterator[LLMEvent]:
        """Anthropic SSE（``event: <name>`` 后接 ``data: <json>``）。
        sync 迭代：逐行喂给共享状态机 ``_process_anthropic_sse_line``，遇 message_stop 终止。"""
        state = _AnthropicSSEState(_parse_usage_anthropic)
        for line in rsp.iter_lines():
            for evt in _process_anthropic_sse_line(line, state):
                yield evt
            if state.stopped:
                break

    async def _aiter_anthropic_sse(self, rsp: httpx.Response) -> AsyncIterator[LLMEvent]:
        state = _AnthropicSSEState(_parse_usage_anthropic)
        async for line in rsp.aiter_lines():
            for evt in _process_anthropic_sse_line(line, state):
                yield evt
            if state.stopped:
                break


# ============================================================================
# Anthropic Messages API SSE 共享状态机（chat_stream / achat_stream 共用）
# ============================================================================

class _AnthropicSSEState:
    """Anthropic SSE 解析状态（content_block + 累积 + done 拦截）。"""

    def __init__(self, parse_usage) -> None:
        self.parse_usage = parse_usage
        self.event_type: Optional[str] = None
        self.current: Optional[Dict[str, Any]] = None  # 进行中的 content_block
        self.json_buf = ""
        self.finish_reason: Optional[str] = None
        self.usage: Optional[UsageInfo] = None
        self.stopped = False  # 收到 message_stop


def _process_anthropic_sse_line(line, state: _AnthropicSSEState) -> List[LLMEvent]:
    """处理一行 Anthropic SSE，返回要 yield 的 LLMEvent 列表。

    关键事件：
      content_block_start / content_block_delta / content_block_stop
      message_delta / message_stop
    """
    out: List[LLMEvent] = []
    if line is None:
        return out
    if line.startswith("event: "):
        state.event_type = line[len("event: "):].strip()
        return out
    if not line.startswith("data: "):
        return out
    try:
        evt = json.loads(line[len("data: "):])
    except json.JSONDecodeError:
        return out
    etype = evt.get("type") or state.event_type

    if etype == "content_block_start":
        cb = evt.get("content_block") or {}
        state.current = {
            "type": cb.get("type", "text"),
            "id": cb.get("id"),
            "name": cb.get("name"),
            "text": cb.get("text", "") or "",
            "input": {},
        }
        state.json_buf = ""
    elif etype == "content_block_delta":
        if state.current is None:
            return out
        delta = evt.get("delta") or {}
        if delta.get("type") == "text_delta":
            chunk = delta.get("text", "")
            state.current["text"] = state.current.get("text", "") + chunk
            out.append(LLMEvent(type="text", text=chunk))
        elif delta.get("type") == "input_json_delta":
            state.json_buf += delta.get("partial_json", "")
    elif etype == "content_block_stop":
        if state.current is not None and state.current.get("type") == "tool_use":
            state.current["input"] = _parse_json_args(state.json_buf)
            out.append(LLMEvent(
                type="tool_call",
                tool_call=ToolCall(
                    id=state.current.get("id") or str(_uuid.uuid4()),
                    name=state.current.get("name", ""),
                    arguments=state.current.get("input", {}),
                ),
            ))
        state.current = None
        state.json_buf = ""
    elif etype == "message_delta":
        delta = evt.get("delta") or {}
        if "stop_reason" in delta:
            state.finish_reason = delta["stop_reason"]
        if "usage" in evt:
            state.usage = state.parse_usage(evt)
    elif etype == "message_stop":
        state.stopped = True
        out.append(LLMEvent(
            type="done",
            stop_reason=state.finish_reason,
            usage=state.usage,
            raw=None,
        ))
    return out
