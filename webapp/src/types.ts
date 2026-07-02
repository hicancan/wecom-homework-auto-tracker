export type CollectionStatus = 'active' | 'archived'

export type CollectionItem = {
  收集表ID: string
  数据文件: string
  标题: string
  主题: string
  对象: string
  周期?: string
  状态: CollectionStatus
}

export type CollectionRoot = {
  更新时间?: string
  最后部署时间?: string
  收集表列表: CollectionItem[]
}

export type CollectionManifest = {
  version: string
  indexFile: string
  更新时间?: string
  最后部署时间?: string
}

export type SubmissionRef = {
  提交序号ID: string
  提交序号: string
  数据文件: string
  提交内容列表?: string[]
}

export type CollectionIndex = {
  收集表ID: string
  标题: string
  主题?: string
  对象?: string
  周期?: string
  状态?: CollectionStatus
  更新时间?: string
  最后部署时间?: string
  提交序号列表: SubmissionRef[]
}

export type ClassStat = {
  应交人数: number
  截止已提交人数?: number
  截止未提交人数?: number
  截止提交率?: number
  截止已提交名单?: string[]
  截止未提交名单?: string[]
  已提交人数: number
  未提交人数: number
  提交率: number
  已提交名单: string[]
  未提交名单: string[]
  后缀无效人数?: number
  后缀无效名单?: string[]
  已补交人数?: number
  已补交名单?: string[]
}

export type ContentStatPayload = {
  班级统计?: Record<string, ClassStat>
}

export type ContentStatSummary = {
  提交内容: string
  应交人数: number
  已提交人数: number
  未提交人数: number
  后缀无效人数: number
  已补交人数: number
  提交率: number
}

export type IssueSummary = {
  总人数: number
  班级统计?: Record<string, string[]>
}

export type SubmissionStat = {
  收集表ID: string
  标题: string
  主题?: string
  对象?: string
  周期?: string
  状态?: CollectionStatus
  提交序号ID?: string
  提交序号: string
  提交内容列表?: string[]
  提交内容统计?: Record<string, ContentStatPayload> | ContentStatSummary[]
  更新时间?: string
  最后部署时间?: string
  最后提交时间?: string
  统计截止时间?: string
  发布模式?: '截止模式' | '补交窗口模式'
  允许补交?: boolean
  补交窗口开始时间?: string
  补交窗口结束时间?: string
  隐藏未提交?: boolean
  后缀无效?: IssueSummary
  其他已提交名单?: string[]
  其他后缀无效名单?: string[]
  其他已补交名单?: string[]
  汇总?: {
    应交总人数: number
    截止已提交总人数?: number
    已补交总人数?: number
    已提交总人数: number
    未提交总人数: number
    总提交率: number
    后缀无效总人数?: number
  }
  班级统计: Record<string, ClassStat>
}
