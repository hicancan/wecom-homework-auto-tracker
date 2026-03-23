export type CourseItem = {
  课程: string
  数据文件: string
}

export type CourseIndex = {
  更新时间?: string
  最后部署时间?: string
  课程列表: CourseItem[]
}

export type CourseManifest = {
  version: string
  indexFile: string
  更新时间?: string
  最后部署时间?: string
}

function joinPublicPath(publicBase: string, relativePath: string): string {
  const base = publicBase.endsWith('/') ? publicBase : `${publicBase}/`
  return `${base}${relativePath}`
}

async function fetchJson<T>(url: string, init?: RequestInit): Promise<T> {
  const response = await fetch(url, init)
  if (!response.ok) {
    throw new Error(`HTTP ${response.status}`)
  }
  return (await response.json()) as T
}

export async function loadCourseIndex(publicBase: string): Promise<{
  manifest: CourseManifest
  index: CourseIndex
}> {
  const manifestUrl = `${joinPublicPath(publicBase, 'course-manifest.json')}?t=${Date.now()}`
  const manifest = await fetchJson<CourseManifest>(manifestUrl, {
    cache: 'no-store',
  })
  if (!manifest.indexFile) {
    throw new Error('course-manifest.json 缺少 indexFile')
  }

  const index = await fetchJson<CourseIndex>(joinPublicPath(publicBase, manifest.indexFile))
  if (!(index.课程列表 || []).length) {
    throw new Error('课程索引中没有可用课程数据')
  }

  return { manifest, index }
}
