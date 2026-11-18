<script setup lang="ts">
import { reactive, ref, watch } from 'vue'
import { fetchSettings, saveSettings } from '../api'
import type { SettingsInfo, SettingsPatch } from '../types'

const props = defineProps<{ open: boolean }>()
const emit = defineEmits<{ close: []; saved: [] }>()

const loading = ref(false)
const saving = ref(false)
const error = ref('')
const saved = ref(false)
const info = ref<SettingsInfo | null>(null)

const form = reactive({
  llm_base_url: '',
  llm_model: '',
  llm_api_key: '',
  stats_api_key: '',
})

async function load(): Promise<void> {
  loading.value = true
  error.value = ''
  saved.value = false
  try {
    info.value = await fetchSettings()
    form.llm_base_url = info.value.llm.base_url
    form.llm_model = info.value.llm.model
    // 密钥永远不回显：留空 = 保持不变，输入新值 = 覆盖。
    form.llm_api_key = ''
    form.stats_api_key = ''
  } catch (err) {
    error.value = err instanceof Error ? err.message : String(err)
  } finally {
    loading.value = false
  }
}

async function save(): Promise<void> {
  if (saving.value) return
  saving.value = true
  error.value = ''
  saved.value = false
  try {
    const patch: SettingsPatch = {}
    if (form.llm_base_url.trim()) patch.llm_base_url = form.llm_base_url.trim()
    if (form.llm_model.trim()) patch.llm_model = form.llm_model.trim()
    if (form.llm_api_key.trim()) patch.llm_api_key = form.llm_api_key.trim()
    if (form.stats_api_key.trim()) patch.stats_api_key = form.stats_api_key.trim()

    info.value = await saveSettings(patch)
    form.llm_api_key = ''
    form.stats_api_key = ''
    saved.value = true
    emit('saved')
  } catch (err) {
    error.value = err instanceof Error ? err.message : String(err)
  } finally {
    saving.value = false
  }
}

watch(
  () => props.open,
  (open) => {
    if (open) void load()
  },
)
</script>

<template>
  <div v-if="open" class="overlay" @click.self="emit('close')">
    <div class="dialog settings-dialog">
      <div class="dialog-head">
        <h3>API 配置</h3>
        <button class="dialog-close" type="button" aria-label="关闭" @click="emit('close')">×</button>
      </div>
      <p class="dialog-sub">
        密钥只保存在本机 <code>.env</code> 文件，不回显完整值、不写入日志。留空的字段保持原值不变。
      </p>

      <div v-if="loading" class="hint">读取配置中…</div>

      <template v-else>
        <section class="settings-group">
          <h4>对话模型（LLM）</h4>
          <p class="group-tip">
            两条路选一：本机已装 <strong>Ollama</strong> 就保持默认地址（密钥随便填个非空值）；
            用 <strong>DeepSeek / OpenAI 等云端服务</strong> 则改地址、填真实密钥、填对应模型名。
          </p>
          <label class="field-label" for="s-llm-url">API 地址</label>
          <input
            id="s-llm-url"
            v-model="form.llm_base_url"
            type="text"
            placeholder="https://api.deepseek.com/v1"
          />

          <label class="field-label" for="s-llm-model">模型名</label>
          <input id="s-llm-model" v-model="form.llm_model" type="text" placeholder="deepseek-chat" />

          <label class="field-label" for="s-llm-key">密钥</label>
          <input
            id="s-llm-key"
            v-model="form.llm_api_key"
            type="password"
            autocomplete="new-password"
            :placeholder="info?.llm.api_key_configured ? `已配置 ${info?.llm.api_key_masked}，留空保持不变` : '尚未配置，请粘贴密钥'"
          />
        </section>

        <section class="settings-group">
          <h4>统计数据（聚汇）</h4>
          <p class="group-tip">
            不填也能出空气质量图；要画 GDP、人口等统计图才需要。到
            <a href="https://www.gotohui.com/member/api-keys" target="_blank" rel="noopener">gotohui.com</a> 注册后创建。
          </p>
          <label class="field-label" for="s-stats-key">API Key</label>
          <input
            id="s-stats-key"
            v-model="form.stats_api_key"
            type="password"
            autocomplete="new-password"
            :placeholder="info?.stats.api_key_configured ? `已配置 ${info?.stats.api_key_masked}，留空保持不变` : '尚未配置，请粘贴 API Key'"
          />
        </section>

        <p v-if="saved" class="saved-note">✓ 已保存并立即生效</p>
        <p v-if="error" class="error">{{ error }}</p>

        <div class="dialog-actions">
          <button class="btn ghost" type="button" @click="emit('close')">关闭</button>
          <button class="btn primary" type="button" :disabled="saving" @click="save">
            {{ saving ? '保存中…' : '保存' }}
          </button>
        </div>
      </template>
    </div>
  </div>
</template>
