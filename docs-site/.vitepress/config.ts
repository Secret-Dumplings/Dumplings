import { defineConfig } from 'vitepress'
import { readdirSync, readFileSync } from 'node:fs'
import { resolve, dirname } from 'node:path'
import { fileURLToPath } from 'node:url'

const __dirname = dirname(fileURLToPath(import.meta.url))
// markdown 源目录：docs-site/docs-build/（构建前由 scripts/sync-docs.mjs 从 ../docs 同步）
// 必须放在 docs-site/ 内（与 node_modules 同层），否则 pnpm 依赖隔离下
// docs/*.md 里的 vue 依赖解析不到，干净环境（Cloudflare Pages / CI）构建会挂。
const DOCS_DIR = resolve(__dirname, '../docs-build')

interface DocMeta {
  file: string
  title: string
  order: number
  icon: string
}

/** 极简 frontmatter 解析（只取 slug/title/order/icon 标量字段，够用即可） */
function parseFrontmatter(raw: string): Record<string, string | number> {
  const m = raw.match(/^---\n([\s\S]*?)\n---/)
  if (!m) return {}
  const meta: Record<string, string | number> = {}
  for (const line of m[1].split('\n')) {
    const idx = line.indexOf(':')
    if (idx <= 0) continue
    const key = line.slice(0, idx).trim()
    const value = line.slice(idx + 1).trim().replace(/^['"]|['"]$/g, '')
    if (key in meta) continue
    meta[key] = /^\d+$/.test(value) ? Number(value) : value
  }
  return meta
}

/** 扫描 docs/*.md，按 frontmatter 的 order 排序 */
function loadDocs(): DocMeta[] {
  return readdirSync(DOCS_DIR)
    .filter((f) => f.endsWith('.md') && !f.startsWith('README'))
    .map((f) => {
      const raw = readFileSync(resolve(DOCS_DIR, f), 'utf-8')
      const meta = parseFrontmatter(raw)
      return {
        file: f.replace(/\.md$/, ''),
        title: String(meta.title ?? f.replace(/\.md$/, '')),
        order: Number(meta.order ?? 999),
        icon: String(meta.icon ?? ''),
      }
    })
    .sort((a, b) => a.order - b.order)
}

const docs = loadDocs()

/** 文件名 → 路由链接（index 是首页） */
const linkOf = (file: string) => (file === 'index' ? '/' : `/${file}`)

const sidebarItems = docs.map((d) => ({ text: d.title, link: linkOf(d.file) }))

export default defineConfig({
  title: 'tangyuanAI',
  description: '轻量、模块化的多智能体协作框架',

  // srcDir 指向构建目录 docs-build/（构建前由 scripts/sync-docs.mjs 从 ../docs 同步），
  // 必须放在 docs-site/ 内（与 node_modules 同层），否则 pnpm 依赖隔离下
  // docs/*.md 里的 vue 依赖解析不到，干净环境（Cloudflare Pages / CI）构建会挂。
  srcDir: DOCS_DIR,
  // public/（如 _redirects）相对 docs-site/ 根，显式指定避免受 srcDir 影响
  publicDir: resolve(__dirname, '../public'),
  cleanUrls: true,
  lastUpdated: true,
  ignoreDeadLinks: true,

  themeConfig: {
    logo: '/logo.svg',
    nav: [
      { text: '首页', link: '/' },
      { text: 'GitHub', link: 'https://github.com/secret-tangyuan/tangyuanAI' },
    ],
    sidebar: [
      {
        text: '文档',
        items: sidebarItems,
      },
    ],
    search: {
      provider: 'local',
      options: {
        translations: {
          button: { buttonText: '搜索文档', buttonAriaLabel: '搜索文档' },
          modal: {
            displayDetails: '显示详情',
            resetButtonTitle: '重置',
            backButtonTitle: '返回',
            noResultsText: '没有找到相关结果',
            footer: { selectText: '选择', navigateText: '切换', closeText: '关闭' },
          },
        },
      },
    },
    outline: { level: [2, 3], label: '本页目录' },
    docFooter: { prev: '上一篇', next: '下一篇' },
    sidebarMenuLabel: '目录',
    returnToTopLabel: '回到顶部',
    darkModeSwitchLabel: '外观',
    lastUpdatedText: '最后更新',
  },
})