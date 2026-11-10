<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { health } from './api'
import ChatView from './components/ChatView.vue'
import FormView from './components/FormView.vue'

const view = ref<'chat' | 'form'>('chat')
const llmConfigured = ref(false)
const chatKey = ref(0)
const history = ref<string[]>([])
const sidebarOpen = ref(false)

function loadHistory(): void {
  try {
    history.value = JSON.parse(sessionStorage.getItem('mapsmith_history') || '[]') as string[]
  } catch {
    history.value = []
  }
}

function newChat(): void {
  chatKey.value += 1
  sessionStorage.removeItem('mapsmith_history')
  history.value = []
  view.value = 'chat'
  sidebarOpen.value = false
}

function switchView(next: 'chat' | 'form'): void {
  view.value = next
  sidebarOpen.value = false
}

onMounted(async () => {
  loadHistory()
  try {
    llmConfigured.value = (await health()).llm_configured
  } catch {
    llmConfigured.value = false
  }
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
        <div v-for="(item, index) in history.slice().reverse()" :key="index" class="history-item">
          {{ item }}
        </div>
        <div v-if="!history.length" class="history-item">暂无对话</div>
      </div>

      <div class="hint">模型：{{ llmConfigured ? '已配置' : '未配置' }}</div>
    </aside>

    <main class="main">
      <div class="topbar">
        <button class="mobile-toggle" @click="sidebarOpen = !sidebarOpen">☰</button>
        <strong>MapSmith</strong>
      </div>

      <ChatView
        v-if="view === 'chat'"
        :key="chatKey"
        :llm-configured="llmConfigured"
        @history-changed="loadHistory"
      />
      <FormView v-else :llm-configured="llmConfigured" />
    </main>
  </div>
</template>