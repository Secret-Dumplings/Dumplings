# -*- coding: utf-8 -*-
"""tangyuanai.imaging.generator —— 从 config 读 enabled features，实例化 provider，路由调用。"""
from __future__ import annotations

from typing import Any

from tangyuanAI.config import find_feature, load_config
from tangyuanAI.logging_config import get_logger

from .provider import (
    HttpJsonImageProvider,
    ImageError,
    ImageProvider,
    download_urls,
)

__all__ = ["ImageGenerator"]


class ImageGenerator:
    """图片生成入口。

    - 从 config 读 enabled feature（type=image_generation）
    - 按 feature["config"]["provider"] 实例化 HttpJsonImageProvider
    - generate(prompt, ...) → URL 列表 或 本地路径（download=True）
    """

    def __init__(self, config_path: str | None = None):
        self.config = load_config(config_path)
        self._providers: dict[tuple[str, str], ImageProvider] = {}
        self._log = get_logger("imaging.generator")

    def _get_provider(self, feature: dict) -> ImageProvider:
        cfg = feature["config"]
        key = (feature["name"], cfg["provider"])
        if key in self._providers:
            return self._providers[key]

        # 自定义 provider 实现（覆盖传输差异：form-data / base64 / 自定义鉴权等）
        impl = cfg.get("provider_impl")
        if impl:
            self._providers[key] = self._instantiate_impl(impl, feature)
        else:
            self._providers[key] = HttpJsonImageProvider(
                name=key[1], feature_cfg=cfg,
            )
        return self._providers[key]

    @staticmethod
    def _instantiate_impl(impl: str, feature: dict) -> ImageProvider:
        """从 "module:ClassName" 导入并实例化自定义 provider。

        自定义 provider 需实现 ImageProvider Protocol：
            class X:
                name = "x"
                def __init__(self, *, name, feature_cfg): ...
                async def generate(self, *, prompt, model=None, **kwargs) -> list[str]: ...
                async def close(self): ...
        """
        if ":" not in impl:
            raise ImageError(
                f"provider_impl 格式应为 'module:ClassName'，got {impl!r}"
            )
        module_path, class_name = impl.split(":", 1)
        try:
            import importlib
            module = importlib.import_module(module_path)
        except ImportError as e:
            raise ImageError(
                f"导入 provider_impl 模块失败: {module_path}（{e}）"
            ) from e
        cls = getattr(module, class_name, None)
        if cls is None:
            raise ImageError(
                f"provider_impl 模块 {module_path} 里找不到类 {class_name!r}"
            )
        return cls(name=feature["config"]["provider"], feature_cfg=feature["config"])

    async def generate(
        self,
        feature_name: str = "image_generation",
        *,
        prompt: str,
        model: str | None = None,
        download: bool = False,
        download_dir: str = "./images",
        **kwargs: Any,
    ) -> list[str]:
        """生成图片。

        Args:
            feature_name: config 里的 feature 名（默认 image_generation）
            prompt: 文本提示词
            model: 覆盖 config 里的 default_model
            download: 是否下载到本地（URL 1 小时过期）
            download_dir: 下载目录（download=True 时生效）

        Returns:
            list[str] —— URL 列表 或 本地路径列表
        """
        feat = find_feature(self.config, feature_name)
        if not feat or not feat.get("enabled", False):
            raise ImageError(f"feature {feature_name!r} 未在 config 启用")
        if feat.get("type") != "image_generation":
            raise ImageError(
                f"feature {feature_name!r} type={feat.get('type')!r} 不是 image_generation"
            )

        provider = self._get_provider(feat)
        cfg = feat.get("config", {})
        urls = await provider.generate(
            prompt=prompt,
            model=model or cfg.get("default_model"),
            **kwargs,
        )
        if download:
            return await download_urls(urls, download_dir)
        return urls

    async def close(self) -> None:
        for p in self._providers.values():
            try:
                await p.close()
            except Exception:
                pass
        self._providers.clear()
