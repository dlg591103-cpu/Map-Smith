<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { createSession, deleteSession, fetchStatsBalance, health, listSessions } from './api'
import type { SessionMeta } from './types'
import ChatView from './components/ChatView.vue'
import FormView from './components/FormView.vue'
import SettingsDialog from './components/SettingsDialog.vue'

const view = ref<'chat' | 'form'>('chat')
const llmConfigured = ref(false)
// 聚汇余额：只在配置了统计数据 API Key 时显示，取数为 0 时提示「免费额度」。
const statsBalance = ref<{ configured: boolean; available?: boolean; points_balance?: number | null }>({ configured: false })
const chatKey = ref(0)
const sessions = ref<SessionMeta[]>([])
const currentSessionId = ref<string | null>(null)
const sidebarOpen = ref(false)
const settingsOpen = ref(false)
// 会话接口就绪前不渲染 ChatView，避免它先按空 ID 挂载、随后又换 ID 重载。
const sessionReady = ref(false)

/** 后端时间形如 "2026-11-18T15:30:00"，侧栏只显示「11-18 15:30」。 */
function formatTime(value: string): string {
  const text = (value || '').replace('T', ' ')
  return text.length >= 16 ? text.slice(5, 16) : text
}

async function loadSessions(): Promise<void> {
  try {
    sessions.value = await listSessions()
  } catch {
    sessions.value = []
  }
}

/** 会话接口不可用时返回 null，对话本身照常可用，只是不落历史。 */
async function startSession(): Promise<string | null> {
  try {
    return (await createSession()).id
  } catch {
    return null
  }
}

async function newChat(): Promise<void> {
  currentSessionId.value = await startSession()
  chatKey.value += 1
  view.value = 'chat'
  sidebarOpen.value = false
}

function openSession(id: string): void {
  sidebarOpen.value = false
  if (id === currentSessionId.value && view.value === 'chat') return
  currentSessionId.value = id
  chatKey.value += 1
  view.value = 'chat'
}

async function removeSession(id: string): Promise<void> {
  if (!window.confirm('删除这条历史会话？删除后无法找回。')) return
  try {
    await deleteSession(id)
  } catch {
    // 删除失败时仍然刷新列表，让用户看到真实状态
  }
  await loadSessions()
  if (id === currentSessionId.value) await newChat()
}

function switchView(next: 'chat' | 'form'): void {
  view.value = next
  sidebarOpen.value = false
}

/** 刷新模型/余额状态；设置保存后与页面加载时都会调用。 */
async function refreshStatus(): Promise<void> {
  try {
    llmConfigured.value = (await health()).llm_configured
    statsBalance.value = await fetchStatsBalance()
  } catch {
    llmConfigured.value = false
  }
}

onMounted(async () => {
  currentSessionId.value = await startSession()
  sessionReady.value = true
  await loadSessions()
  await refreshStatus()
})
</script>

<template>
  <div class="app">
    <aside class="sidebar" :class="{ open: sidebarOpen }">
      <div class="brand">Map<span>Smith</span></div>
      <button class="side-action" @click="newChat">＋ 新建对话</button>

      <div class="nav">
        <button :class="{ active: view === 'chat' }" @click="switchView('chat')">对话生成</button>
        <button :class="{ active: view === 'form' }" @click="switchView('form')">高级表单</button>
      </div>

      <div class="side-caption">最近</div>
      <div class="history">
        <div
          v-for="item in sessions"
          :key="item.id"
          class="history-item"
          :class="{ active: item.id === currentSessionId }"
          :title="item.title"
          @click="openSession(item.id)"
        >
          <div class="item-main">
            <div class="item-title">{{ item.title }}</div>
            <div class="item-time">{{ formatTime(item.updated_at) }}</div>
          </div>
          <button class="item-del" type="button" title="删除会话" @click.stop="removeSession(item.id)">
            ×
          </button>
        </div>
        <div v-if="!sessions.length" class="history-empty">暂无对话</div>
      </div>

      <div class="hint">模型：{{ llmConfigured ? '已配置' : '未配置' }}</div>
      <div v-if="statsBalance.configured" class="hint">
        数据积分：{{ statsBalance.available ? (statsBalance.points_balance ?? 0) : '—' }}
      </div>
      <button class="side-action side-settings" @click="settingsOpen = true">⚙ 设置 API</button>
    </aside>

    <main class="main">
      <div class="topbar">
        <button class="mobile-toggle" @click="sidebarOpen = !sidebarOpen">☰</button>
        <strong>MapSmith</strong>
      </div>

      <ChatView
        v-if="view === 'chat' && sessionReady"
        :key="chatKey"
        :llm-configured="llmConfigured"
        :session-id="currentSessionId"
        @sessions-changed="loadSessions"
      />
      <FormView v-else-if="view === 'form'" :llm-configured="llmConfigured" />
    </main>

    <SettingsDialog
      :open="settingsOpen"
      @close="settingsOpen = false"
      @saved="refreshStatus"
    />
  </div>
</template>