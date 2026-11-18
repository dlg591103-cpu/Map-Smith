<script setup lang="ts">
import { nextTick, onMounted, reactive, ref, watch } from 'vue'
import { confirmCrs as confirmCrsApi, getSession, saveSession, streamPost, uploadFile } from '../api'
import type { CrsRequired, Message, ResultPayload, UploadInfo } from '../types'
import Composer from './Composer.vue'
import CrsDialog from './CrsDialog.vue'
import MessageBubble from './MessageBubble.vue'

const props = defineProps<{ llmConfigured: boolean; sessionId: string | null }>()
const emit = defineEmits<{ sessionsChanged: [] }>()

const messages = ref<Message[]>([])
const busy = ref(false)
const attachment = ref<UploadInfo | null>(null)
const pendingCrs = ref<CrsRequired | null>(null)
const listRef = ref<HTMLElement | null>(null)
const lastRequest = ref<{ message: string; uploadId: string | null } | null>(null)
// 追问期间累积的用户原话。后端把这些拼进解析上下文，避免「说了徐州又让说徐州」
// 的死循环；出图成功或新建对话时清空。
const pendingContext = ref<string[]>([])
// 历史会话防抖保存：只在内容确实变化时落盘，避免加载后立刻回写一次。
let saveTimer: number | undefined
let lastSaved = ''

const suggestions = [
  '徐州 2026-11-01 的 PM2.5 分布图',
  '徐州 2026-11-01 的 AQI',
  '徐州 2026-11-01 的 PM10 点图',
]

function newId(): string {
  if (typeof crypto !== 'undefined' && 'randomUUID' in crypto) return crypto.randomUUID()
  return `${Date.now()}-${Math.random().toString(16).slice(2)}`
}

function addMessage(role: Message['role'], text: string): Message {
  // 用 reactive 包装：SSE 回调里会通过返回的引用改 stage/result/error，
  // 若存原始对象，Vue 3 追踪不到后续属性变更，气泡会一直空白。
  const message = reactive<Message>({ id: newId(), role, text })
  messages.value.push(message)
  return message
}

function scrollToBottom(): void {
  nextTick(() => {
    const element = listRef.value
    if (element) element.scrollTop = element.scrollHeight
  })
}

/** 只落盘展示字段：stage 是本次请求的进度，恢复后没有意义。 */
function storedMessages(): Message[] {
  return messages.value.map((message) => ({
    id: message.id,
    role: message.role,
    text: message.text,
    error: message.error,
    result: message.result,
  }))
}

async function persist(): Promise<void> {
  const id = props.sessionId
  if (!id || !messages.value.length) return
  const payload = storedMessages()
  const key = JSON.stringify(payload)
  if (key === lastSaved) return
  try {
    await saveSession(id, payload)
    lastSaved = key
    emit('sessionsChanged')
  } catch {
    // 保存失败不打断对话：下一次消息变化还会再试。
  }
}

function scheduleSave(): void {
  if (!props.sessionId || !messages.value.length) return
  window.clearTimeout(saveTimer)
  saveTimer = window.setTimeout(() => void persist(), 600)
}

/** 恢复会话时重建追问上下文：最后一条助手消息仍在提问时，
 * 此前的用户原话要一并交给后端，否则重启后又得从头问一遍。 */
function contextFrom(loaded: Message[]): string[] {
  const last = [...loaded].reverse().find((message) => message.role === 'assistant')
  if (!last?.result?.questions?.length) return []
  return loaded
    .filter((message) => message.role === 'user')
    .map((message) => String(message.text || '').split('\n📎')[0].trim())
    .filter(Boolean)
    .slice(-4)
}

async function loadSession(id: string): Promise<void> {
  // 刚新建、还没落盘的会话会拿到 404，按空对话处理即可。
  const data = await getSession(id).catch(() => null)
  if (!data || !data.messages.length) return
  messages.value = data.messages.map((item) =>
    reactive<Message>({
      id: item.id || newId(),
      role: item.role,
      text: item.text || '',
      error: item.error,
      result: item.result,
    }),
  )
  pendingContext.value = contextFrom(data.messages)
  lastSaved = JSON.stringify(storedMessages())
  scrollToBottom()
}

function crsInfo(upload: UploadInfo): CrsRequired {
  const suggested = upload.suggested_crs || 'EPSG:4326'
  return {
    upload_id: upload.upload_id,
    name: upload.name,
    suggested,
    options: Array.from(new Set([suggested, 'EPSG:4490', 'EPSG:4326'])),
  }
}

