# -*- coding: utf-8 -*-
"""
tangyuanai 命令行入口（Python 模块名 tangyuanAI）
==================================================

::

    tangyuanai --help        全部子命令
    tangyuanai --doctor      环境自检（Python / httpx / pydantic / API Key）
    tangyuanai --demo        跑一个最小离线示例（不连真 LLM）

也可以通过 ``python -m tangyuanAI`` 进入。
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
            "主要用途：环境自检 + 离线 demo + Agent/工具/会话管理。\n"
            "通过 `pip install tangyuanAI` 安装后可执行 `tangyuanai --help`。"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument(
        "--doctor", action="store_true",
        help="环境自检：Python 版本 / 关键依赖 / API Key / Agent 注册",
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

    # KB 子命令（kb.cli）
    try:
        from .kb.cli import add_subparser
        subparsers = p.add_subparsers(dest="cmd", help="子命令")
        add_subparser(subparsers)
    except ImportError:
        # KB 依赖未装时，kb 子命令不可用（不影响其他命令）
        subparsers = None

    # Image Gen 子命令 + Plugin 管理
    try:
        if subparsers is None:
            subparsers = p.add_subparsers(dest="cmd", help="子命令")
        _add_imaging_subparsers(subparsers)
    except ImportError:
        pass

    return p


def _add_imaging_subparsers(subparsers) -> None:
    """image-gen + plugin 子命令。"""

    # image-gen
    img_p = subparsers.add_parser("image-gen", help="图片生成（config 启用，provider 自定）")
    img_p.add_argument("prompt", help="文本提示词")
    img_p.add_argument("--feature", default="image_generation", help="config 里的 feature 名")
    img_p.add_argument("--config", help="tangyuanai.config.json 路径")
    img_p.add_argument("--model", default=None, help="覆盖 config 里的 default_model")
    img_p.add_argument("--download", action="store_true", help="下载到本地（URL 1 小时过期）")
    img_p.add_argument("--download-dir", default="./images", help="下载目录")
    img_p.add_argument("--negative-prompt", dest="negative_prompt", default=None)
    img_p.add_argument("--image-size", dest="image_size", default=None)
    img_p.add_argument("--seed", type=int, default=None)
    img_p.add_argument("--num-inference-steps", dest="num_inference_steps", type=int, default=None)
    img_p.add_argument("--batch-size", dest="batch_size", type=int, default=None)
    img_p.add_argument("--guidance-scale", dest="guidance_scale", type=float, default=None)
    img_p.add_argument("--cfg", type=float, default=None)
    img_p.add_argument("--image", default=None, help="base64 或 URL（编辑模式）")
    img_p.add_argument("--image2", dest="image2", default=None)
    img_p.add_argument("--image3", dest="image3", default=None)
    img_p.set_defaults(func=cmd_image_gen)

    # plugin
    plug_p = subparsers.add_parser("plugin", help="plugin 管理（install / list）")
    plug_sub = plug_p.add_subparsers(dest="plugin_action", required=True)

    pi = plug_sub.add_parser("install", help="从中央仓库下载并启用 plugin")
    pi.add_argument("name", help="plugin 名（中央仓库 <name>.json）")
    pi.add_argument("--config", help="tangyuanai.config.json 路径")
    pi.add_argument("--no-enable", action="store_true", help="只装不启用")
    pi.add_argument("--owner", default="secret-tangyuan", help="中央仓库 owner")
    pi.add_argument("--repo", default="tangyuanAI_image_plus", help="中央仓库 repo")
    pi.add_argument("--branch", default="main", help="中央仓库 branch")
    pi.set_defaults(func=cmd_plugin_install)

    pl = plug_sub.add_parser("list", help="列出本地已启用的 plugin")
    pl.add_argument("--config", help="tangyuanai.config.json 路径")
    pl.set_defaults(func=cmd_plugin_install)


def cmd_image_gen(args) -> int:
    """tangyuanai image-gen "prompt" → 打印图片 URL 或本地路径。"""
    import asyncio

    from .imaging import ImageGenerator

    g = ImageGenerator(config_path=args.config)
    kwargs = {}
    for k in ("negative_prompt", "image_size", "seed",
              "num_inference_steps", "batch_size", "guidance_scale", "cfg",
              "image", "image2", "image3"):
        v = getattr(args, k, None)
        if v is not None:
            kwargs[k] = v
    try:
        paths = asyncio.run(g.generate(
            feature_name=args.feature,
            prompt=args.prompt,
            model=args.model,
            download=args.download,
            download_dir=args.download_dir,
            **kwargs,
        ))
        for u in paths:
            print(u)
        return 0 if paths else 1
    finally:
        asyncio.run(g.close())


def cmd_plugin_install(args) -> int:
    """tangyuanai plugin install/list。"""
    import asyncio

    from .plugin_store import install_plugin, list_installed

    if getattr(args, "plugin_action", None) == "list":
        for f in list_installed(args.config):
            print(f"  enabled: {f.get('name')!r}  type={f.get('type')!r}")
        return 0

    asyncio.run(install_plugin(
        plugin_name=args.name,
        config_path=args.config,
        enable=not args.no_enable,
        owner=args.owner,
        repo=args.repo,
        branch=args.branch,
    ))
    print(f"plugin 已安装: {args.name}")
    return 0


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

    # kb 子命令委派
    if getattr(args, "cmd", None) == "kb":
        try:
            from .kb.cli import main as kb_main
            return kb_main(args)
        except ImportError:
            print("KB 子命令不可用（依赖未装？）。")
            return 1

    # image-gen / plugin 子命令委派
    if getattr(args, "cmd", None) in ("image-gen", "plugin"):
        func = getattr(args, "func", None)
        if func is None:
            print("子命令参数缺失。")
            return 1
        return func(args)

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
