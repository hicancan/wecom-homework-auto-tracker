import type { CollectionIndex, CollectionManifest, CollectionRoot, SubmissionStat } from './types'

function joinPublicPath(publicBase: string, relativePath: string): string {
  const base = publicBase.endsWith('/') ? publicBase : `${publicBase}/`
  return `${base}${relativePath}`
}

function appendVersion(url: string, version?: string): string {
  if (!version) return url
  const connector = url.includes('?') ? '&' : '?'
  return `${url}${connector}v=${encodeURIComponent(version)}`
}

async function fetchJson<T>(url: string, init?: RequestInit): Promise<T> {
  const response = await fetch(url, init)
  if (!response.ok) {
    throw new Error(`HTTP ${response.status}`)
  }
  return (await response.json()) as T
}

export async function loadCollectionRoot(publicBase: string): Promise<{
  manifest: CollectionManifest
  index: CollectionRoot
}> {
  const manifestUrl = `${joinPublicPath(publicBase, 'course-manifest.json')}?t=${Date.now()}`
  const manifest = await fetchJson<CollectionManifest>(manifestUrl, { cache: 'no-store' })
  if (!manifest.indexFile) {
    throw new Error('course-manifest.json 缺少 indexFile')
  }

  const index = await fetchJson<CollectionRoot>(
    appendVersion(joinPublicPath(publicBase, manifest.indexFile), manifest.version),
  )
  if (!(index.收集表列表 || []).length) {
    throw new Error('收集表索引中没有可用数据')
  }
  return { manifest, index }
}

export async function loadCollectionIndex(
  publicBase: string,
  relativePath: string,
  version?: string,
): Promise<CollectionIndex> {
  return fetchJson<CollectionIndex>(appendVersion(joinPublicPath(publicBase, relativePath), version))
}

export async function loadSubmissionStat(
  publicBase: string,
  relativePath: string,
  version?: string,
): Promise<SubmissionStat> {
  return fetchJson<SubmissionStat>(appendVersion(joinPublicPath(publicBase, relativePath), version))
}
