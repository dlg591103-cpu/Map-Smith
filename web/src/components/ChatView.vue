<script setup lang="ts">
import { nextTick, onMounted, ref, watch } from 'vue'
import { confirmCrs as confirmCrsApi, streamPost, uploadFile } from '../api'
import type { CrsRequired, Message, ResultPayload, UploadInfo } from '../types'
import Composer from './Composer.vue'
import CrsDialog from './CrsDialog.vue'
import MessageBubble from './MessageBubble.vue'

defineProps<{ llmConfigured: boolean }>()
const emit = defineEmits<{ historyChanged: [] }>()

const messages = ref<Message[]>([])
const busy = ref(false)
const attachment = ref<UploadInfo | null>(null)
const pendingCrs = ref<CrsRequired | null>(null)
const listRef = ref<HTMLElement | null>(null)
const lastRequest = ref<{ message: string; uploadId: string | null } | null>(null)

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
  const message: Message = { id: newId(), role, text }
  messages.value.push(message)
  return message
}

function scrollToBottom(): void {
  nextTick(() => {
    const element = listRef.value
    if (element) element.scrollTop = element.scrollHeight
  })
}

function saveHistory(): void {
  const recent = messages.value
    .filter((message) => message.role === 'user')
    .map((message) => message.text)
    .slice(-20)
  sessionStorage.setItem('mapsmith_history', JSON.stringify(recent))
  emit('historyChanged')
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

  try {
    await streamPost('/api/chat', { message: content, upload_id: uploadId }, (event, data) => {
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
        assistant.result = data as unknown as ResultPayload
      } else if (event === 'error') {
        assistant.stage = undefined
        assistant.error = String(data.message || '请求失败')
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
    saveHistory()
    scrollToBottom()
  }
}

function removeAttachment(): void {
  attachment.value = null
  lastRequest.value = null
}

watch(messages, scrollToBottom, { deep: true })

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