import { readFileSync, readdirSync, statSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { join } from 'node:path'

const publicRoot = new URL('../public/', import.meta.url)
const publicPath = fileURLToPath(publicRoot)

function readJson(relativePath) {
  return JSON.parse(readFileSync(join(publicPath, relativePath), 'utf8'))
}

function assert(condition, message) {
  if (!condition) {
    throw new Error(message)
  }
}

function walkJsonFiles(dir) {
  const files = []
  for (const name of readdirSync(dir)) {
    const full = join(dir, name)
    const stat = statSync(full)
    if (stat.isDirectory()) {
      files.push(...walkJsonFiles(full))
    } else if (name.endsWith('.json')) {
      files.push(full)
    }
  }
  return files
}

const root = readJson('collections.json')
assert(Array.isArray(root.收集表列表), 'collections.json 必须包含 收集表列表')
assert(!Object.hasOwn(root, '课程列表'), 'public 根索引不得包含旧字段 课程列表')

const edgeone = readJson('edgeone.json')
assert(Array.isArray(edgeone.headers), 'edgeone.json 必须声明 headers')

function headersFor(source) {
  const entry = edgeone.headers.find((item) => item.source === source)
  assert(entry, `edgeone.json 缺少规则: ${source}`)
  assert(Array.isArray(entry.headers), `edgeone.json headers 无效: ${source}`)
  return Object.fromEntries(entry.headers.map((item) => [item.key, item.value]))
}

function assertCache(source, expected) {
  const headers = headersFor(source)
  assert(headers['Cache-Control'] === expected, `${source} Cache-Control 应为 ${expected}`)
}

const baseHeaders = headersFor('/*')
assert(baseHeaders['X-Content-Type-Options'] === 'nosniff', 'edgeone.json 缺少 nosniff')
assert(baseHeaders['X-Frame-Options'] === 'SAMEORIGIN', 'edgeone.json 缺少 X-Frame-Options')
assert(baseHeaders['Referrer-Policy'] === 'strict-origin-when-cross-origin', 'edgeone.json 缺少 Referrer-Policy')
assertCache('/course-manifest.json', 'no-store, max-age=0, must-revalidate')
assertCache('/collections.json', 'no-store, max-age=0, must-revalidate')
assertCache('/data/*.json', 'no-store, max-age=0, must-revalidate')
assertCache('/data/*/*.json', 'no-store, max-age=0, must-revalidate')
assertCache('/assets/*', 'public, max-age=31536000, immutable')

for (const item of root.收集表列表) {
  assert(item.收集表ID, '收集表项缺少 收集表ID')
  assert(item.数据文件 === `data/${item.收集表ID}/index.json`, `收集表数据路径必须稳定: ${item.收集表ID}`)
  const index = readJson(item.数据文件)
  assert(index.收集表ID === item.收集表ID, `收集表索引 ID 不一致: ${item.收集表ID}`)
  assert(Array.isArray(index.提交序号列表), `收集表索引缺少 提交序号列表: ${item.收集表ID}`)
  for (const ref of index.提交序号列表) {
    assert(ref.提交序号ID, `提交序号缺少稳定 ID: ${item.收集表ID}`)
    assert(ref.数据文件 === `data/${item.收集表ID}/${ref.提交序号ID}.json`, `提交序号数据路径必须稳定: ${item.收集表ID}`)
    const stat = readJson(ref.数据文件)
    assert(stat.收集表ID === item.收集表ID, `统计文件 ID 不一致: ${ref.数据文件}`)
    assert(stat.提交序号ID === ref.提交序号ID, `统计文件 seq ID 不一致: ${ref.数据文件}`)
    assert(!Object.hasOwn(stat, '课程'), `统计文件不得包含旧字段 课程: ${ref.数据文件}`)
  }
}

for (const full of walkJsonFiles(join(publicPath, 'data'))) {
  const data = JSON.parse(readFileSync(full, 'utf8'))
  assert(!Object.hasOwn(data, '课程'), `public data 不得包含旧字段 课程: ${full}`)
  assert(!Object.hasOwn(data, '作业'), `public data 不得包含旧字段 作业: ${full}`)
}

console.log(`validated ${root.收集表列表.length} collections`)