async function handleFile(file: File): Promise<void> {
  if (busy.value) return
  busy.value = true
  try {
    const info = await uploadFile(file)
    attachment.value = info
    if (info.crs_status === 'missing') pendingCrs.value = crsInfo(info)
  } catch (error) {
    const assistant = addMessage('assistant', '')
    assistant.error = error instanceof Error ? error.message : String(error)
  } finally {
    busy.value = false
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
    if (lastRequest.value && lastRequest.value.uploadId === info.upload_id) {
      const retry = lastRequest.value
      lastRequest.value = null
      await send(retry.message, retry.uploadId)
    }
  } catch (error) {
    addMessage('assistant', '').error = error instanceof Error ? error.message : String(error)
    pendingCrs.value = null
  }
}

async function send(text: string, uploadIdOverride?: string | null): Promise<void> {
  if (busy.value) return
  if (attachment.value?.crs_status === 'missing' && uploadIdOverride === undefined) {
    pendingCrs.value = crsInfo(attachment.value)
    return
  }

  const content = text.trim()
  if (!content) return

  const uploadId = uploadIdOverride !== undefined ? uploadIdOverride : attachment.value?.upload_id || null
  const attachmentName = attachment.value && uploadId === attachment.value.upload_id ? attachment.value.name : ''
  addMessage('user', attachmentName ? `${content}\n📎 ${attachmentName}` : content)
  const assistant = addMessage('assistant', '')
  busy.value = true
  lastRequest.value = { message: content, uploadId: uploadId || null }

  // 带着追问上下文发送：上一轮是追问时，把之前说过的话一起交给后端。
  const history = [...pendingContext.value]

  try {
    await streamPost('/api/chat', { message: content, history, upload_id: uploadId }, (event, data) => {
      if (event === 'stage') {
        assistant.stage = String(data.label || data.stage || '处理中')
      } else if (event === 'crs_required') {
        assistant.stage = undefined
        const info = data as unknown as CrsRequired
        pendingCrs.value = info
        lastRequest.value = { message: content, uploadId: info.upload_id }
        busy.value = false
      } else if (event === 'result') {
        assistant.stage = undefined
        const payload = data as unknown as ResultPayload
        assistant.result = payload
        // 仍在追问：把这次的原话攒进上下文，下一轮一起发送；否则话题结束，清空。
        if (payload.questions && payload.questions.length > 0) {
          pendingContext.value = [...history, content]
        } else {
          pendingContext.value = []
        }
      } else if (event === 'error') {
        assistant.stage = undefined
        assistant.error = String(data.message || '请求失败')
        pendingContext.value = []
      } else if (event === 'done') {
        assistant.stage = undefined
        busy.value = false
      }
      scrollToBottom()
    })
  } catch (error) {
    assistant.error = error instanceof Error ? error.message : String(error)
  } finally {
    assistant.stage = undefined
    busy.value = false
    attachment.value = null
    scheduleSave()
    scrollToBottom()
  }
}

function removeAttachment(): void {
  attachment.value = null
  lastRequest.value = null
}

watch(messages, scrollToBottom, { deep: true })
// 一轮结束后才写盘：busy 期间消息还在流式变化，存中间态没有意义。
watch(
  messages,
  () => {
    if (!busy.value) scheduleSave()
  },
  { deep: true },
)
// 切换会话时组件会被重建，按目标 ID 载入历史；刚新建的空会话 404 视为空对话。
watch(
  () => props.sessionId,
  (id) => {
    if (id) void loadSession(id)
  },
  { immediate: true },
)

onMounted(() => {
  scrollToBottom()
})
</script>

<template>
  <div class="view">
    <div ref="listRef" class="view-scroll">
      <div class="chat">
        <div v-if="!messages.length" class="hero">
          <h1>今天想做什么图？</h1>
          <p>用一句话告诉我区域、时间和指标，也可以点附件上传自己的点数据或面数据。</p>
          <div class="suggestions">
            <button v-for="item in suggestions" :key="item" class="suggestion" @click="send(item)">
              {{ item }}
            </button>
          </div>
        </div>

        <MessageBubble v-for="message in messages" :key="message.id" :message="message" />
      </div>
    </div>

    <div v-if="!llmConfigured" class="hint" style="text-align: center; padding-bottom: 6px">
      未配置模型：请设置 MAPSMITH_LLM_BASE_URL / MAPSMITH_LLM_API_KEY / MAPSMITH_LLM_MODEL，或在「高级表单」中出图。
    </div>

    <Composer
      :disabled="busy || !llmConfigured"
      :attachment-name="attachment?.name || null"
      @send="send"
      @file="handleFile"
      @remove="removeAttachment"
    />

    <CrsDialog :info="pendingCrs" @confirm="confirmCrs" @cancel="pendingCrs = null" />
  </div>
</template>