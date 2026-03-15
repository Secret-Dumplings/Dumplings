# -*- coding: utf-8 -*-
"""
tool.py  –  带超详细日志的工具注册器
用法：
    export LOGURU_LEVEL=TRACE
    python your_main.py
"""
from .logging_config import logger
import os, inspect, sys

# 日志配置已由 logging_config 模块统一管理

# 2. 工具注册器 --------------------------------------------------------
from functools import wraps
from typing import List, Union, Optional


class tool:
    """工具注册管理器（超详细日志版）"""
    def __init__(self):
        self._tools: dict = {}              # name -> info
        self._agent_permissions: dict = {}  # 预留
        self._uuid_to_name: dict = {}       # uuid -> name
        logger.trace("tool.__init__ -> empty registries created")

    # --------------------  uuid 映射 --------------------
    def register_agent_uuid(self, uuid: str, name: str):
        logger.trace(f"register_agent_uuid(uuid={uuid!r}, name={name!r}) enter")
        self._uuid_to_name[uuid] = name
        logger.debug(f"uuid映射已注册: {uuid} -> {name}")

    # --------------------  工具注册 --------------------
    def register_tool(
        self,
        allowed_agents: Union[str, List[str]] = None,
        description: str = "",
        name: Optional[str] = None,
        parameters: Optional[dict] = None,
    ):
        """
        工具注册装饰器（带日志）
        parameters: OpenAI function calling schema
        """
        frame = inspect.currentframe().f_back
        caller = f"{frame.f_code.co_filename}:{frame.f_lineno}"
        logger.trace(f"register_tool() called from {caller}")
        logger.trace(
            f"params -> allowed_agents={allowed_agents!r}, "
            f"description={description!r}, name={name!r}, parameters={parameters!r}"
        )

        def decorator(func):
            tool_name = name or func.__name__
            logger.trace(f"decorator applied on function {func.__name__!r}, tool_name={tool_name!r}")

            # 处理 allowed_agents
            if allowed_agents is None:
                permitted = None
                logger.trace("permitted_agents -> None (unlimited)")
            elif isinstance(allowed_agents, str):
                permitted = [allowed_agents]
                logger.trace(f"permitted_agents -> single str: {permitted}")
            else:
                permitted = list(allowed_agents)
                logger.trace(f"permitted_agents -> list: {permitted}")

            # 构建 OpenAI tools schema
            tool_schema = {
                "type": "function",
                "function": {
                    "name": tool_name,
                    "description": description,
                    "parameters": parameters or {
                        "type": "object",
                        "properties": {},
                        "required": []
                    }
                }
            }

            # 真正注册
            self._tools[tool_name] = {
                "function": func,
                "allowed_agents": permitted,
                "description": description,
                "name": tool_name,
                "parameters": parameters,
                "schema": tool_schema
            }
            logger.debug(
                f"工具注册成功: {tool_name!r} -> {self._tools[tool_name]}"
            )

            @wraps(func)
            def wrapper(*args, **kwargs):
                logger.trace(
                    f"工具被调用: {tool_name!r} with args={args}, kwargs={kwargs}"
                )
                return func(*args, **kwargs)

            logger.trace(f"decorator返回wrapper，注册流程结束: {tool_name!r}")
            return wrapper

        return decorator

    # --------------------  权限检查 --------------------
    def check_permission(self, agent_name: str, tool_name: str) -> bool:
        logger.trace(
            f"check_permission(agent_name={agent_name!r}, tool_name={tool_name!r})"
        )
        if tool_name not in self._tools:
            logger.warning(f"工具 {tool_name!r} 未注册，拒接访问")
            return False

        # uuid -> name
        original_agent = agent_name
        if agent_name in self._uuid_to_name:
            agent_name = self._uuid_to_name[agent_name]
            logger.debug(f"uuid转换: {original_agent!r} -> {agent_name!r}")

        tool_info = self._tools[tool_name]
        allowed = tool_info["allowed_agents"]
        logger.trace(f"工具 {tool_name!r} 的 allowed_agents = {allowed!r}")

        if allowed is None:
            logger.trace("allowed_agents 为 None，放行")
            return True

        ok = agent_name in allowed
        logger.debug(
            f"权限检查结果: agent={agent_name!r} "
            f"{'✔' if ok else '✘'} 工具 {tool_name!r}"
        )
        return ok

    # --------------------  查询接口 --------------------
    def get_tool_info(self, tool_name: str) -> Optional[dict]:
        logger.trace(f"get_tool_info({tool_name!r})")
        return self._tools.get(tool_name)

    def get_tool_schema(self, tool_name: str) -> Optional[dict]:
        """返回单个工具的 OpenAI schema"""
        logger.trace(f"get_tool_schema({tool_name!r})")
        tool_info = self._tools.get(tool_name)
        return tool_info.get("schema") if tool_info else None

    def get_all_tools_schema(self, agent_uuid: str) -> list:
        """返回该 agent 有权限使用的所有工具的 schema"""
        logger.trace(f"get_all_tools_schema(agent_uuid={agent_uuid!r})")
        tools_schema = []
        for tool_name, tool_info in self._tools.items():
            if self.check_permission(agent_uuid, tool_name):
                tools_schema.append(tool_info.get("schema"))
        logger.debug(f"Agent {agent_uuid} 有权限的工具数: {len(tools_schema)}")
        return tools_schema

    def get_all_tools_info(self, agent_uuid: str) -> dict:
        """返回该 agent 有权限的所有工具信息（名称和描述）"""
        logger.trace(f"get_all_tools_info(agent_uuid={agent_uuid!r})")
        tools_info = {}
        for tool_name, tool_info in self._tools.items():
            if self.check_permission(agent_uuid, tool_name):
                tools_info[tool_name] = {
                    "description": tool_info["description"],
                    "parameters": tool_info.get("parameters", {})
                }
        logger.debug(f"Agent {agent_uuid} 有权限的工具: {list(tools_info.keys())}")
        return tools_info

    def list_tools(self) -> dict:
        logger.trace("list_tools() called")
        snapshot = {
            name: {
                "description": info["description"],
                "allowed_agents": info["allowed_agents"],
            }
            for name, info in self._tools.items()
        }
        logger.trace(f"当前注册工具: {list(snapshot.keys())}")
        return snapshot


# 3. 全局实例 ----------------------------------------------------------
tool_registry = tool()
logger.trace("tool_registry 全局实例已创建")