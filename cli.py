# -*- coding: utf-8 -*-
"""
tangyuanai 命令行入口（Python 模块名 tangyuanAI）
==================================================

::

    tangyuanai --help        全部子命令
    tangyuanai --doctor      环境自检（Python / httpx / pydantic / API Key / 插件）
    tangyuanai --demo        跑一个最小离线示例（不连真 LLM）

也可以通过 ``python -m tangyuanAI`` 进入。

插件化（v1.1.0+）
-----------------
- ``tangyuanai plugin install <name>`` 从中央 config 仓库下载并启用插件
- ``kb`` / ``image-gen`` 子命令由已安装的插件包提供：
  - RAG 插件（``tangyuanai-rag-plus``）→ ``kb`` 子命令
  - 图片插件（``tangyuanai-image-plus``）→ ``image-gen`` 子命令
  - 未安装时子命令不可用（``--doctor`` 会提示安装方式）
"""
from __future__ import annotations

import argparse
import importlib
import os
import sys
from typing import List, Optional

from ._banner import print_banner
from ._banner import silence as silence_banner

__all__ = ["main", "cmd_doctor", "cmd_demo", "cmd_help"]


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="tangyuanai",
        description=(
            "tangyuanAI 命令行入口（CLI 命令 = tangyuanai）。\n"
            "主要用途：环境自检 + 离线 demo + Agent/工具/插件管理。\n"
            "通过 `pip install tangyuanAI` 安装后可执行 `tangyuanai --help`。"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument(
        "--doctor", action="store_true",
        help="环境自检：Python 版本 / 关键依赖 / API Key / Agent 注册 / 插件",
    )
    p.add_argument(
        "--demo", action="store_true",
        help="跑一个最小离线 demo（不连真实 LLM）",
    )
    p.add_argument(
        "--quiet", "-q", action="store_true",
        help="不打启动 banner",
    )
    p.add_argument(
        "--version", action="store_true",
        help="打印版本号并退出",
    )

    subparsers = p.add_subparsers(dest="cmd", help="子命令")

    # 核心：plugin 管理（不依赖任何插件包）
    _add_plugin_subparsers(subparsers)

    # 旧版兼容：若核心仍捆绑 kb 子包（升级前残留），尝试挂载
    try:
        from .kb.cli import add_subparser
        add_subparser(subparsers)
    except ImportError:
        pass

    # 插件子命令：已安装的插件包注册 kb / image-gen 等
    _add_plugin_command_subparsers(subparsers)

    return p


def _add_plugin_subparsers(subparsers) -> None:
    """plugin 管理子命令（核心自带，不依赖插件包）。"""
    plug_p = subparsers.add_parser("plugin", help="plugin 管理（install / list / status）")
    plug_sub = plug_p.add_subparsers(dest="plugin_action", required=True)

    pi = plug_sub.add_parser("install", help="从中央仓库下载并启用 plugin config")
    pi.add_argument("name", help="plugin 名（中央仓库 <name>.json）")
    pi.add_argument("--config", help="tangyuanai.config.json 路径")
    pi.add_argument("--no-enable", action="store_true", help="只装不启用")
    pi.add_argument("--owner", default="secret-tangyuan", help="中央仓库 owner")
    pi.add_argument("--repo", default=None, help="中央仓库 repo（默认按插件名自动匹配）")
    pi.add_argument("--branch", default="main", help="中央仓库 branch")
    pi.set_defaults(func=cmd_plugin_install)

    pl = plug_sub.add_parser("list", help="列出本地 config 已启用的 plugin")
    pl.add_argument("--config", help="tangyuanai.config.json 路径")
    pl.set_defaults(func=cmd_plugin_list)

    ps = plug_sub.add_parser("status", help="已安装插件包 + 中央仓库插件状态")
    ps.set_defaults(func=cmd_plugin_status)


def _add_plugin_command_subparsers(subparsers) -> None:
    """已安装插件包的 add_cli_subparsers()（kb / image-gen 等）。"""
    from .plugin_loader import PluginError, discover_plugins

    for name in sorted(discover_plugins()):
        try:
            from .plugin_loader import load_plugin
            mod = load_plugin(name)
        except PluginError:
            continue
        add = getattr(mod, "add_cli_subparsers", None)
        if callable(add):
            try:
                add(subparsers)
            except Exception:
                continue


# ---------------------------------------------------------------------------
# plugin 命令
# ---------------------------------------------------------------------------


def cmd_plugin_install(args) -> int:
    """tangyuanai plugin install <name> → 下载 config 合并到本地，并提示代码包安装。"""
    import asyncio

    from .plugin_store import install_plugin

    repo = args.repo
    try:
        feat = asyncio.run(install_plugin(
            plugin_name=args.name,
            config_path=args.config,
            enable=not args.no_enable,
            owner=args.owner,
            repo=repo,
            branch=args.branch,
        ))
    except Exception as e:
        print(f"plugin 安装失败: {e}")
        return 1
    print(f"plugin config 已安装并{'启用' if not args.no_enable else '未启用'}: {args.name}")
    _print_code_install_hint(feat)
    return 0


def cmd_plugin_list(args) -> int:
    """tangyuanai plugin list → 列出本地 config 已启用 features。"""
    from .plugin_store import list_installed

    feats = list_installed(args.config)
    if not feats:
        print("(没有已启用的 plugin)")
        return 0
    for f in feats:
        print(f"  enabled: {f.get('name')!r}  type={f.get('type')!r}")
    return 0


def cmd_plugin_status(_args) -> int:
    """tangyuanai plugin status → 已安装插件包 + 可用性自检。"""
    from .plugin_loader import discover_plugins

    entries = discover_plugins()
    if not entries:
        print("未安装任何插件包。")
        print("安装全部插件：pip install 'tangyuanAI[all]'")
        return 0
    for name in sorted(entries):
        try:
            from .plugin_loader import load_plugin
            mod = load_plugin(name)
            ok = True
            info = ""
            check = getattr(mod, "check", None)
            if callable(check):
                try:
                    ok, info = check()
                except Exception as e:
                    ok, info = False, str(e)
        except Exception as e:
            ok, info = False, str(e)
        title = getattr(mod, "PLUGIN_TITLE", name) if "mod" in dir() else name
        print(f"  {'✓' if ok else '✗'} {name}  ({title}){(' — ' + info) if info else ''}")
    return 0


def _print_code_install_hint(feat: dict) -> None:
    """config 装完后，提示代码包（Python 实现）怎么装。"""
    cfg = feat.get("config", {}) or {}
    package = cfg.get("package") or cfg.get("pip_package")
    if not package:
        return
    print(f"  代码包: {package}")
    print(f"    单独安装：pip install {package}")
    print("    或安装全部插件：pip install 'tangyuanAI[all]'")


# ---------------------------------------------------------------------------
# doctor / demo
# ---------------------------------------------------------------------------


def _check_python_version() -> tuple[bool, str]:
    v = sys.version_info
    ok = (v >= (3, 10))
    return ok, f"{v.major}.{v.minor}.{v.micro}" + ("" if ok else "（< 3.10 不受支持）")


def _check_module(name: str) -> tuple[bool, str]:
    try:
        mod = importlib.import_module(name)
        ver = getattr(mod, "__version__", "(no __version__)")
        return True, ver
    except ImportError as e:
        return False, f"ImportError: {e}"


def _check_api_keys() -> list[tuple[str, bool, str]]:
    """检查常见 LLM provider 的 API Key 环境变量"""
    keys = [
        ("API_KEY", "OpenAI 兼容 / 自家网关通用"),
        ("OPENAI_API_KEY", "OpenAI 官方"),
        ("ANTHROPIC_API_KEY", "Anthropic 官方"),
        ("DASHSCOPE_API_KEY", "阿里云 DashScope"),
    ]
    out: list[tuple[str, bool, str]] = []
    for env, who in keys:
        val = os.environ.get(env)
        out.append((env, bool(val), who + (" — " + (val[:8] + "..." if val else "未设置"))))
    return out


def _check_agents() -> tuple[bool, list[str]]:
    try:
        from tangyuanAI import agent_list
        names = sorted({a.name for a in agent_list.values() if hasattr(a, "name")})
        return True, names
    except Exception as e:
        return False, [f"import agent_list 失败：{e}"]


def _check_plugins() -> list[tuple[str, str, bool]]:
    """返回 [(entry_point_name, title_or_module, ok)]。"""
    from .plugin_loader import discover_plugins

    entries = discover_plugins()
    out: list[tuple[str, str, bool]] = []
    for name in sorted(entries):
        try:
            from .plugin_loader import load_plugin
            mod = load_plugin(name)
            title = getattr(mod, "PLUGIN_TITLE", "")
            out.append((name, title or "", True))
        except Exception as e:
            out.append((name, str(e), False))
    return out


def cmd_doctor(_args: argparse.Namespace) -> int:
    """环境自检"""
    print("tangyuanAI Doctor\n" + "=" * 50)

    # Python 版本
    ok_py, py = _check_python_version()
    print(f"  {'✓' if ok_py else '✗'} Python {py}")

    # 关键依赖
    for name in ("httpx", "pydantic", "tiktoken", "loguru", "mcp"):
        ok, info = _check_module(name)
        print(f"  {'✓' if ok else '✗'} {name} {info}")

    # API Key
    print("  ─ API Key 环境变量")
    for env, ok, label in _check_api_keys():
        marker = "✓" if ok else "✗"
        print(f"    {marker} {env:18s}  {label}")

    # Agent 注册
    ok_ag, names = _check_agents()
    if ok_ag:
        if names:
            print(f"  ✓ 已注册 Agent: {', '.join(names)}")
        else:
            print("  ─ (尚未注册任何 Agent)")
    else:
        print(f"  ✗ {names[0]}")

    # 插件
    print("  ─ 插件（Plugin）")
    plugs = _check_plugins()
    if not plugs:
        print("    ─ 未安装插件包（pip install 'tangyuanAI[all]' 安装 kb + image）")
    else:
        for name, title, ok in plugs:
            print(f"    {'✓' if ok else '✗'} {name}  {title}")

    print()
    if not ok_py:
        print("⚠ Python 版本过低，请升级到 3.10+")
    print("下一步：tangyuanai --demo 跑一个最简示例")
    return 0


def cmd_demo(_args: argparse.Namespace) -> int:
    """离线 demo：不连 LLM，直接看框架结构"""
    print("tangyuanAI 离线 Demo\n" + "=" * 50)
    print("本 demo 不连真实 LLM，仅展示框架对象。\n")

    from tangyuanAI import (
        Agent,
        agent_list,
        builtin_tool,
        template_agent,
    )
    from tangyuanAI.Agent_list import activate_template
    from tangyuanAI.agent_tool import tool_registry
    from tangyuanAI.errors import classify

    print("  ✓ Agent / builtin_tool / tool_registry / template_agent import OK")
    print(f"  ✓ classify(429, 'rate') → {classify(429, 'rate limited').__class__.__name__}")

    # 临时构造一个 Agent（离线 demo，不连真实 LLM）
    @template_agent("demo_agent", uuid="demo-uuid", description="demo 用 Agent")
    class DemoAgent(Agent):
        prompt = "demo"
        api_provider = "https://example.com"
        model_name = "demo-model"
        api_key = "demo-key"
        enable_connectivity = False  # 离线 demo 不发起连通性测试

        @builtin_tool(description="hello world")
        def hello(self, name: str) -> str:
            return f"hello, {name}!"

    activate_template("demo_agent")
    ag = agent_list["demo_agent"]
    schemas = tool_registry.collect_builtin_tools(ag)
    print(f"  ✓ DemoAgent 已注册，发现 {len(schemas)} 个内建工具")
    for s in schemas:
        print(f"      - {s['function']['name']}")

    print("\n  → 接下来你可以：")
    print("      import tangyuanAI（pip 默认安装名）")
    print("      agent = agent_list['demo_agent']")
    print("      agent.conversation_with_tool('hi')")
    return 0


def cmd_help(_args: argparse.Namespace) -> int:
    """打印简版 help"""
    _build_parser().print_help()
    return 0


def main(argv: Optional[List[str]] = None) -> int:
    """CLI 入口"""
    # Windows 终端默认 GBK，先切 UTF-8 再打印 ✓/✗ 等字符
    if sys.platform == "win32":
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except (AttributeError, UnicodeError):
            pass
    parser = _build_parser()
    args = parser.parse_args(argv)

    # 子命令统一委派（kb / image-gen / plugin 等都有 func）
    cmd = getattr(args, "cmd", None)
    if cmd is not None:
        func = getattr(args, "func", None)
        if func is not None:
            return func(args)
        # 旧版兼容：kb 子命令走旧入口
        if cmd == "kb":
            try:
                from .kb.cli import main as kb_main
                return kb_main(args)
            except ImportError:
                print("KB 子命令不可用（RAG 插件未安装？）。")
                return 1
        print("子命令参数缺失。")
        return 1

    if args.quiet:
        silence_banner()

    if args.version:
        from tangyuanAI import __version__
        print(__version__)
        return 0

    if not (args.doctor or args.demo):
        # 默认行为：先打 banner 再走 doctor，让用户看到诊断
        print_banner()
        return cmd_doctor(args)

    if args.doctor:
        return cmd_doctor(args)
    if args.demo:
        return cmd_demo(args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
