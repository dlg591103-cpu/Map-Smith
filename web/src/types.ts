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

export interface FormState {
  place: string
  time: string
  metric: string
  map_type: string
  method: string
  n: number
  palette_scheme: string
  palette_reverse: boolean
}

export const FIELD_OPTIONS = [
  'PM2_5_24h',
  'PM10_24h',
  'NO2_24h',
  'SO2_24h',
  'O3_8h_24h',
  'CO_24h',
  'AQI',
]

export const MAP_TYPES = ['choropleth', 'point', 'idw']

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