# -*- coding: utf-8 -*-
"""tangyuanai.config —— 用户配置加载 + feature 查找 + 合并。

加载 `tangyuanai.config.json`（路径查找顺序：cwd → $TANGYUAN_CONFIG → 默认 cwd）。

Schema（v1）：
{
  "features": [
    {
      "name": "image_generation",
      "type": "image_generation",
      "enabled": true,
      "config": {
        "provider": "siliconflow",
        "api_base": "https://api.siliconflow.cn/v1",  # 支持 ${env:VAR} 占位
        "api_key_env": "TANGYUAN_IMAGE_API_KEY",
        "default_model": "Qwen/Qwen-Image-Edit-2509",
        "default_image_size": "1024x1024",
        "request_template": { ... },
        "request_static": {"stream": false},
        "response_image_url_path": "data.0.url"
      }
    }
  ]
}

API：
- load_config(path=None) -> dict
- save_config(config, path=None) -> None
- find_feature(config, name) -> dict | None
- find_feature_by_type(config, type) -> dict | None
- get_enabled_features(config, type=None) -> list
- merge_feature(config, new_feature) -> dict
- resolve_url_template(api_base, env) -> str
"""
from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any, Optional

__all__ = [
    "load_config",
    "save_config",
    "find_feature",
    "find_feature_by_type",
    "get_enabled_features",
    "merge_feature",
    "resolve_url_template",
    "config_path",
]


def config_path(explicit: Optional[str] = None) -> Path:
    """解析 config 文件路径：explicit → $TANGYUAN_CONFIG → ./tangyuanai.config.json。"""
    if explicit:
        return Path(explicit).expanduser()
    env = os.environ.get("TANGYUAN_CONFIG")
    if env:
        return Path(env).expanduser()
    return Path("tangyuanai.config.json").resolve()


def load_config(path: Optional[str] = None) -> dict:
    """加载 config JSON；不存在返回 {}。"""
    p = config_path(path)
    if not p.exists():
        return {}
    try:
        import json
        text = p.read_text(encoding="utf-8")
        return json.loads(text)
    except Exception as e:
        # 损坏的 config 不应阻塞整个框架；仅警告
        from .logging_config import get_logger
        get_logger("tangyuanAI.config").warning(f"加载 config 失败 {p}: {e}")
        return {}


def save_config(config: dict, path: Optional[str] = None) -> None:
    """写回 config JSON。"""
    import json
    p = config_path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")
    from .logging_config import get_logger
    get_logger("tangyuanAI.config").info(f"config 已保存: {p}")


def find_feature(config: dict, name: str) -> Optional[dict[str, Any]]:
    """按 name 查 feature。"""
    for f in config.get("features", []) or []:
        if f.get("name") == name:
            return f
    return None


def find_feature_by_type(config: dict, feature_type: str) -> Optional[dict[str, Any]]:
    """按 type 查第一个 enabled 的 feature（v1 同 type 通常只一个）。"""
    for f in config.get("features", []) or []:
        if f.get("type") == feature_type and f.get("enabled", True):
            return f
    return None


def get_enabled_features(config: dict, feature_type: Optional[str] = None) -> list[dict[str, Any]]:
    """所有 enabled features；可选 type 过滤。"""
    feats = [f for f in config.get("features", []) or [] if f.get("enabled", True)]
    if feature_type is not None:
        feats = [f for f in feats if f.get("type") == feature_type]
    return feats


def merge_feature(config: dict, new_feature: dict) -> dict:
    """按 name 替换/追加 feature（返回新 config，不修改原对象）。"""
    feats = [f for f in config.get("features", []) or [] if f.get("name") != new_feature.get("name")]
    feats.append(new_feature)
    return {**config, "features": feats}


def resolve_url_template(api_base: str, env: Optional[dict] = None) -> str:
    """把 ${env:VAR} 替换为 env[VAR]（env 默认 os.environ）。"""
    e = env if env is not None else os.environ
    return re.sub(r"\$\{env:(\w+)\}", lambda m: e.get(m.group(1), ""), api_base)
