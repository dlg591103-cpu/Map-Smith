<script setup lang="ts">
import { ref } from 'vue'

const props = defineProps<{
  disabled: boolean
  attachmentName?: string | null
  placeholder?: string
}>()

const emit = defineEmits<{
  send: [text: string]
  file: [file: File]
  remove: []
}>()

const text = ref('')
const fileInput = ref<HTMLInputElement | null>(null)

function submit(): void {
  if (props.disabled) return
  const content = text.value.trim()
  if (!content) return
  emit('send', content)
  text.value = ''
  const area = document.querySelector<HTMLTextAreaElement>('.composer textarea')
  if (area) area.style.height = 'auto'
}

function onKeydown(event: KeyboardEvent): void {
  if (event.key === 'Enter' && !event.shiftKey) {
    event.preventDefault()
    submit()
  }
}

function pick(event: Event): void {
  const input = event.target as HTMLInputElement
  const file = input.files?.[0]
  if (file) emit('file', file)
  input.value = ''
}

function autoGrow(event: Event): void {
  const element = event.target as HTMLTextAreaElement
  element.style.height = 'auto'
  element.style.height = `${Math.min(element.scrollHeight, 150)}px`
}
</script>

<template>
  <div class="composer-wrap">
    <div v-if="attachmentName" class="attachments">
      <span class="attachment">📎 {{ attachmentName }}</span>
      <button class="icon-btn" title="移除附件" @click="emit('remove')">×</button>
    </div>

    <div class="composer">
      <button class="icon-btn" title="添加附件" :disabled="disabled" @click="fileInput?.click()">📎</button>
      <input
        ref="fileInput"
        type="file"
        accept=".csv,.geojson,.json,.zip"
        hidden
        @change="pick"
      />
      <textarea
        v-model="text"
        rows="1"
        :placeholder="placeholder || '给 MapSmith 发消息…'"
        :disabled="disabled"
        @keydown="onKeydown"
        @input="autoGrow"
      ></textarea>
      <button
        class="icon-btn send"
        :disabled="disabled || !text.trim()"
        title="发送"
        @click="submit"
      >
        ➤
      </button>
    </div>
  </div>
</template>