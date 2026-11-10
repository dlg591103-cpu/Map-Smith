<script setup lang="ts">
import { ref, watch } from 'vue'
import type { CrsRequired } from '../types'

const props = defineProps<{ info: CrsRequired | null }>()
const emit = defineEmits<{ confirm: [crs: string]; cancel: [] }>()

const choice = ref('EPSG:4326')

watch(
  () => props.info,
  (value) => {
    choice.value = value?.suggested || 'EPSG:4326'
  },
  { immediate: true },
)
</script>

<template>
  <div v-if="info" class="overlay">
    <div class="dialog">
      <h3>确认坐标系</h3>
      <p>文件「{{ info.name }}」未声明坐标系，请选择后继续。未确认不会生效，也不会按默认值静默处理。</p>
      <select v-model="choice">
        <option v-for="option in info.options" :key="option" :value="option">{{ option }}</option>
      </select>
      <div class="dialog-actions">
        <button class="btn ghost" @click="emit('cancel')">取消</button>
        <button class="btn primary" @click="emit('confirm', choice)">确认并继续</button>
      </div>
    </div>
  </div>
</template>