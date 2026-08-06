---
slug: plugin-install
title: Plugin 安装（中央 config 仓库）
order: 12
icon: PACKAGE_OUTLINED
---

# Plugin 安装（中央 config 仓库）

> **v1.0.0+**。`tangyuanai plugin install <name>` 从中央 config 仓库下载 plugin 配置，合并到本地 `tangyuanai.config.json`。

## 中央仓库

- 仓库：https://github.com/secret-tangyuan/tangyuanAI_image_plus
- 约定：每个 plugin 一个 `<name>.json` 文件，在 `main` 分支根目录
- raw URL 模板：`https://raw.githubusercontent.com/secret-tangyuan/tangyuanAI_image_plus/main/{name}.json`

## 用法

```bash
# 列出本地已启用的 plugin
tangyuanai plugin list
# →   enabled: 'image_generation'  type='image_generation'

# 从中央仓库下载并启用
tangyuanai plugin install image_generation
# → plugin 已安装: image_generation

# 只下载不启用
tangyuanai plugin install image_generation --no-enable

# 从其它仓库安装
tangyuanai plugin install image_generation \
    --owner other-user --repo other-plugins --branch main

# 自定义 config 路径
tangyuanai plugin install image_generation --config ./my/tangyuanai.config.json
```

安装后的 plugin 配置合并到本地 `tangyuanai.config.json`：
- **同 name 替换**（升级覆盖）
- **新 name 追加**（保留已有 features）
- 下载的 JSON 若没写 `enabled`，默认设 `true`

## 部署一个新 plugin

1. 在 `tangyuanAI_image_plus` 仓库创建 `<name>.json`（格式见 [image-generation.md](image-generation.md)）
2. 提交 PR / push 到 `main`
3. 用户 `tangyuanai plugin install <name>` 即用

```json
{
  "name": "image_generation",
  "type": "image_generation",
  "config": {
    "provider": "siliconflow",
    "api_base": "https://api.siliconflow.cn/v1",
    "api_key_env": "TANGYUAN_IMAGE_API_KEY",
    "default_model": "Qwen/Qwen-Image-Edit-2509",
    "request_template": { "model": "${model}", "prompt": "${prompt}" },
    "response_image_url_path": "data.0.url"
  }
}
```

## 换仓库

`plugin_store.py` 顶部 `DEFAULT_OWNER` / `DEFAULT_REPO` / `DEFAULT_BRANCH` 三个常量，或 CLI `--owner / --repo / --branch`。
