# dumplingsAI 文档站

VitePress 实现，BBDDFF 浅蓝色主题。markdown 源在 `../docs/`（frontmatter 驱动，自动排序）。

线上地址：**https://docs.dumplingsai.secret-dumplings.xin**（Cloudflare Pages，push 自动构建）

## 启动

```bash
cd Dumplings/docs-site

# 前端（VitePress dev server，自动同步 docs + 生成 api-data）
pnpm install         # 首次
pnpm dev             # http://localhost:5173

# 后端（FastAPI，可选 — 仅本地 dev 演示）
pnpm api             # http://localhost:8001
```

## 目录结构

```
docs-site/
├── .vitepress/
│   ├── config.ts            # 侧栏自动生成（frontmatter order 排序）、srcDir → docs-build/
│   └── theme/
│       ├── index.ts         # 主题入口
│       └── style.css        # BBDDFF 浅蓝配色（CSS 变量）
├── docs-build/              # 构建产物（.gitignore 排除，由 sync-docs.mjs 生成）
├── api-data.json            # 构建产物（.gitignore 排除，由 generate-api-data.mjs 生成）
├── functions/api/           # Pages Functions（线上 /api/*，替代 FastAPI）
│   ├── _lib.ts              # 共享工具
│   ├── health.ts            # GET /api/health
│   ├── docs/list.ts         # GET /api/docs/list
│   ├── docs/[slug].ts       # GET /api/docs/{slug}
│   └── search.ts            # GET /api/search?q=
├── public/_redirects        # SPA 回退（/* → /index.html）
├── scripts/
│   ├── sync-docs.mjs        # ../docs/*.md → docs-build/（构建前）
│   └── generate-api-data.mjs# docs-build/*.md → api-data.json（构建前）
├── api/                     # FastAPI 后端（仅本地 dev 演示）
│   ├── __init__.py
│   ├── docs_loader.py       # 读 ../docs/*.md + frontmatter
│   └── main.py              # /api/docs/list, /api/docs/{slug}, /api/search
├── deploy/                  # 服务器版一键部署（Ubuntu + Nginx + Let's Encrypt，不进 git）
│   ├── deploy.sh
│   ├── nginx.conf.template
│   ├── README.md
│   └── PAGES.md             # Cloudflare Pages 部署文档（本方案）
├── package.json
└── README.md
```

## 新增文档

往 `../docs/` 加一个带 frontmatter 的 .md 即可，不用改任何代码：

```markdown
---
slug: my-new-doc
title: 我的新文档
order: 11
icon: STAR_OUTLINED
---

# 我的新文档
正文...
```

侧栏自动按 `order` 排序；push 到 main 后 Pages 自动构建上线。

## 构建流水线

```
pnpm build
├─ node scripts/sync-docs.mjs          # ../docs/*.md → docs-build/（node_modules 同层）
│                                      #   原因：srcDir 在 node_modules 外时 pnpm 依赖隔离
│                                      #   导致 docs/*.md 解析不到 vue，CI/Pages 干净环境会挂
├─ node scripts/generate-api-data.mjs  # docs-build/*.md → api-data.json
└─ vitepress build .                   # srcDir = docs-build/，publicDir → public/
```

## 部署

### Cloudflare Pages（推荐，线上当前方案）

Dashboard 配置见 `deploy/PAGES.md`。要点：

- **Root directory**：`docs-site`
- **Build command**：`pnpm install && pnpm build`
- **Build output**：`.vitepress/dist`
- 域名：`docs.dumplingsai.secret-dumplings.xin`（CNAME → dumplingsai.pages.dev）
- 每次 push main 自动构建；HTTPS 证书自动签发 + 自动续签

### 本地构建 / 服务器版

```bash
pnpm build       # 出 .vitepress/dist/ 静态文件
pnpm preview     # 预览 build 产物
```

服务器自建（Nginx + Let's Encrypt + 自动续签）见 `deploy/README.md`。

## 关键设计

- **srcDir 指向构建目录 `docs-build/`**：构建前由 `sync-docs.mjs` 从 `../docs/` 同步。必须与 node_modules 同层，否则 pnpm 依赖隔离下 docs/*.md 解析不到 vue，干净环境构建必挂。
- **`/api/*` 双实现**：线上用 Pages Functions（`functions/api/`，构建时从 `api-data.json` 读数据）；本地 dev 用 FastAPI（`api/`）。**行为一致**（JSON 字段相同）。
- **BBDDFF 浅蓝主题**：仅覆盖 CSS 变量（`--vp-c-brand-1` 等），不 fork 主题。
- **打包隔离**：`pyproject.toml` 用 `exclude-package-data` + `MANIFEST.in` 排除 `docs-site/**`，保证 wheel/sdist 干净；GA publish workflow 有 "Verify wheel excludes docs-site" 校验步骤。
- **图标**：frontmatter 的 `icon` 字段是 Material Icons 枚举名（`HOME_OUTLINED` / `EDIT_NOTE_OUTLINED` 等），目前侧栏显示文字（图标留待扩展）。