<script setup lang="ts">
import type { Message } from '../types'
import ResultCard from './ResultCard.vue'

defineProps<{ message: Message }>()
</script>

<template>
  <div v-if="message.role === 'user'" class="message user">
    <div class="bubble user">{{ message.text }}</div>
  </div>

  <div v-else class="message assistant">
    <div class="avatar">🗺️</div>
    <div class="assistant-body">
      <div v-if="message.stage" class="stage"><span class="spinner"></span>{{ message.stage }}</div>
      <div v-if="message.text" class="assistant-text">{{ message.text }}</div>
      <div v-if="message.error" class="error">{{ message.error }}</div>
      <ResultCard v-if="message.result" :result="message.result" />
    </div>
  </div>
</template>