<script setup lang="ts">
import { reactive, ref } from 'vue'
import { confirmCrs as confirmCrsApi, streamPost, uploadFile } from '../api'
import type { CrsRequired, FormState, ResultPayload, UploadInfo } from '../types'
import { FIELD_OPTIONS, MAP_TYPES, METHODS, PALETTES } from '../types'
import CrsDialog from './CrsDialog.vue'
import ResultCard from './ResultCard.vue'

defineProps<{ llmConfigured: boolean }>()

const form = reactive<FormState>({
  place: '徐州',
  time: '20261101',
  metric: 'PM2_5_24h',
  map_type: 'choropleth',
  method: 'quantile',
  n: 5,
  palette_scheme: 'YlOrRd',
  palette_reverse: false,
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

async function submit(): Promise<void> {
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
      { ...form, upload_id: attachment.value?.upload_id || null },
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
          <label>区域（默认徐州）</label>
          <input v-model="form.place" />
        </div>
        <div class="field">
          <label>日期 YYYYMMDD</label>
          <input v-model="form.time" />
        </div>

        <div class="field">
          <label>指标字段</label>
          <select v-model="form.metric">
            <option v-for="option in FIELD_OPTIONS" :key="option" :value="option">{{ option }}</option>
          </select>
        </div>
        <div class="field">
          <label>图种</label>
          <select v-model="form.map_type">
            <option v-for="option in MAP_TYPES" :key="option" :value="option">{{ option }}</option>
          </select>
        </div>

        <div class="field">
          <label>分级方法</label>
          <select v-model="form.method">
            <option v-for="option in METHODS" :key="option" :value="option">{{ option }}</option>
          </select>
        </div>
        <div class="field">
          <label>级数：{{ form.n }}</label>
          <input v-model.number="form.n" type="range" min="2" max="9" step="1" />
        </div>

        <div class="field">
          <label>配色方案</label>
          <select v-model="form.palette_scheme">
            <option v-for="option in PALETTES" :key="option" :value="option">{{ option }}</option>
          </select>
        </div>
        <div class="field">
          <label>数据文件（可选）</label>
          <button class="btn ghost" :disabled="busy" @click="fileInput?.click()">
            {{ attachment ? `已选 ${attachment.name}` : '上传 CSV / GeoJSON / zip' }}
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
      <p class="hint">buffer / overlay 尚未实现，暂不支持（待 SPEC 决策）。</p>

      <div class="form-actions">
        <button class="btn primary" :disabled="busy" @click="submit">生成地图</button>
        <span v-if="stage" class="stage"><span class="spinner"></span>{{ stage }}</span>
      </div>

      <div v-if="error" class="error">{{ error }}</div>
      <ResultCard v-if="result" :result="result" />
    </div>

    <CrsDialog :info="pendingCrs" @confirm="confirmCrs" @cancel="pendingCrs = null" />
  </div>
</template>