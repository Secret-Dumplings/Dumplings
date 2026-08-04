# -*- coding: utf-8 -*-
"""
dumplingsAI Agent 统一实现（v0.4.2+）。

之前 OpenAI / Anthropic 两个 Agent 类在 ``Agent_Base_.py`` 和
``anthropic_agent.py``，~2000 行大量重复。v0.4.2 合并为单一 ``agent.py``，
协议差异通过 mixin + ``protocol`` 字段分发。

公开 API（向后兼容）：

- ``dumplingsAI.Agent``（占位类，``protocol`` 字段决定继承）
- ``dumplingsAI.agent``（小写别名，继承中转）
- ``dumplingsAI.BaseAgent``（OpenAI 协议）
- ``dumplingsAI.anthropic_agent.AnthropicAgent``（Anthropic 协议）
- ``register_protocol(name, base_cls)``（第三方扩展）
"""
from __future__ import annotations

import json
import os
import platform
import re
import threading
import time
import uuid as _uuid
from typing import List, Optional

try:
    from .agent_queue import get_call_chain, get_default_queue
    from .agent_tool import _builtin_promote_overrides, builtin_tool, tool_registry
    from .llm_transport import (
        ChatRequest,
        HttpxAnthropicTransport,
        HttpxOpenAIResponsesTransport,
        HttpxOpenAITransport,
        LLMResponse,
    )
    from .logging_config import logger
    from .persistence import _auto_save, _auto_save_async
    from .tool_runner import ToolRunner
except ImportError:
    raise ImportError("不可单独执行")


# ============================================================================
# 协议注册表（v0.4.2+）
# ============================================================================

_PROTOCOL_BASES: dict = {}


def register_protocol(name: str, base_cls: type) -> None:
    """注册协议 → 真实基类映射（第三方可扩展）。"""
    _PROTOCOL_BASES[name.lower()] = base_cls


def list_protocols() -> list:
    return sorted(_PROTOCOL_BASES)


def _resolve_protocol_base(name: str) -> type:
    base = _PROTOCOL_BASES.get(name.lower())
    if base is None:
        raise ValueError(
            f"protocol={name!r} 不支持。已注册：{list_protocols()}"
        )
    return base


# ============================================================================
# Metaclass
# ============================================================================

class _ProtocolMeta(type):
    """``Agent`` 占位 → 真实基类（OpenAI / Anthropic）。

    关键：用 ``b.__name__ == "Agent"`` 字符串比较代替 ``b is Agent``。
    因为在 ``class Agent(...)`` 自定义过程中，``Agent`` 名字尚未绑定到模块 globals，
    会 NameError。用名字比较避免循环。
    """

    def __new__(mcs, name, bases, namespace, **kwargs):
        # 检测占位基类
        has_placeholder = any(getattr(b, "__name__", "") == "Agent" for b in bases)
        if has_placeholder:
            protocol = namespace.get("protocol", "openai")
            if not isinstance(protocol, str):
                raise TypeError(
                    f"{name}.protocol 必须是字符串，当前是 {type(protocol).__name__}"
                )
            real_base = _resolve_protocol_base(protocol.lower())
            new_bases = tuple(
                real_base if getattr(b, "__name__", "") == "Agent" else b
                for b in bases
            )
            return super().__new__(mcs, name, new_bases, namespace, **kwargs)
        return super().__new__(mcs, name, bases, namespace, **kwargs)


# 协议无关的 Agent 占位类 —— 必须在 _OpenAIBase / _AnthropicBase 之前定义，
# 因为它们的 metaclass 引用 ``Agent`` 类对象。
class Agent(metaclass=_ProtocolMeta):
    """协议无关的 Agent 工厂占位类。

    通过类属性 ``protocol`` 决定实际继承 ``BaseAgent`` 或 ``AnthropicAgent``::

        @dumplingsAI.register_agent("uuid-1", "my_agent")
        class MyAgent(dumplingsAI.Agent):
            protocol = "anthropic"
            ...
        # MyAgent 实际是 AnthropicAgent 的子类。
    """

    protocol: str = "openai"


# 小写别名（继承中转用 / 大小写 A 不区分）
agent = Agent


# ============================================================================
# 共享方法（mixin）
# ============================================================================

