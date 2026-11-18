export interface UploadInfo {
  upload_id: string
  name: string
  kind: string
  crs_status: string
  suggested_crs: string | null
  summary: string
}

export interface ReviewIssue {
  rule: string
  severity: string
  message: string
  fix_spec_patch?: Record<string, unknown>
}

export interface ReviewResult {
  passed?: boolean
  allow_render?: boolean
  issues?: ReviewIssue[]
  summary?: string
  round?: number
}

export interface ResultPayload {
  status: 'rendered' | 'needs_input' | 'failed'
  round_no: number
  elapsed: number
  summary: string
  notes: string[]
  review: ReviewResult | null
  spec: Record<string, unknown> | null
  decision: string | null
  questions: string[]
  png: string | null
  pdf: string | null
}

export interface CrsRequired {
  upload_id: string
  name: string
  suggested: string
  options: string[]
}

export interface Message {
  id: string
  role: 'user' | 'assistant'
  text: string
  stage?: string
  error?: string
  result?: ResultPayload
  questions?: string[]
  crs?: CrsRequired
}

// 历史会话：meta 用于侧栏列表，detail 用于点开后恢复整段对话。
export interface SessionMeta {
  id: string
  title: string
  created_at: string
  updated_at: string
  message_count: number
}

export interface SessionDetail extends SessionMeta {
  messages: Message[]
}

export interface FormState {
  place: string
  time: string
  metric: string
  map_type: string
  method: string
  n: number
  palette_scheme: string
  palette_reverse: boolean
  // T25：buffer / overlay 专用参数
  buffer_km: string
  overlay_op: string
}

// 指标选项分三组：空气质量（quotsoft 站点）、社会经济统计（聚汇榜单 / 预置
// 数据集）、以及任意其它指标名（统计接口会动态搜索榜单 slug）。
// 表单值直接作为 metric 提交，后端 `map_metric` + `resolve_metric_slug` 负责归一。
export const FIELD_OPTIONS = [
  // 空气质量
  'PM2_5_24h',
  'PM10_24h',
  'NO2_24h',
  'SO2_24h',
  'O3_8h_24h',
  'CO_24h',
  'AQI',
  // 社会经济统计（省级走免费榜单；市级需积分，界面会先确认）
  'GDP',
  '人均GDP',
  '人口',
  '城镇化率',
  '财政收入',
  '财政支出',
  '税收收入',
  '进出口总额',
  '城镇居民可支配收入',
  '医院床位数',
  '小学生数量',
  '初中生数量',
  'CPI',
]

export const MAP_TYPES = ['choropleth', 'point', 'idw', 'buffer', 'overlay']

export const METHODS = ['quantile', 'jenks', 'equal_interval', 'custom']

export const PALETTES = [
  'YlOrRd',
  'YlGnBu',
  'OrRd',
  'BuPu',
  'PuBu',
  'Greens',
  'Blues',
  'Reds',
  'Oranges',
  'Purples',
]