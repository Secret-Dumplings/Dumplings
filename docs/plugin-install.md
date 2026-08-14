---
slug: plugin-install
title: 第三方插件安装（CLI install-git）
order: 12
icon: PACKAGE_OUTLINED
---

# 第三方插件安装

> **v1.1.0+**。KB / 图片生成的**官方实现已 vendor 在主包**（`pip install tangyuanai` 自带）。
> 第三方插件 = 替换默认实现的兼容包（通过 `tangyuanai.plugins` entry point 注册）。
> 推荐安装路径：`tangyuanai plugin install-git <git-url>`。

## 一、官方默认（vendor）— 开箱即用

```bash
pip install tangyuanAI
tangyuanai plugin status
# KB  : vendored 默认实现（主包内置）
# Image: vendored 默认实现（主包内置）
```

不需要任何额外操作就能 `from tangyuanAI.kb import Knowledge` / `from tangyuanAI.imaging import ImageGenerator`。

## 二、装第三方插件

### 方式 A：从 git URL 装（推荐）

```bash
# 官方子仓作示例（保留作可选插件源）
tangyuanai plugin install-git https://github.com/secret-tangyuan/tangyuanAI_RAG_plus.git
tangyuanai plugin install-git https://github.com/secret-tangyuan/tangyuanAI_image_plus.git

# 自己的 fork / 第三方包都行
tangyuanai plugin install-git https://github.com/your-fork/tangyuanai-kb-alt.git

# editable 模式（开发期常用）
tangyuanai plugin install-git https://github.com/your-fork/tangyuanai-kb-alt.git --editable

# 单仓多包（plugin 是 monorepo 时用）
tangyuanai plugin install-git https://github.com/some/monorepo.git --dir plugins/kb
```

参数：
- `--branch` / `--branch` 默认 `main`
- `--dir` 指定仓内子目录（plugin 是 monorepo 时用）
- `--editable` / `-e` editable 安装

### 方式 B：标准 pip 装（包已发 PyPI）

```bash
pip install tangyuanai-kb-alt        # 第三方 KB 替代
pip install tangyuanai-image-alt     # 第三方图片替代
```

第三方包必须：
- 在 `[project.entry-points."tangyuanai.plugins"]` 注册 entry point
- name + module 对应 `kb` / `image`（或自定义），type 对应 `knowledge_base` / `image_generation`

### 方式 C：传统 `tangyuanai plugin install <name>`

仅适用**装 config 模板**（JSON 合并到本地 `tangyuanai.config.json`），不装代码：

```bash
tangyuanai plugin list
tangyuanai plugin install rag
tangyuanai plugin install image_generation
tangyuanai plugin install image_generation --no-enable   # 只下载不启用
```

## 三、验证

```bash
tangyuanai plugin status
# 已装插件包 + KB/Image 子系统:
#   KB  : 第三方插件接管 (tangyuanai_kb_alt)
#   Image: vendored 默认实现（主包内置）
```

## 中央 config 仓库

| 仓库 | 内容 |
|---|---|
| https://github.com/secret-tangyuan/tangyuanAI_image_plus | 图片生成 provider 配置（`image_generation*.json`） |
| https://github.com/secret-tangyuan/tangyuanAI_RAG_plus | （已迁回主包，仓保留作可选 git 装源） |

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
能力 Protocol，装进环境即替换官方 KB / 图片插件，核心零改动。