class _AgentCommon:
    """OpenAI / Anthropic 共享方法 mixin。"""

    prompt: Optional[str] = None
    api_provider: Optional[str] = None
    model_name: Optional[str] = None
    api_key: Optional[str] = None
    fc_model: bool = True
    stream: bool = True
    description: Optional[str] = None
    tool_timeout: float = 60.0
    tool_max_workers: int = 8

    # v0.4.2+：连通性测试可关
    enable_connectivity: bool = True

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)
        _builtin_promote_overrides(cls)
        if cls.pack is not _AgentCommon.pack and cls.out is _AgentCommon.out:
            logger.warning(
                "[dumplingsAI] 检测到子类 {} 覆写了 pack() 但没有覆写 out()。"
                "请覆写 out(content) 而不是 pack()。".format(cls.__name__)
            )

    def __init__(self, new_load: bool = True):
        self.uuid = self.__class__.uuid
        self.name = self.__class__.name
        self.stream_run = False
        self.current_task_id = None
        self.tool_call_hooks: list = []

        self._tool_runner = ToolRunner(
            timeout=self.tool_timeout,
            max_workers=self.tool_max_workers,
        )

        agent_name = getattr(self.__class__, "name", None) or getattr(self.__class__, "__name__", None)
        if agent_name and self.uuid:
            tool_registry.register_agent_uuid(self.uuid, agent_name)

        self._build_system_prompt()

        self.headers = {"Content-Type": "application/json"}
        if self.api_key:
            self.headers["Authorization"] = f"Bearer {self.api_key}"

        self.os_name = platform.system()
        self.conversations_folder = os.getcwd()
        if self.os_name == "Windows":
            self.os_main_folder = os.getenv("USERPROFILE")
        elif self.os_name == "Linux":
            self.os_main_folder = os.path.expanduser("~")
        elif self.os_name == "Darwin":
            self.os_main_folder = os.getenv("HOME")

        if self.enable_connectivity:
            threading.Thread(target=self._connectivity, daemon=True).start()

    def _build_system_prompt(self) -> None:
        """prompt + 工具清单 + Skills + uuid 尾巴。"""
        tools_info = tool_registry.get_all_tools_info(self.uuid)
        tools_prompt = ""
        tools_list = list(tools_info.keys())

        builtin_schemas = tool_registry.collect_builtin_tools(self)
        builtin_names = {s["function"]["name"] for s in builtin_schemas}
        for name in builtin_names:
            if name not in tools_list:
                tools_list.append(name)

        if tools_list:
            tools_prompt = "\n\n你可以使用以下工具：\n"
            for name, info in tools_info.items():
                tools_prompt += f"- {name}: {info['description']}\n"
            for s in builtin_schemas:
                n = s["function"]["name"]
                if n in tools_list and n not in tools_info:
                    tools_prompt += f"- {n}: {s['function']['description']}\n"
            if not self.fc_model:
                tools_prompt += (
                    "在使用xml格式的工具时应采用（无参数调用）<工具名></工具名>"
                    "（含参数调用）<工具名><参数1>放入你想传入的内容</参数1>...</工具名>"
                )

        try:
            from .skill import skill_registry
            tools_prompt += skill_registry.get_skills_prompt_text(self.uuid)
        except ImportError:
            pass

        self.system_prompt = (
            (self.prompt or "") + tools_prompt + ", 你的uuid " + str(self.uuid)
        )
        self.history = [{"role": "system", "content": self.system_prompt}]

    def _generate_task_id(self) -> str:
        return str(_uuid.uuid4())

    def _get_timestamp(self) -> int:
        return int(time.time() * 1000)

    def _execute_hooks(self, event_type, tool_name, tool_args, tool_result=None):
        for hook in self.tool_call_hooks:
            try:
                hook(
                    event_type=event_type,
                    tool_name=tool_name,
                    tool_args=tool_args,
                    tool_result=tool_result,
                    task_id=self.current_task_id,
                )
            except Exception as e:
                logger.error(f"钩子执行失败：{e}")

    def register_tool_hook(self, hook_func):
        self.tool_call_hooks.append(hook_func)

    def save_state(self, key: str, backend: Optional[str] = None) -> None:
        from .persistence import save_state as _save_state
        _save_state(self, key, backend=backend)

    @classmethod
    def load_state(cls, key: str, backend: Optional[str] = None):
        from .persistence import load_state as _load_state
        return _load_state(key, backend=backend)

    # ---- shared builtin_tools ----
    @builtin_tool(
        description="请求其他Agent帮助，调用另一个Agent完成子任务并把它的回复作为工具结果返回。",
        params={
            "agent_id": "目标Agent的UUID或名称（已在 dumplingsAI.agent_list 中注册）",
            "message": "要发送给目标Agent的内容",
        },
    )
    def ask_for_help(self, agent_id: str, message: str) -> str:
        """请求另一个 Agent 协助（支持 UUID 或名称）"""
        from .Agent_list import agent_list

        target = agent_list.get(agent_id)
        if target is None:
            target = next(
                (a for a in agent_list.values() if a.name == agent_id),
                None,
            )
        if target is None:
            return f"未找到 Agent：{agent_id}"
        try:
            chain = get_call_chain()
            queue = get_default_queue()
            return queue.submit(
                target_uuid=target.uuid,
                call_fn=lambda: str(target.conversation_with_tool(message)),
                caller_chain=chain,
            )
        except Exception as e:
            logger.error(f"ask_for_help 失败：{e}")
            return f"协助请求失败：{e}"

    @builtin_tool(
        description="列出当前系统内所有已注册的Agent及其UUID/名称，便于发现协作对象。",
    )
    def list_agents(self) -> str:
        from .Agent_list import agent_list
        lines = []
        seen = set()
        for key, inst in agent_list.items():
            uuid = getattr(inst, "uuid", None)
            if uuid and uuid == key and uuid not in seen:
                seen.add(uuid)
                lines.append(f"- name={inst.name} uuid={uuid}")
        return "\n".join(lines) if lines else "(无已注册 Agent)"

    @builtin_tool(
        description="标记当前任务完成并退出对话循环；可附 report_content 作为最终汇报。",
        params={"report_content": "最终汇报内容（可空）"},
    )
    def attempt_completion(self, report_content: str = "") -> str:
        self.pack(finish_task=True)
        return report_content or ""

    @builtin_tool(
        description="重新拉取你自己当前可用的工具/技能列表，重置系统提示词；当你认为环境已变、想刷新时调用。",
    )
    def reload(self) -> str:
        self._build_system_prompt()
        self.history = []
        logger.info(f"{self.name} 已 reload")
        return "reloaded"

    @builtin_tool(
        description="占位说明：模板注册必须在 Python 代码侧完成（工具调用只能传 JSON，无法注入 Python 类）。",
    )
    def register_template(self, name: str = "", description: str = "") -> str:
        from .Agent_list import list_templates as _list_templates
        items = _list_templates()
        if not items:
            return (
                "模板注册请在 Python 代码侧完成："
                "from dumplingsAI.Agent_list import register_template;"
                "register_template(MyAgent, name='my_agent'。"
                "当前 agent_template_pool 为空。"
            )
        names = "、".join(it["name"] for it in items)
        return (
            "模板注册请在 Python 代码侧完成："
            "from dumplingsAI.Agent_list import register_template;"
            "register_template(MyAgent, name='my_agent'。"
            f"当前 agent_template_pool 内的模板：{names}。"
        )

    @builtin_tool(
        description="把 agent_template_pool 中的某个模板实例化并写入 agent_list。",
        params={"name": "模板名"},
    )
    def activate_template(self, name: str) -> str:
        from .Agent_list import activate_template as _activate
        try:
            _activate(name)
        except KeyError as e:
            return f"激活失败：{e}"
        return (
            f"已激活模板 {name!r}：实例已写入 agent_list。"
            f"可通过 agent_list[{name!r}] 或其 uuid 访问。"
        )

    @builtin_tool(
        description="把 agent_list 中的某个模板实例移除（模板仍保留在池中）。",
        params={"name": "模板名"},
    )
    def deactivate_template(self, name: str) -> str:
        from .Agent_list import deactivate_template as _deactivate
        ok = _deactivate(name)
        return f"已反激活 {name!r}" if ok else f"模板 {name!r} 不在池中"

    @builtin_tool(
        description="查询 agent_template_pool 中的模板清单（只读，不会实例化）。",
        params={"name": "可选：模板名；为空则列出全部"},
    )
    def list_templates(self, name: str = "") -> str:
        from .Agent_list import agent_list, get_template
        from .Agent_list import list_templates as _list_templates
        if name:
            tpl = get_template(name)
            if tpl is None:
                return f"模板 {name!r} 不在 agent_template_pool 中"
            return (
                f"模板 {name!r}: uuid={tpl.get('uuid')!r}, "
                f"description={tpl.get('description')!r}, "
                f"active={name in agent_list}"
            )
        items = _list_templates()
        if not items:
            return "agent_template_pool：（暂无）"
        lines = []
        for it in items:
            lines.append(
                f"- {it['name']} (uuid={it['uuid']}) "
                f"active={it['active']} description={it.get('description')!r}"
            )
        return "agent_template_pool：\n" + "\n".join(lines)

    def get_all_available_tools(self) -> List[str]:
        tools: List[str] = []
        tools_info = tool_registry.get_all_tools_info(self.uuid)
        if tools_info:
            tools.extend(tools_info.keys())
        for s in tool_registry.collect_builtin_tools(self):
            tools.append(s["function"]["name"])
        return tools

    # ---- pack / out ----
    def pack(
        self,
        message=None,
        tool_model: bool = False,
        tool_name: Optional[str] = None,
        tool_parameter=None,
        finish_task: bool = False,
        other: bool = False,
        tool_result=None,
    ) -> None:
        """事件打包：构造 content dict 后转 self.out()。"""
        content: dict = {}
        task_id = self.current_task_id or self._generate_task_id()
        timestamp = self._get_timestamp()

        if finish_task:
            content = {"task": True, "task_id": task_id, "timestamp": timestamp,
                       "ai_uuid": self.uuid, "ai_name": self.name}
        elif tool_model:
            content = {"tool_name": tool_name, "tool_parameter": tool_parameter,
                       "ai_uuid": self.uuid, "ai_name": self.name,
                       "task_id": task_id, "timestamp": timestamp, "task": False}
        elif tool_result is not None:
            content = {"tool_result": tool_result, "tool_name": tool_name,
                       "ai_uuid": self.uuid, "ai_name": self.name,
                       "task_id": task_id, "timestamp": timestamp, "task": False}
        else:
            content = {"message": message, "ai_uuid": self.uuid, "ai_name": self.name,
                       "other": other, "task_id": task_id, "timestamp": timestamp, "task": False}
        self.out(content)

    def out(self, content: dict) -> None:
        """默认打印；通过重写可劫持输出。"""
        if content.get("tool_name"):
            print(f"\n[工具] {content.get('tool_name')} 参数={content.get('tool_parameter')}")
            return
        if content.get("task"):
            print(f"\n[完成] {content.get('message', '')}")
            return
        if content.get("message") is not None:
            print(content.get("message"), end="")

    # ------------------------------------------------------------------
    # 共享对话循环（v0.4.2+）—— 三个协议类共用，协议差异通过钩子注入
    # ------------------------------------------------------------------
    #
    # 协议钩子（子类覆盖）：
    #   - ``_transport_cls``       : LLMTransport 子类（必填）
    #   - ``_endpoint()``          : transport 的请求 URL（默认 api_provider）
    #   - ``_transport_kwargs()``  : transport 构造参数（如 anthropic_version）
    #   - ``_build_user_message()``: user 消息构造（多模态差异）
    #   - ``_collect_tools_schema()``: 工具 schema 收集
    #   - ``_extract_system_and_messages()``: system 抽取
    #   - ``_handle_xml_mode()``   : OpenAI 特有 XML 标签模式（默认不处理）

    _transport_cls: type = None
    _default_max_tokens: Optional[int] = None  # Anthropic 用 4096，OpenAI 不传

    def _endpoint(self) -> str:
        return self.api_provider

    def _transport_kwargs(self) -> dict:
        return {}

    def _handle_xml_mode(self, work_history, full_content):
        """默认不处理 XML 标签模式；OpenAI 协议覆盖。"""
        return None

    def _dispatch_tool(self, name: str, arguments: dict):
        """Pydantic 校验 + ACL 检查 + ToolRunner 执行（三个协议共享）。"""
        from .agent_tool import _validate_tool_args_for
        try:
            arguments = _validate_tool_args_for(self, name, arguments)
        except Exception as e:
            return (f"工具参数校验失败：{e}", None)

        builtin_names = {s["function"]["name"] for s in tool_registry.collect_builtin_tools(self)}
        if name in builtin_names:
            method = getattr(self, name, None)
            if callable(method):
                if arguments:
                    result, async_id = self._tool_runner.submit(
                        method, tool_name=name, timeout=self.tool_timeout, **arguments,
                    )
                else:
                    result, async_id = self._tool_runner.submit(
                        method, tool_name=name, timeout=self.tool_timeout,
                    )
                return result, async_id

        if tool_registry.check_permission(self.uuid, name):
            tool_info = tool_registry.get_tool_info(name)
            if tool_info:
                func = tool_info["function"]
                try:
                    if arguments:
                        result, async_id = self._tool_runner.submit(
                            func, tool_name=name, timeout=self.tool_timeout, **arguments,
                        )
                    else:
                        result, async_id = self._tool_runner.submit(
                            func, tool_name=name, timeout=self.tool_timeout,
                        )
                    return result, async_id
                except TypeError:
                    result, async_id = self._tool_runner.submit(
                        func, tool_name=name, timeout=self.tool_timeout, xml=str(arguments),
                    )
                    return result, async_id
        return (f"找不到工具：{name}", None)

    def _execute_tool_calls(self, work_history, tool_calls_list):
        """共享 FC 工具执行：解析参数 → hooks → Pydantic → ToolRunner → 结果回填。"""
        work_history.append({
            "role": "assistant",
            "content": None,
            "tool_calls": tool_calls_list,
        })
        tool_results = []
        for tool_call in tool_calls_list:
            tool_name = tool_call["function"]["name"]
            tool_id = tool_call["id"]
            try:
                args = json.loads(tool_call["function"]["arguments"])
                self.current_task_id = self._generate_task_id()
                self._execute_hooks("before", tool_name, args)
                logger.debug(f"调用工具 {tool_name}，参数: {args}")
                self.pack(tool_name=tool_name, tool_parameter=args)

                from .agent_tool import _validate_tool_args_for
                args = _validate_tool_args_for(self, tool_name, args)

                async_id = None
                result, async_id = self._dispatch_tool(tool_name, args)
                if async_id is not None:
                    result = f"[tool {tool_name} still running in background as task_id={async_id}]"
                self._execute_hooks("after", tool_name, args, result)
                self.pack(tool_result=result, tool_name=tool_name)
                tool_results.append({
                    "tool_call_id": tool_id, "name": tool_name, "content": result,
                })
            except Exception as e:
                error_msg = f"执行工具 {tool_name} 时出错: {str(e)}"
                logger.error(error_msg)
                if "args" in locals():
                    self._execute_hooks("error", tool_name, args, error_msg)
                tool_results.append({
                    "tool_call_id": tool_id, "name": tool_name, "content": error_msg,
                })
        for result in tool_results:
            work_history.append({
                "role": "tool",
                "tool_call_id": result["tool_call_id"],
                "name": result["name"],
                "content": result["content"],
            })

    def _collect_stream_events(self, transport, req):
        """共享流式事件收集：text / tool_call / usage。返回 (full_content, tool_calls_list)。"""
        full_content = ""
        tool_calls_list: list = []
        self.stream_run = True
        for evt in transport.chat_stream(req):
            if evt.type == "text":
                full_content += evt.text
                self.pack(evt.text, finish_task=False)
            elif evt.type == "tool_call" and evt.tool_call is not None:
                tc = evt.tool_call
                tool_calls_list.append({
                    "id": tc.id, "type": "function",
                    "function": {
                        "name": tc.name,
                        "arguments": json.dumps(tc.arguments, ensure_ascii=False),
                    },
                })
            elif evt.type == "usage" and evt.usage is not None:
                self.stream_run = False
                self.pack(finish_task=True)
                self.pack(
                    f"\n本次请求用量：提示 {evt.usage.prompt_tokens} tokens，"
                    f"生成 {evt.usage.completion_tokens} tokens，"
                    f"总计 {evt.usage.total_tokens} tokens。",
                    other=True,
                )
        return full_content, tool_calls_list

    def _collect_plain_response(self, llm_rsp: LLMResponse):
        """共享非流式响应收集。返回 (full_content, tool_calls_list)。"""
        full_content = llm_rsp.text
        tool_calls_list: list = []
        self.stream_run = False
        if full_content:
            self.pack(full_content, finish_task=False)
        for tc in llm_rsp.tool_calls:
            tool_calls_list.append({
                "id": tc.id, "type": "function",
                "function": {
                    "name": tc.name,
                    "arguments": json.dumps(tc.arguments, ensure_ascii=False),
                },
            })
        if llm_rsp.usage is not None:
            self.pack(finish_task=True)
            self.pack(
                f"\n本次请求用量：提示 {llm_rsp.usage.prompt_tokens} tokens，"
                f"生成 {llm_rsp.usage.completion_tokens} tokens，"
                f"总计 {llm_rsp.usage.total_tokens} tokens。",
                other=True,
            )
        return full_content, tool_calls_list

    @_auto_save
    def conversation_with_tool(self, messages=None, tool: bool = False, images=None):
        """共享对话循环（sync）。协议差异通过钩子注入。"""
        work_history = self.history

        if not tool and messages:
            work_history.append(self._build_user_message(messages, images))

        tools_schema = self._collect_tools_schema() if self.fc_model else []
        system_str, rest_messages = self._extract_system_and_messages(work_history)

        req = ChatRequest(
            model=self.model_name,
            system=system_str,
            messages=rest_messages,
            tools=tools_schema,
            stream=self.stream,
            max_tokens=self._default_max_tokens,
        )

        transport = self._transport_cls(
            endpoint=self._endpoint(),
            api_key=self.api_key,
            **self._transport_kwargs(),
        )

        full_content = ""
        tool_calls_list: list = []
        if self.stream:
            try:
                full_content, tool_calls_list = self._collect_stream_events(transport, req)
            except Exception as e:
                logger.error(f"流式响应处理错误: {e}")
                full_content = ""
        else:
            try:
                llm_rsp: LLMResponse = transport.chat(req)
                full_content, tool_calls_list = self._collect_plain_response(llm_rsp)
            except Exception as e:
                logger.error(f"非流式响应处理错误: {e}")
                full_content = ""

        logger.trace(f"AI 回复内容长度：{len(full_content)}")

        # FC 模式：执行工具 + 递归继续
        if self.fc_model and tool_calls_list:
            self._execute_tool_calls(work_history, tool_calls_list)
            logger.debug("工具执行完成，继续对话")
            return self.conversation_with_tool(tool=True)

        # XML 标签模式（OpenAI 特有钩子；其他协议返回 None）
        xml_result = self._handle_xml_mode(work_history, full_content)
        if xml_result is not None:
            return xml_result
        return full_content

    @_auto_save_async
    async def aconversation_with_tool(self, messages=None, tool: bool = False, images=None):
        """共享对话循环（async）。"""
        work_history = self.history

        if not tool and messages:
            work_history.append(self._build_user_message(messages, images))

        tools_schema = self._collect_tools_schema() if self.fc_model else []
        system_str, rest_messages = self._extract_system_and_messages(work_history)

        req = ChatRequest(
            model=self.model_name,
            system=system_str,
            messages=rest_messages,
            tools=tools_schema,
            stream=self.stream,
            max_tokens=self._default_max_tokens,
        )

        transport = self._transport_cls(
            endpoint=self._endpoint(),
            api_key=self.api_key,
            **self._transport_kwargs(),
        )

        full_content = ""
        tool_calls_list: list = []
        if self.stream:
            try:
                async for evt in transport.achat_stream(req):
                    if evt.type == "text":
                        full_content += evt.text
                        self.pack(evt.text, finish_task=False)
                    elif evt.type == "tool_call" and evt.tool_call is not None:
                        tc = evt.tool_call
                        tool_calls_list.append({
                            "id": tc.id, "type": "function",
                            "function": {
                                "name": tc.name,
                                "arguments": json.dumps(tc.arguments, ensure_ascii=False),
                            },
                        })
                    elif evt.type == "usage" and evt.usage is not None:
                        self.stream_run = False
                        self.pack(finish_task=True)
                        self.pack(
                            f"usage: prompt={evt.usage.prompt_tokens} "
                            f"completion={evt.usage.completion_tokens} "
                            f"total={evt.usage.total_tokens}",
                            other=True,
                        )
            except Exception as e:
                logger.error(f"异步流式响应处理错误: {e}")
                full_content = ""
        else:
            self.stream_run = False
            try:
                llm_rsp: LLMResponse = await transport.achat(req)
                full_content, tool_calls_list = self._collect_plain_response(llm_rsp)
            except Exception as e:
                logger.error(f"异步非流式响应处理错误: {e}")
                full_content = ""

        if self.fc_model and tool_calls_list:
            self._execute_tool_calls(work_history, tool_calls_list)
            return await self.aconversation_with_tool(tool=True)
        return full_content


