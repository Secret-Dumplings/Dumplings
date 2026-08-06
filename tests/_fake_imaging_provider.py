# -*- coding: utf-8 -*-
"""
fake provider 实现（tests/_fake_imaging_provider.py）
====================================================

供 test_image_generation.py 的 provider_impl 插件测试用。
模拟一个"响应是 base64 内嵌"的厂商（HttpJsonImageProvider 不支持，需自定义插件）。
"""
from __future__ import annotations

from typing import Any


class Base64ImageProvider:
    """模拟 base64 响应厂商：generate 直接返回假 URL（测试用）。"""

    name = "fake-base64"

    def __init__(self, *, name: str, feature_cfg: dict):
        self.name = name
        self._cfg = feature_cfg

    async def generate(
        self, *, prompt: str, model: str | None = None, **kwargs: Any,
    ) -> list[str]:
        # 测试：模拟 base64 解码后落盘返回本地路径
        return ["http://fake/base64"]

    async def close(self) -> None:
        pass
