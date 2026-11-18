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

// API 配置（程序内设置窗口）：密钥只返回「是否配置 + 脱敏值」，绝不回传完整值。
export interface SettingsInfo {
  llm: {
    base_url: string
    model: string
    api_key_configured: boolean
    api_key_masked: string
    configured: boolean
    provider: string
  }
  stats: {
    api_key_configured: boolean
    api_key_masked: string
  }
}

export interface SettingsPatch {
  llm_base_url?: string
  llm_api_key?: string
  llm_model?: string
  stats_api_key?: string
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

// 选项对象：value 提交给后端，label 给站内人看，hint 是一句话用途说明。
// 表单单选一律显示中文 label，后端仍收英文 value，接口契约不变。
export interface OptionItem {
  value: string
  label: string
  hint: string
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

/** 指标 → 中文名（空气质量字段名对非专业用户不友好，选完在下面显示一句解释）。 */
export const METRIC_LABELS: Record<string, string> = {
  PM2_5_24h: 'PM2.5（24 小时均值）',
  PM10_24h: 'PM10（24 小时均值）',
  NO2_24h: '二氧化氮（24 小时均值）',
  SO2_24h: '二氧化硫（24 小时均值）',
  O3_8h_24h: '臭氧（8 小时滑动均值）',
  CO_24h: '一氧化碳（24 小时均值）',
  AQI: '空气质量指数 AQI',
}

export const MAP_TYPE_OPTIONS: OptionItem[] = [
  {
    value: 'choropleth',
    label: '分级设色图',
    hint: '按数值给每个区域填不同深浅的颜色，一眼看出哪个区高、哪个区低。最常用。',
  },
  {
    value: 'point',
    label: '点图 / 气泡图',
    hint: '把每个站点画成一个点，气泡越大数值越高。适合站点分布稀疏时。',
  },
  {
    value: 'idw',
    label: '插值面图（IDW）',
    hint: '用周围站点的值推算整片区域的数值，画成连续渐变。站点较密时更接近真实分布。',
  },
  {
    value: 'buffer',
    label: '缓冲区分析图',
    hint: '在每个站点周围画固定半径的圆，统计圈内情况。适合评估站点服务范围。',
  },
  {
    value: 'overlay',
    label: '叠加 / 裁剪图',
    hint: '把两层数据叠在一起，或按规定范围裁掉多余部分。适合看两类数据的关系。',
  },
]

export const METHOD_OPTIONS: OptionItem[] = [
  {
    value: 'quantile',
    label: '分位数（推荐）',
    hint: '让每一级包含的区域数量尽量相近，适合看「谁排前面」。数据有极端值时也不会被拖偏。',
  },
  {
    value: 'jenks',
    label: '自然断点',
    hint: '自动找到数值「天然分开」的位置分级，同级内部差异最小、级间差异最大。',
  },
  {
    value: 'equal_interval',
    label: '等间距',
    hint: '把数值范围平均切成几段。数据分布比较均匀时最直观，有极端值时会失衡。',
  },
  {
    value: 'custom',
    label: '自定义断点',
    hint: '自己指定每级的分界值，适合按国标或内部口径分级。',
  },
]

export const PALETTE_OPTIONS: OptionItem[] = [
  { value: 'YlOrRd', label: '黄 → 橙 → 红', hint: '数值越高颜色越深，适合高值预警（污染、拥堵）' },
  { value: 'YlGnBu', label: '黄 → 绿 → 蓝', hint: '从浅到深过渡柔和，适合作中性展示' },
  { value: 'OrRd', label: '橙 → 红', hint: '暖色系，强调高低差异' },
  { value: 'BuPu', label: '蓝 → 紫', hint: '冷色系，适合降水、湿度一类指标' },
  { value: 'PuBu', label: '紫 → 蓝', hint: '冷色系，视觉偏安静' },
  { value: 'Greens', label: '绿色系', hint: '适合植被、绿地类指标' },
  { value: 'Blues', label: '蓝色系', hint: '适合水系、降雨类指标' },
  { value: 'Reds', label: '红色系', hint: '适合高温、风险类指标' },
  { value: 'Oranges', label: '橙色系', hint: '适合日照、干旱类指标' },
  { value: 'Purples', label: '紫色系', hint: '适合人口密度、商业类指标' },
]

/** 级数说明：3 级最概括、7 级以上容易难以分辨。 */
export const N_HINT = '级数越多颜色层次越细，但超过 7 级很难分辨；一般 5 级最合适。'

export const OVERLAY_OPTIONS: OptionItem[] = [
  { value: 'clip', label: '裁剪（clip）', hint: '按范围边界把多余部分切掉' },
  { value: 'intersection', label: '相交（intersection）', hint: '只保留两层重叠的部分' },
]