# ============================================================================
# 协议特定方法 - 由子类实现
# ============================================================================

# 这些抽象方法在 _OpenAIBase 和 _AnthropicBase 中实现。
# 在这里只声明 stub 让 mypy 满意。如果某个方法没实现，运行时会 AttributeError。


# ============================================================================
# 后置定义：OpenAI / Anthropic 协议实现
# ============================================================================
# 这里延迟 import 避免循环依赖（protocol = openai / anthropic 在类体内读取）。


class _OpenAIBase(_AgentCommon, metaclass=_ProtocolMeta):
    """OpenAI 兼容 Chat Completions 协议。"""

    protocol: str = "openai"

    def _connectivity(self):
        """异步 ping：走 HTTPClient，不重试。"""
        from .errors import APIError
        from .http_utils import HTTPClient

        try:
            client = HTTPClient()
            payload = {
                "model": self.model_name,
                "messages": [{"role": "user", "content": "你好"}],
                "stream": self.stream,
                "stream_options": {"include_usage": True},
                "max_tokens": 1,
            }
            rsp = client.post(
                self.api_provider,
                headers=self.headers,
                json=payload,
                max_retries=0,
            )
            ok = 200 <= rsp.status_code < 300
        except APIError as e:
            logger.error(f"{self.name} 连接测试未通过：{e}")
            return False
        except Exception as e:
            logger.error(f"{self.name} 连接异常：{e}")
            return False
        if ok:
            logger.info(f"{self.name} 连接正常")
        else:
            logger.error(f"{self.name} 连接测试未通过：status={rsp.status_code}")
        return ok

    def _resolve_tool(self, name: str):
        """解析 tool 名字到实际 callable"""
        tool_func = None
        if tool_registry.check_permission(self.uuid, name):
            info = tool_registry.get_tool_info(name)
            if info is not None:
                tool_func = info["function"]
        if tool_func is None and hasattr(self, name):
            method = getattr(self, name)
            if callable(method):
                tool_func = method
        if tool_func is None:
            raise ValueError(f"tool not found: {name}")
        return tool_func

    def _collect_tools_schema(self) -> list:
        """收集 tools schema（OpenAI 格式）"""
        tools_schema = list(tool_registry.get_all_tools_schema(self.uuid))
        for s in tool_registry.collect_builtin_tools(self):
            tools_schema.append(s)
        try:
            from .skill import skill_registry
            tools_schema.extend(skill_registry.get_all_tool_schemas())
        except ImportError:
            pass
        return tools_schema if self.fc_model else []

    def _build_user_message(self, messages, images) -> dict:
        """构建 OpenAI user message（支持多模态）"""
        if not images:
            return {"role": "user", "content": messages}
        content_list = [{"type": "text", "text": messages}]
        for img in images:
            if isinstance(img, str) and img.startswith("http"):
                content_list.append({"type": "image_url", "image_url": {"url": img}})
            else:
                content_list.append({"type": "image_url", "image_url": {"url": f"data:image/png;base64,{img}"}})
        return {"role": "user", "content": content_list}

    def _extract_system_and_messages(self, work_history):
        """抽出 system 消息，剩余为对话"""
        if work_history and isinstance(work_history[0], dict) and work_history[0].get("role") == "system":
            return work_history[0].get("content") or "", list(work_history[1:])
        return "", list(work_history)

    def _handle_fc_mode(self, work_history, tool_calls_list, full_content):
        """OpenAI Function Calling 模式：执行工具 - 复用 BaseAgent 逻辑"""
        if not (self.fc_model and tool_calls_list):
            return None
        logger.debug(f"发现 Function Calling 工具调用: {tool_calls_list}")

        work_history.append({
            "role": "assistant",
            "content": None,
            "tool_calls": tool_calls_list,
        })

        tool_results = []
        for tool_call in tool_calls_list:
            tool_name = tool_call['function']['name']
            tool_id = tool_call['id']

            try:
                args = json.loads(tool_call['function']['arguments'])
                self.current_task_id = self._generate_task_id()
                self._execute_hooks('before', tool_name, args)
                logger.debug(f"调用工具 {tool_name}，参数: {args}")
                self.pack(tool_name=tool_name, tool_parameter=args)

                from .agent_tool import _validate_tool_args_for
                args = _validate_tool_args_for(self, tool_name, args)

                async_id = None
                result, async_id = self._tool_runner.submit(
                    tool_func=self._resolve_tool(tool_name),
                    tool_name=tool_name,
                    timeout=self.tool_timeout,
                    **args,
                )
                if async_id is not None:
                    result = f"[tool {tool_name} still running in background as task_id={async_id}]"
                self._execute_hooks('after', tool_name, args, result)
                self.pack(tool_result=result, tool_name=tool_name)
                tool_results.append({
                    "tool_call_id": tool_id, "name": tool_name, "content": result,
                })
            except Exception as e:
                error_msg = f"执行工具 {tool_name} 时出错: {str(e)}"
                logger.error(error_msg)
                if 'args' in locals():
                    self._execute_hooks('error', tool_name, args, error_msg)
                tool_results.append({
                    "tool_call_id": tool_id, "name": tool_name, "content": error_msg,
                })

        for result in tool_results:
            work_history.append({
                "role": "tool",
                "tool_call_id": result['tool_call_id'],
                "name": result['name'],
                "content": result['content'],
            })

        return self.conversation_with_tool(tool=True)

    def _handle_xml_mode(self, work_history, full_content):
        """OpenAI XML 模式：解析 <tool_name>...</tool_name> 块"""
        from bs4 import BeautifulSoup
        xml_pattern = re.compile(r'<(\w+)>.*?</\1>', flags=re.S)
        clean_pattern = re.compile(r'</?(out_text|thinking)>', flags=re.S)
        clean_content = clean_pattern.sub('', full_content)
        xml_blocks = [m.group(0) for m in xml_pattern.finditer(clean_content)]

        if not xml_blocks:
            if self.fc_model:
                return None
            return full_content

        tool_results = []
        tool_names = []
        for block in xml_blocks:
            logger.debug(f"发现工具块：{block[:50]}...")
            soup = BeautifulSoup(block, "xml")
            root = soup.find()
            if root is None:
                raise ValueError("空 XML")
            tool_name = root.name

            tool_func = None
            tool_source = None

            if tool_registry.check_permission(self.uuid, tool_name):
                tool_info = tool_registry.get_tool_info(tool_name)
                if tool_info is not None:
                    tool_func = tool_info['function']
                    tool_source = "工具注册器"

            if tool_func is None and hasattr(self, tool_name):
                method = getattr(self, tool_name)
                if callable(method):
                    tool_func = method
                    tool_source = "类方法"

            if tool_func is None:
                available_tools = self.get_all_available_tools()
                tool_error = f"工具错误：找不到工具 '{tool_name}'。"
                if available_tools:
                    tool_error += f" 你可以使用以下工具：{', '.join(available_tools)}"
                work_history.append({"role": "system", "content": tool_error})
                tool_results.append({"error": tool_error})
                logger.warning(f"工具 {tool_name} 未找到，可用工具: {available_tools}")
                continue

            logger.debug(f"从 {tool_source} 找到工具 {tool_name}")
            params = {}
            for child in root.children:
                if hasattr(child, "name") and child.name:
                    params[child.name] = child.text

            self.current_task_id = self._generate_task_id()
            self._execute_hooks('before', tool_name, params)
            self.pack(tool_name=tool_name, tool_parameter=params)

            import inspect

            from .agent_tool import _validate_tool_args_for
            try:
                params = _validate_tool_args_for(self, tool_name, params)
            except Exception as e:
                result = f"工具参数校验失败：{e}"
                tool_results.append(result)
                tool_names.append(tool_name)
                self._execute_hooks('error', tool_name, params, result)
                continue

            sig = inspect.signature(tool_func)
            param_count = len([p for p in sig.parameters.values()
                               if p.default == inspect.Parameter.empty
                               and p.kind not in (inspect.Parameter.VAR_POSITIONAL, inspect.Parameter.VAR_KEYWORD)])
            has_kwargs = any(p.kind == inspect.Parameter.VAR_KEYWORD for p in sig.parameters.values())
            if has_kwargs or param_count == 0:
                result = tool_func(**params) if params else tool_func()
            elif param_count == 1 and len(params) == 1:
                result = tool_func(list(params.values())[0])
            else:
                try:
                    result = tool_func(**params)
                except TypeError:
                    result = tool_func(block)

            self._execute_hooks('after', tool_name, params, result)
            self.pack(tool_result=result, tool_name=tool_name)

            if not result:
                result = f"no return for the tool{tool_name}"
            tool_results.append(result)
            tool_names.append(tool_name)

        if "<attempt_completion>" in full_content:
            self.pack("\n[系统] AI 已标记任务完成，程序退出。", tool_name="attempt_completion")

        if tool_results:
            n = 0
            for i in tool_results:
                try:
                    work_history.append({"role": "system", "content": f"{tool_names[n]} results: {i}"})
                    n += 1
                except Exception:
                    break
            return self.conversation_with_tool(tool=True)
        return full_content

    @_auto_save
    def conversation_with_tool(self, messages=None, tool: bool = False, images=None):
        """进行对话，支持多模态输入（文本 + 图片）"""
        work_history = self.history

        if not tool and messages:
            work_history.append(self._build_user_message(messages, images))

        tools_schema = self._collect_tools_schema()
        system_str, rest_messages = self._extract_system_and_messages(work_history)

        req = ChatRequest(
            model=self.model_name,
            system=system_str,
            messages=rest_messages,
            tools=tools_schema,
            stream=self.stream,
        )

        transport = HttpxOpenAITransport(
            endpoint=self.api_provider,
            api_key=self.api_key,
        )

        full_content = ""
        tool_calls_list: list = []
        self.stream_run = True

        if self.stream:
            for evt in transport.chat_stream(req):
                if evt.type == "text":
                    full_content += evt.text
                    self.pack(evt.text, finish_task=False)
                elif evt.type == "tool_call" and evt.tool_call is not None:
                    tc = evt.tool_call
                    tool_calls_list.append({
                        "id": tc.id, "type": "function",
                        "function": {
                            "name": tc.name,
                            "arguments": json.dumps(tc.arguments, ensure_ascii=False),
                        },
                    })
                elif evt.type == "usage" and evt.usage is not None:
                    self.stream_run = False
                    self.pack(finish_task=True)
                    self.pack(
                        f"\n本次请求用量：提示 {evt.usage.prompt_tokens} tokens，"
                        f"生成 {evt.usage.completion_tokens} tokens，"
                        f"总计 {evt.usage.total_tokens} tokens。",
                        other=True,
                    )
        else:
            self.stream_run = False
            try:
                llm_rsp: LLMResponse = transport.chat(req)
                full_content = llm_rsp.text
                if full_content:
                    self.pack(full_content, finish_task=False)
                for tc in llm_rsp.tool_calls:
                    tool_calls_list.append({
                        "id": tc.id, "type": "function",
                        "function": {
                            "name": tc.name,
                            "arguments": json.dumps(tc.arguments, ensure_ascii=False),
                        },
                    })
                if llm_rsp.usage is not None:
                    self.pack(finish_task=True)
                    self.pack(
                        f"\n本次请求用量：提示 {llm_rsp.usage.prompt_tokens} tokens，"
                        f"生成 {llm_rsp.usage.completion_tokens} tokens，"
                        f"总计 {llm_rsp.usage.total_tokens} tokens。",
                        other=True,
                    )
            except Exception as e:
                logger.error(f"非流式响应处理错误: {e}")
                full_content = ""

        logger.trace(f"AI 回复内容长度：{len(full_content)}")

        # FC 模式
        if self.fc_model and tool_calls_list:
            return self._handle_fc_mode(work_history, tool_calls_list, full_content)

        # XML 模式
        result = self._handle_xml_mode(work_history, full_content)
        if result is not None:
            return result
        return full_content

    @_auto_save_async
    async def aconversation_with_tool(self, messages=None, tool: bool = False, images=None):
        """异步版 conversation_with_tool"""
        work_history = self.history

        if not tool and messages:
            work_history.append(self._build_user_message(messages, images))

        tools_schema = self._collect_tools_schema()
        system_str, rest_messages = self._extract_system_and_messages(work_history)

        req = ChatRequest(
            model=self.model_name,
            system=system_str,
            messages=rest_messages,
            tools=tools_schema,
            stream=self.stream,
        )

        transport = HttpxOpenAITransport(endpoint=self.api_provider, api_key=self.api_key)
        full_content = ""
        tool_calls_list: list = []

        if self.stream:
            async for evt in transport.achat_stream(req):
                if evt.type == "text":
                    full_content += evt.text
                    self.pack(evt.text, finish_task=False)
                elif evt.type == "tool_call" and evt.tool_call is not None:
                    tc = evt.tool_call
                    tool_calls_list.append({
                        "id": tc.id, "type": "function",
                        "function": {
                            "name": tc.name,
                            "arguments": json.dumps(tc.arguments, ensure_ascii=False),
                        },
                    })
                elif evt.type == "usage" and evt.usage is not None:
                    self.stream_run = False
                    self.pack(finish_task=True)
                    self.pack(
                        f"usage: prompt={evt.usage.prompt_tokens} "
                        f"completion={evt.usage.completion_tokens} "
                        f"total={evt.usage.total_tokens}",
                        other=True,
                    )
        else:
            self.stream_run = False
            try:
                llm_rsp: LLMResponse = await transport.achat(req)
                full_content = llm_rsp.text
                if full_content:
                    self.pack(full_content, finish_task=False)
                for tc in llm_rsp.tool_calls:
                    tool_calls_list.append({
                        "id": tc.id, "type": "function",
                        "function": {
                            "name": tc.name,
                            "arguments": json.dumps(tc.arguments, ensure_ascii=False),
                        },
                    })
                if llm_rsp.usage is not None:
                    self.pack(finish_task=True)
                    self.pack(
                        f"usage: prompt={llm_rsp.usage.prompt_tokens} "
                        f"completion={llm_rsp.usage.completion_tokens} "
                        f"total={llm_rsp.usage.total_tokens}",
                        other=True,
                    )
            except Exception as e:
                logger.error(f"非流式响应处理错误: {e}")
                full_content = ""

        # FC 模式走相同逻辑（包一层 asyncio 友好）
        if self.fc_model and tool_calls_list:
            # 简化复用：调用 sync 版本（ToolRunner 不阻塞）
            return self._handle_fc_mode(work_history, tool_calls_list, full_content)
        return full_content


