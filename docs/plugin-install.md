---
slug: plugin-install
title: Plugin 安装（中央 config 仓库 + 代码包）
order: 12
icon: PACKAGE_OUTLINED
---

# Plugin 安装（中央 config 仓库 + 代码包）

> **v1.1.0+**。插件 = **代码包**（pip 安装，entry point 注册）+ **config**（合并到本地 `tangyuanai.config.json`）。
> `tangyuanai plugin install <name>` 负责 config；代码包用 `pip install "tangyuanAI[all]"` 或单独 `pip install`。

## 一、装代码包（实现）

```bash
# 官方两个插件一起装（RAG 知识库 + 图片生成）
pip install "tangyuanAI[all]"

# 单独装
pip install tangyuanai-rag-plus        # 知识库 / RAG
pip install tangyuanai-image-plus      # 图片生成
```

装完即注册插件，CLI 自动出现 `kb` / `image-gen` 子命令：

```bash
tangyuanai plugin status
tangyuanai --doctor
tangyuanai --help          # 应看到 {plugin,kb,image-gen}
```

## 二、装 config（可选，配置/启用 feature）

```bash
# 列出本地已启用的 plugin
tangyuanai plugin list

# 安装并启用（代码包已装时直接用包内置 config，离线可用）
tangyuanai plugin install rag
tangyuanai plugin install image_generation

# 只下载不启用
tangyuanai plugin install image_generation --no-enable
```

## 中央 config 仓库

| 仓库 | 内容 | 文件 |
|---|---|---|
| https://github.com/secret-tangyuan/tangyuanAI_image_plus | 图片生成 provider 配置 | `image_generation*.json` |
| https://github.com/secret-tangyuan/tangyuanAI_RAG_plus | RAG 插件清单 | `rag.json` |

raw URL 模板：`https://raw.githubusercontent.com/secret-tangyuan/<repo>/main/<name>.json`
已知插件名自动匹配仓库（`plugin_store.PLUGIN_REPO_MAP`），无需 `--repo`；也可显式指定：

```bash
tangyuanai plugin install image_generation \
    --owner other-user --repo other-plugins --branch main
```

安装后的 config 合并到本地 `tangyuanai.config.json`：
- 同 `name` 替换（升级覆盖）、新 `name` 追加
- 下载的 JSON 没写 `enabled` 时默认 `true`

## 部署一个新插件配置

1. 在对应中央仓库创建 `<name>.json`（格式见 [image-generation.md](image-generation.md)）
2. 提交 PR / push 到 `main`
3. 用户 `tangyuanai plugin install <name>` 即用

## 开发自己的插件 / 替换实现

见 [plugin-dev.md](plugin-dev.md)（接口文档）：实现 `tangyuanai.plugins` entry point +
能力 Protocol，装进环境即替换官方 RAG / 图片插件，核心零改动。
