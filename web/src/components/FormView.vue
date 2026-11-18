<script setup lang="ts">
import { computed, reactive, ref } from 'vue'
import { confirmCrs as confirmCrsApi, streamPost, uploadFile } from '../api'
import type { CrsRequired, FormState, OptionItem, ResultPayload, UploadInfo } from '../types'
import {
  FIELD_OPTIONS,
  MAP_TYPE_OPTIONS,
  METRIC_LABELS,
  METHOD_OPTIONS,
  N_HINT,
  OVERLAY_OPTIONS,
  PALETTE_OPTIONS,
} from '../types'
import CrsDialog from './CrsDialog.vue'
import ResultCard from './ResultCard.vue'

defineProps<{ llmConfigured: boolean }>()

/** 选项里的中文说明：给一个 value 找到它的 hint。 */
function hintOf(options: OptionItem[], value: string): string {
  return options.find((item) => item.value === value)?.hint || ''
}

/** 空气质量字段名（PM2_5_24h）对非专业用户不友好，下拉里显示中文名。 */
function metricLabel(value: string): string {
  return METRIC_LABELS[value] || value
}

const form = reactive<FormState>({
  place: '徐州',
  time: '20261101',
  metric: 'PM2_5_24h',
  map_type: 'choropleth',
  method: 'quantile',
  n: 5,
  palette_scheme: 'YlOrRd',
  palette_reverse: false,
  buffer_km: '5',
  overlay_op: 'clip',
})

const busy = ref(false)
const stage = ref('')
const error = ref('')
const result = ref<ResultPayload | null>(null)
const attachment = ref<UploadInfo | null>(null)
const pendingCrs = ref<CrsRequired | null>(null)
const fileInput = ref<HTMLInputElement | null>(null)

function crsInfo(upload: UploadInfo): CrsRequired {
  const suggested = upload.suggested_crs || 'EPSG:4326'
  return {
    upload_id: upload.upload_id,
    name: upload.name,
    suggested,
    options: Array.from(new Set([suggested, 'EPSG:4490', 'EPSG:4326'])),
  }
}

async function pickFile(event: Event): Promise<void> {
  const input = event.target as HTMLInputElement
  const file = input.files?.[0]
  input.value = ''
  if (!file) return
  try {
    const info = await uploadFile(file)
    attachment.value = info
    if (info.crs_status === 'missing') pendingCrs.value = crsInfo(info)
  } catch (err) {
    error.value = err instanceof Error ? err.message : String(err)
  }
}

async function confirmCrs(crs: string): Promise<void> {
  const info = pendingCrs.value
  if (!info) return
  try {
    const updated = await confirmCrsApi(info.upload_id, crs)
    if (attachment.value?.upload_id === info.upload_id) {
      attachment.value = { ...attachment.value, crs_status: updated.crs_status }
    }
    pendingCrs.value = null
  } catch (err) {
    error.value = err instanceof Error ? err.message : String(err)
    pendingCrs.value = null
  }
}

/** 表单结果里「要花积分确认」的追问；有值时显示确认条。 */
const costQuestion = computed(() => {
  const questions = result.value?.questions || []
  return questions.find((item) => String(item).includes('积分')) || ''
})

/** 余额不足时按钮改为「去充值」，避免反复点确认也买不到。 */
const costShort = computed(() => costQuestion.value.includes('余额不足'))

function openRecharge(): void {
  window.open('https://www.gotohui.com/member/recharge', '_blank', 'noopener')
}
async function submit(confirmCost = false): Promise<void> {
  if (busy.value) return
  if (attachment.value?.crs_status === 'missing') {
    pendingCrs.value = crsInfo(attachment.value)
    return
  }

  busy.value = true
  stage.value = ''
  error.value = ''
  result.value = null

  try {
    await streamPost(
      '/api/form',
      { ...form, upload_id: attachment.value?.upload_id || null, confirm_cost: confirmCost },
      (event, data) => {
        if (event === 'stage') stage.value = String(data.label || data.stage || '处理中')
        else if (event === 'result') result.value = data as unknown as ResultPayload
        else if (event === 'error') error.value = String(data.message || '请求失败')
        else if (event === 'crs_required') pendingCrs.value = data as unknown as CrsRequired
        else if (event === 'done') {
          stage.value = ''
          busy.value = false
        }
      },
    )
  } catch (err) {
    error.value = err instanceof Error ? err.message : String(err)
  } finally {
    busy.value = false
    stage.value = ''
  }
}
</script>