class _AnthropicBase(_AgentCommon, metaclass=_ProtocolMeta):
    """Anthropic Messages API 协议。"""

    protocol: str = "anthropic"
    anthropic_version: str = "2023-06-01"
    max_tokens: int = 4096

    def _endpoint(self) -> str:
        """根据 api_provider 拼出 messages endpoint URL"""
        base = (self.api_provider or "").strip().rstrip("/")
        if not base:
            raise ValueError(
                f"{self.__class__.__name__} 必须显式设置 api_provider 类属性"
            )
        if base.endswith("/v1/messages"):
            return base
        if base.endswith("/v1"):
            return base + "/messages"
        return base + "/v1/messages"

    def _connectivity(self):
        from .errors import APIError
        from .http_utils import HTTPClient

        try:
            client = HTTPClient()
            payload = {
                "model": self.model_name,
                "max_tokens": 1,
                "messages": [{"role": "user", "content": "ping"}],
            }
            rsp = client.post(
                self._endpoint(),
                headers=self.headers,
                json=payload,
                max_retries=0,
            )
            ok = 200 <= rsp.status_code < 300
        except APIError as e:
            logger.error(f"{self.name} Anthropic 连接测试未通过：{e}")
            return False
        except Exception as e:
            logger.error(f"{self.name} Anthropic 连接异常：{e}")
            return False
        if ok:
            logger.info(f"{self.name} Anthropic 连接正常")
        else:
            logger.error(f"{self.name} Anthropic 连接测试未通过：status={rsp.status_code}")
        return ok

    def _dispatch_tool(self, name: str, arguments: dict):
        """Pydantic 校验 + 工具分发 + ToolRunner 执行"""
        from .agent_tool import _validate_tool_args_for
        try:
            arguments = _validate_tool_args_for(self, name, arguments)
        except Exception as e:
            return (f"工具参数校验失败：{e}", None)

        builtin_names = {s["function"]["name"] for s in tool_registry.collect_builtin_tools(self)}
        if name in builtin_names:
            method = getattr(self, name, None)
            if callable(method):
                if arguments:
                    result, async_id = self._tool_runner.submit(
                        method, tool_name=name, timeout=self.tool_timeout, **arguments,
                    )
                else:
                    result, async_id = self._tool_runner.submit(
                        method, tool_name=name, timeout=self.tool_timeout,
                    )
                return result, async_id

        if tool_registry.check_permission(self.uuid, name):
            tool_info = tool_registry.get_tool_info(name)
            if tool_info:
                func = tool_info["function"]
                try:
                    if arguments:
                        result, async_id = self._tool_runner.submit(
                            func, tool_name=name, timeout=self.tool_timeout, **arguments,
                        )
                    else:
                        result, async_id = self._tool_runner.submit(
                            func, tool_name=name, timeout=self.tool_timeout,
                        )
                    return result, async_id
                except TypeError:
                    result, async_id = self._tool_runner.submit(
                        func, tool_name=name, timeout=self.tool_timeout, xml=str(arguments),
                    )
                    return result, async_id
        return (f"找不到工具：{name}", None)

    def _collect_tools_schema(self) -> list:
        """Anthropic 工具 schema（含 builtin）"""
        tools_schema = list(tool_registry.get_all_tools_schema(self.uuid))
        for s in tool_registry.collect_builtin_tools(self):
            tools_schema.append(s)
        try:
            from .skill import skill_registry
            tools_schema.extend(skill_registry.get_all_tool_schemas())
        except ImportError:
            pass
        # OpenAI → Anthropic 转换由 HttpxAnthropicTransport._convert_tools 内部处理
        return tools_schema if self.fc_model else []

    def _build_user_message(self, messages, images) -> dict:
        """构建 Anthropic user message（支持多模态）"""
        if not images:
            return {"role": "user", "content": messages}
        content_list = [{"type": "text", "text": messages}]
        for img in images:
            if isinstance(img, str) and img.startswith("http"):
                content_list.append({"type": "image", "source": {"type": "url", "url": img}})
            else:
                content_list.append({
                    "type": "image",
                    "source": {"type": "base64", "media_type": "image/png", "data": str(img)},
                })
        return {"role": "user", "content": content_list}

    def _extract_system_and_messages(self, work_history):
        if work_history and isinstance(work_history[0], dict) and work_history[0].get("role") == "system":
            return work_history[0].get("content") or "", list(work_history[1:])
        return "", list(work_history)

    @_auto_save
    def conversation_with_tool(self, messages=None, tool: bool = False, images=None):
        """Anthropic Messages API 对话"""
        work_history = self.history

        if not tool and messages:
            work_history.append(self._build_user_message(messages, images))

        tools_schema = self._collect_tools_schema()
        system_str, rest_messages = self._extract_system_and_messages(work_history)

        req = ChatRequest(
            model=self.model_name,
            system=system_str,
            messages=rest_messages,
            tools=tools_schema,
            stream=self.stream,
            max_tokens=self.max_tokens,
        )

        transport = HttpxAnthropicTransport(
            endpoint=self._endpoint(),
            api_key=self.api_key,
            anthropic_version=self.anthropic_version,
            max_tokens=self.max_tokens,
        )

        full_text = ""
        assistant_blocks: list = []
        tool_uses: list = []

        try:
            if self.stream:
                for evt in transport.chat_stream(req):
                    if evt.type == "text":
                        assistant_blocks.append({"type": "text", "text": evt.text})
                        self.pack(evt.text, finish_task=False)
                    elif evt.type == "tool_call" and evt.tool_call is not None:
                        tool_use_block = {
                            "type": "tool_use",
                            "id": evt.tool_call.id,
                            "name": evt.tool_call.name,
                            "input": evt.tool_call.arguments,
                        }
                        assistant_blocks.append(tool_use_block)
                        tool_uses.append({
                            "id": evt.tool_call.id,
                            "name": evt.tool_call.name,
                            "input": evt.tool_call.arguments,
                        })
            else:
                llm_rsp: LLMResponse = transport.chat(req)
                for tc in llm_rsp.tool_calls:
                    assistant_blocks.append({
                        "type": "tool_use",
                        "id": tc.id, "name": tc.name, "input": tc.arguments,
                    })
                    tool_uses.append({
                        "id": tc.id, "name": tc.name, "input": tc.arguments,
                    })
                if llm_rsp.text:
                    full_text += llm_rsp.text
                    assistant_blocks.append({"type": "text", "text": llm_rsp.text})
                    self.pack(llm_rsp.text, finish_task=False)
        except Exception as e:
            logger.error(f"{self.name} Anthropic 调用失败：{e}")
            raise

        if self.stream and not any(b.get("type") == "text" for b in assistant_blocks) and full_text:
            assistant_blocks.append({"type": "text", "text": full_text})

        work_history.append({"role": "assistant", "content": assistant_blocks})
        if not tool_uses:
            return "".join(b.get("text", "") for b in assistant_blocks if b.get("type") == "text")

        tool_results: list = []
        for tu in tool_uses:
            self.current_task_id = self._generate_task_id()
            self._execute_hooks("before", tu["name"], tu["input"])
            self.pack(tool_model=True, tool_name=tu["name"], tool_parameter=tu["input"])
            async_id = None
            try:
                result, async_id = self._dispatch_tool(tu["name"], tu["input"])
            except Exception as e:
                result = f"工具执行失败：{e}"
                self._execute_hooks("error", tu["name"], tu["input"], result)
            else:
                self._execute_hooks("after", tu["name"], tu["input"], result)
                self.pack(tool_result=result, tool_name=tu["name"])

            if async_id is not None:
                result = (
                    f"[tool {tu['name']} still running in background as task_id={async_id}; "
                    f"check via self._tool_runner.get_status('{async_id}') "
                    f"or wait via self._tool_runner.wait('{async_id}')]"
                )

            tool_results.append({
                "type": "tool_result",
                "tool_use_id": tu["id"],
                "content": result if isinstance(result, str) else json.dumps(result, ensure_ascii=False),
            })

        work_history.append({"role": "user", "content": tool_results})
        return self.conversation_with_tool(tool=True)

    @_auto_save_async
    async def aconversation_with_tool(self, messages=None, tool: bool = False, images=None):
        work_history = self.history

        if not tool and messages:
            work_history.append(self._build_user_message(messages, images))

        tools_schema = self._collect_tools_schema()
        system_str, rest_messages = self._extract_system_and_messages(work_history)

        req = ChatRequest(
            model=self.model_name,
            system=system_str,
            messages=rest_messages,
            tools=tools_schema,
            stream=self.stream,
            max_tokens=self.max_tokens,
        )

        transport = HttpxAnthropicTransport(
            endpoint=self._endpoint(),
            api_key=self.api_key,
            anthropic_version=self.anthropic_version,
            max_tokens=self.max_tokens,
        )

        full_text = ""
        assistant_blocks: list = []
        tool_uses: list = []

        try:
            if self.stream:
                async for evt in transport.achat_stream(req):
                    if evt.type == "text":
                        assistant_blocks.append({"type": "text", "text": evt.text})
                        self.pack(evt.text, finish_task=False)
                    elif evt.type == "tool_call" and evt.tool_call is not None:
                        tool_use_block = {
                            "type": "tool_use",
                            "id": evt.tool_call.id,
                            "name": evt.tool_call.name,
                            "input": evt.tool_call.arguments,
                        }
                        assistant_blocks.append(tool_use_block)
                        tool_uses.append({
                            "id": evt.tool_call.id,
                            "name": evt.tool_call.name,
                            "input": evt.tool_call.arguments,
                        })
            else:
                llm_rsp: LLMResponse = await transport.achat(req)
                for tc in llm_rsp.tool_calls:
                    assistant_blocks.append({
                        "type": "tool_use",
                        "id": tc.id, "name": tc.name, "input": tc.arguments,
                    })
                    tool_uses.append({
                        "id": tc.id, "name": tc.name, "input": tc.arguments,
                    })
                if llm_rsp.text:
                    full_text += llm_rsp.text
                    assistant_blocks.append({"type": "text", "text": llm_rsp.text})
                    self.pack(llm_rsp.text, finish_task=False)
        except Exception as e:
            logger.error(f"{self.name} Anthropic 异步调用失败：{e}")
            raise

        work_history.append({"role": "assistant", "content": assistant_blocks})
        if not tool_uses:
            return "".join(b.get("text", "") for b in assistant_blocks if b.get("type") == "text")

        tool_results: list = []
        for tu in tool_uses:
            self.current_task_id = self._generate_task_id()
            self._execute_hooks("before", tu["name"], tu["input"])
            self.pack(tool_model=True, tool_name=tu["name"], tool_parameter=tu["input"])
            async_id = None
            try:
                result, async_id = self._dispatch_tool(tu["name"], tu["input"])
            except Exception as e:
                result = f"tools execution failed: {e}"
                self._execute_hooks("error", tu["name"], tu["input"], result)
            else:
                self._execute_hooks("after", tu["name"], tu["input"], result)
                self.pack(tool_result=result, tool_name=tu["name"])

            if async_id is not None:
                result = f"[tool {tu['name']} still running in background as task_id={async_id}]"

            tool_results.append({
                "type": "tool_result",
                "tool_use_id": tu["id"],
                "content": result if isinstance(result, str) else json.dumps(result, ensure_ascii=False),
            })

        work_history.append({"role": "user", "content": tool_results})
        return await self.aconversation_with_tool(tool=True)


