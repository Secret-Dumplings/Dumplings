// scripts/sync-docs.mjs
// 构建前把 ../docs/*.md 同步到 docs-site/docs/（node_modules 同层）。
//
// 原因：VitePress 的 srcDir 如果指向仓库根的 docs/（node_modules 之外），
// 在 pnpm 依赖隔离下，docs/*.md 里的 vue 依赖解析不到 docs-site/node_modules，
// 干净环境（Cloudflare Pages / CI）构建必挂。同步到构建目录内即可。
import { mkdirSync, readdirSync, copyFileSync, rmSync, existsSync, statSync, utimesSync } from 'node:fs'
import { resolve, dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'

const __dirname = dirname(fileURLToPath(import.meta.url))
const SRC = resolve(__dirname, '../../docs')    // Tangyuan/docs/（数据源）
const DST = resolve(__dirname, '../docs-build') // 构建目录（.gitignore 排除）
const SKIP = new Set(['README.md'])

mkdirSync(DST, { recursive: true })

// 1) 删除 DST 里已被源删除的 .md
for (const f of readdirSync(DST)) {
  if (f.endsWith('.md') && !existsSync(join(SRC, f))) {
    rmSync(join(DST, f), { force: true })
  }
}

// 2) 复制源 .md（保留修改时间戳，便于 VitePress 增量）
let copied = 0
for (const f of readdirSync(SRC)) {
  if (!f.endsWith('.md') || SKIP.has(f)) continue
  const src = join(SRC, f)
  const dst = join(DST, f)
  if (!existsSync(dst) || statSync(src).mtimeMs !== statSync(dst).mtimeMs) {
    copyFileSync(src, dst)
    // 手动还原 mtime，让 VitePress 认为是同一文件
    utimesSync(dst, statSync(src).atime, statSync(src).mtime)
    copied += 1
  }
}

// 3) 同步 public/ 静态资源 → docs-build/public/
// VitePress 的 publicDir = srcDir/public，所以 _redirects 等必须进构建目录
const SRC_PUBLIC = resolve(__dirname, '../public')
const DST_PUBLIC = join(DST, 'public')
mkdirSync(DST_PUBLIC, { recursive: true })
let pubCopied = 0
for (const f of readdirSync(SRC_PUBLIC)) {
  const src = join(SRC_PUBLIC, f)
  const dst = join(DST_PUBLIC, f)
  if (!existsSync(dst) || statSync(src).mtimeMs !== statSync(dst).mtimeMs) {
    copyFileSync(src, dst)
    pubCopied += 1
  }
}

console.log(`[sync-docs] ${copied} 个文档 + ${pubCopied} 个 public 资源已同步 → docs-build/ (共 ${readdirSync(DST).filter(f => f.endsWith('.md')).length} 个)`)