<template>
  <div class="view view-scroll">
    <div class="form-page">
      <h1>高级表单</h1>
      <p class="lead">手动指定区域、时间、指标与图种；提交同样经过 loop.run 与审查。</p>

      <div class="form-grid">
        <div class="field">
          <label>区域</label>
          <input v-model="form.place" placeholder="如 徐州市 / 江苏省" />
        </div>
        <div class="field">
          <label>日期 / 年份</label>
          <input v-model="form.time" placeholder="20261101 或 2025" />
        </div>

        <div class="field">
          <label>指标</label>
          <select v-model="form.metric">
            <option v-for="option in FIELD_OPTIONS" :key="option" :value="option">
              {{ metricLabel(option) }}
            </option>
          </select>
        </div>
        <div class="field">
          <label>图种</label>
          <select v-model="form.map_type">
            <option v-for="option in MAP_TYPE_OPTIONS" :key="option.value" :value="option.value">
              {{ option.label }}
            </option>
          </select>
          <p class="hint">{{ hintOf(MAP_TYPE_OPTIONS, form.map_type) }}</p>
        </div>

        <div v-if="form.map_type === 'buffer'" class="field">
          <label>缓冲距离（公里）</label>
          <input v-model="form.buffer_km" type="number" min="0.1" max="200" step="0.5" />
        </div>
        <div v-if="form.map_type === 'overlay'" class="field">
          <label>叠加方式</label>
          <select v-model="form.overlay_op">
            <option v-for="option in OVERLAY_OPTIONS" :key="option.value" :value="option.value">
              {{ option.label }}
            </option>
          </select>
        </div>

        <div class="field">
          <label>分级方法</label>
          <select v-model="form.method">
            <option v-for="option in METHOD_OPTIONS" :key="option.value" :value="option.value">
              {{ option.label }}
            </option>
          </select>
          <p class="hint">{{ hintOf(METHOD_OPTIONS, form.method) }}</p>
        </div>
        <div class="field">
          <label>级数：{{ form.n }} 级</label>
          <input v-model.number="form.n" type="range" min="2" max="9" step="1" />
          <p class="hint">{{ N_HINT }}</p>
        </div>

        <div class="field">
          <label>配色方案</label>
          <select v-model="form.palette_scheme">
            <option v-for="option in PALETTE_OPTIONS" :key="option.value" :value="option.value">
              {{ option.label }}
            </option>
          </select>
          <p class="hint">{{ hintOf(PALETTE_OPTIONS, form.palette_scheme) }}</p>
        </div>
        <div class="field">
          <label>数据文件</label>
          <button class="btn ghost" :disabled="busy" @click="fileInput?.click()">
            {{ attachment ? `已选 ${attachment.name}` : '上传 CSV / GeoJSON / zip（可选）' }}
          </button>
          <input
            ref="fileInput"
            type="file"
            accept=".csv,.geojson,.json,.zip"
            hidden
            @change="pickFile"
          />
        </div>
      </div>

      <label class="checkline">
        <input v-model="form.palette_reverse" type="checkbox" />
        配色反转
      </label>
      <p v-if="form.map_type === 'overlay'" class="hint">
        叠加图需要上传面图层作为主体，第二图层用所选区域的边界。
      </p>

      <div class="form-actions">
        <!-- 必须写成 submit()：@click="submit" 会把 MouseEvent 当成 confirmCost 传进去，
             导致请求体 confirm_cost 不是 boolean、被后端 422 拒绝（用户实测踩到）。 -->
        <button class="btn primary" :disabled="busy" @click="submit()">生成地图</button>
        <span v-if="stage" class="stage"><span class="spinner"></span>{{ stage }}</span>
      </div>

      <div v-if="error" class="error">{{ error }}</div>
      <div v-if="costQuestion && !busy" class="cost-confirm">
        <span class="cost-confirm-text">{{ costQuestion }}</span>
        <button
          v-if="costShort"
          class="cost-confirm-btn"
          type="button"
          @click="openRecharge"
        >
          去充值
        </button>
        <button v-else class="cost-confirm-btn" type="button" @click="submit(true)">
          确认购买
        </button>
      </div>

      <ResultCard v-if="result" :result="result" />
    </div>

    <CrsDialog :info="pendingCrs" @confirm="confirmCrs" @cancel="pendingCrs = null" />
  </div>
</template>