# ============================================================================
# Agent 占位类 + 小写别名
# ============================================================================
#
# 写两遍 ``class Agent`` 的原因：
# 1. 第一次：作为 metaclass 分发的"占位类"（protocol 字段会被换）
# 2. metaclass 之后 ``_OpenAIBase`` / ``_AnthropicBase`` 已经定义，可以做
#    ``isinstance / issubclass`` 比较
# 3. 第二次：最终版 Agent 类（绑定到上面的两个真实基类）
#
# 简化版：只写一次 final Agent（在文件顶部，metaclass 之后），metaclass 在子类化时查找
# _PROTOCOL_BASES。这里不再重复定义。


# ============================================================================
# 向后兼容别名
# ============================================================================

BaseAgent = _OpenAIBase
AnthropicAgent = _AnthropicBase


# ============================================================================
# 注册默认协议
# ============================================================================

register_protocol("openai", _OpenAIBase)
register_protocol("anthropic", _AnthropicBase)


# OpenAI Responses API（v0.4.2+）—— 复用 _AgentCommon 共享方法，
# 协议特定：conversational flow 用 HttpxOpenAIResponsesTransport
class _OpenAIResponsesBase(_AgentCommon, metaclass=_ProtocolMeta):
    """OpenAI Responses API 兼容（v0.4.2+）。

    用法：``protocol = "openai-responses"``，框架用 ``HttpxOpenAIResponsesTransport``
    调 ``/v1/responses`` endpoint。响应格式（output[] 含 message / function_call）
    框架内部已转成中性的 LLMResponse / LLMEvent。
    """

    protocol: str = "openai-responses"

    def _build_user_message(self, messages, images):
        # Responses API 的 content 可以是 string 或 array（多模态直接展开）
        if not images:
            return {"role": "user", "content": messages}
        content_list = [{"type": "text", "text": messages}]
        for img in images:
            if isinstance(img, str) and img.startswith("http"):
                content_list.append({"type": "image_url", "image_url": {"url": img}})
            else:
                content_list.append({"type": "image_url", "image_url": {"url": f"data:image/png;base64,{img}"}})
        return {"role": "user", "content": content_list}

    def _extract_system_and_messages(self, work_history):
        """Responses API 用 ``instructions``（顶字段）替代 system 消息。"""
        if work_history and isinstance(work_history[0], dict) and work_history[0].get("role") == "system":
            return work_history[0].get("content") or "", list(work_history[1:])
        return "", list(work_history)

    def _collect_tools_schema(self):
        return list(tool_registry.get_all_tools_schema(self.uuid)) + [
            s for s in tool_registry.collect_builtin_tools(self)
        ]

    def _resolve_tool(self, name: str):
        tool_func = None
        if tool_registry.check_permission(self.uuid, name):
            info = tool_registry.get_tool_info(name)
            if info is not None:
                tool_func = info["function"]
        if tool_func is None and hasattr(self, name):
            method = getattr(self, name)
            if callable(method):
                tool_func = method
        if tool_func is None:
            raise ValueError(f"tool not found: {name}")
        return tool_func

    @_auto_save
    def conversation_with_tool(self, messages=None, tool: bool = False, images=None):
        work_history = self.history

        if not tool and messages:
            work_history.append(self._build_user_message(messages, images))

        tools_schema = self._collect_tools_schema() if self.fc_model else []
        system_str, rest_messages = self._extract_system_and_messages(work_history)

        req = ChatRequest(
            model=self.model_name,
            system=system_str,
            messages=rest_messages,
            tools=tools_schema,
            stream=self.stream,
        )

        transport = HttpxOpenAIResponsesTransport(
            endpoint=self.api_provider, api_key=self.api_key,
        )

        full_content = ""
        tool_calls_list: list = []
        self.stream_run = True

        if self.stream:
            for evt in transport.chat_stream(req):
                if evt.type == "text":
                    full_content += evt.text
                    self.pack(evt.text, finish_task=False)
                elif evt.type == "tool_call" and evt.tool_call is not None:
                    tc = evt.tool_call
                    tool_calls_list.append({
                        "id": tc.id, "type": "function",
                        "function": {
                            "name": tc.name,
                            "arguments": json.dumps(tc.arguments, ensure_ascii=False),
                        },
                    })
                elif evt.type == "usage" and evt.usage is not None:
                    self.stream_run = False
                    self.pack(finish_task=True)
                    self.pack(
                        f"\n本次请求用量：提示 {evt.usage.prompt_tokens} tokens，"
                        f"生成 {evt.usage.completion_tokens} tokens，"
                        f"总计 {evt.usage.total_tokens} tokens。",
                        other=True,
                    )
        else:
            self.stream_run = False
            try:
                llm_rsp: LLMResponse = transport.chat(req)
                full_content = llm_rsp.text
                if full_content:
                    self.pack(full_content, finish_task=False)
                for tc in llm_rsp.tool_calls:
                    tool_calls_list.append({
                        "id": tc.id, "type": "function",
                        "function": {
                            "name": tc.name,
                            "arguments": json.dumps(tc.arguments, ensure_ascii=False),
                        },
                    })
                if llm_rsp.usage is not None:
                    self.pack(finish_task=True)
                    self.pack(
                        f"\n本次请求用量：提示 {llm_rsp.usage.prompt_tokens} tokens，"
                        f"生成 {llm_rsp.usage.completion_tokens} tokens，"
                        f"总计 {llm_rsp.usage.total_tokens} tokens。",
                        other=True,
                    )
            except Exception as e:
                logger.error(f"非流式响应处理错误: {e}")
                full_content = ""

        if self.fc_model and tool_calls_list:
            work_history.append({
                "role": "assistant",
                "content": None,
                "tool_calls": tool_calls_list,
            })
            tool_results = []
            for tool_call in tool_calls_list:
                tool_name = tool_call["function"]["name"]
                tool_id = tool_call["id"]
                try:
                    args = json.loads(tool_call["function"]["arguments"])
                    self.current_task_id = self._generate_task_id()
                    self._execute_hooks("before", tool_name, args)
                    logger.debug(f"调用工具 {tool_name}，参数: {args}")
                    self.pack(tool_name=tool_name, tool_parameter=args)
                    from .agent_tool import _validate_tool_args_for
                    args = _validate_tool_args_for(self, tool_name, args)
                    async_id = None
                    result, async_id = self._tool_runner.submit(
                        tool_func=self._resolve_tool(tool_name),
                        tool_name=tool_name,
                        timeout=self.tool_timeout,
                        **args,
                    )
                    if async_id is not None:
                        result = f"[tool {tool_name} still running in background as task_id={async_id}]"
                    self._execute_hooks("after", tool_name, args, result)
                    self.pack(tool_result=result, tool_name=tool_name)
                    tool_results.append({
                        "tool_call_id": tool_id, "name": tool_name, "content": result,
                    })
                except Exception as e:
                    error_msg = f"执行工具 {tool_name} 时出错: {str(e)}"
                    logger.error(error_msg)
                    if 'args' in locals():
                        self._execute_hooks("error", tool_name, args, error_msg)
                    tool_results.append({
                        "tool_call_id": tool_id, "name": tool_name, "content": error_msg,
                    })
            for result in tool_results:
                work_history.append({
                    "role": "tool",
                    "tool_call_id": result["tool_call_id"],
                    "name": result["name"],
                    "content": result["content"],
                })
            return self.conversation_with_tool(tool=True)
        return full_content

    @_auto_save_async
    async def aconversation_with_tool(self, messages=None, tool: bool = False, images=None):
        work_history = self.history
        if not tool and messages:
            work_history.append(self._build_user_message(messages, images))

        tools_schema = self._collect_tools_schema() if self.fc_model else []
        system_str, rest_messages = self._extract_system_and_messages(work_history)

        req = ChatRequest(
            model=self.model_name,
            system=system_str,
            messages=rest_messages,
            tools=tools_schema,
            stream=self.stream,
        )

        transport = HttpxOpenAIResponsesTransport(
            endpoint=self.api_provider, api_key=self.api_key,
        )
        full_content = ""
        tool_calls_list: list = []

        if self.stream:
            async for evt in transport.achat_stream(req):
                if evt.type == "text":
                    full_content += evt.text
                    self.pack(evt.text, finish_task=False)
                elif evt.type == "tool_call" and evt.tool_call is not None:
                    tc = evt.tool_call
                    tool_calls_list.append({
                        "id": tc.id, "type": "function",
                        "function": {
                            "name": tc.name,
                            "arguments": json.dumps(tc.arguments, ensure_ascii=False),
                        },
                    })
                elif evt.type == "usage" and evt.usage is not None:
                    self.stream_run = False
                    self.pack(finish_task=True)
                    self.pack(
                        f"usage: prompt={evt.usage.prompt_tokens} "
                        f"completion={evt.usage.completion_tokens} "
                        f"total={evt.usage.total_tokens}",
                        other=True,
                    )
        else:
            self.stream_run = False
            try:
                llm_rsp: LLMResponse = await transport.achat(req)
                full_content = llm_rsp.text
                if full_content:
                    self.pack(full_content, finish_task=False)
                for tc in llm_rsp.tool_calls:
                    tool_calls_list.append({
                        "id": tc.id, "type": "function",
                        "function": {
                            "name": tc.name,
                            "arguments": json.dumps(tc.arguments, ensure_ascii=False),
                        },
                    })
                if llm_rsp.usage is not None:
                    self.pack(finish_task=True)
                    self.pack(
                        f"usage: prompt={llm_rsp.usage.prompt_tokens} "
                        f"completion={llm_rsp.usage.completion_tokens} "
                        f"total={llm_rsp.usage.total_tokens}",
                        other=True,
                    )
            except Exception as e:
                logger.error(f"非流式响应处理错误: {e}")
                full_content = ""

        if self.fc_model and tool_calls_list:
            work_history.append({
                "role": "assistant",
                "content": None,
                "tool_calls": tool_calls_list,
            })
            tool_results = []
            for tool_call in tool_calls_list:
                tool_name = tool_call["function"]["name"]
                tool_id = tool_call["id"]
                try:
                    args = json.loads(tool_call["function"]["arguments"])
                    from .agent_tool import _validate_tool_args_for
                    args = _validate_tool_args_for(self, tool_name, args)
                    self.current_task_id = self._generate_task_id()
                    self._execute_hooks("before", tool_name, args)
                    self.pack(tool_name=tool_name, tool_parameter=args)
                    async_id = None
                    result, async_id = self._tool_runner.submit(
                        tool_func=self._resolve_tool(tool_name),
                        tool_name=tool_name,
                        timeout=self.tool_timeout,
                        **args,
                    )
                    if async_id is not None:
                        result = f"[tool {tool_name} still running in background as task_id={async_id}]"
                    self._execute_hooks("after", tool_name, args, result)
                    self.pack(tool_result=result, tool_name=tool_name)
                    tool_results.append({
                        "tool_call_id": tool_id, "name": tool_name, "content": result,
                    })
                except Exception as e:
                    error_msg = f"tools execution failed: {e}"
                    logger.error(error_msg)
                    self._execute_hooks("error", tool_name, args, error_msg)
                    tool_results.append({
                        "tool_call_id": tool_id, "name": tool_name, "content": error_msg,
                    })
            for result in tool_results:
                work_history.append({
                    "role": "tool",
                    "tool_call_id": result["tool_call_id"],
                    "name": result["name"],
                    "content": result["content"],
                })
            return await self.aconversation_with_tool(tool=True)
        return full_content


register_protocol("openai-responses", _OpenAIResponsesBase)
