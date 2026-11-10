<script setup lang="ts">
import type { ResultPayload } from '../types'

const props = defineProps<{ result: ResultPayload }>()

function statusClass(): string {
  if (props.result.status === 'rendered') return 'ok'
  if (props.result.status === 'needs_input') return 'warn'
  return 'bad'
}

function statusText(): string {
  if (props.result.status === 'rendered') return '已出图'
  if (props.result.status === 'needs_input') return '需要补充'
  return '未完成'
}

function reviewText(): string {
  const review = props.result.review
  if (review && review.summary) return review.summary
  return props.result.summary
}

function hasIssues(): boolean {
  return Boolean(props.result.review && props.result.review.issues && props.result.review.issues.length)
}
</script>

<template>
  <div v-if="result.status === 'needs_input'" class="questions">
    <p>需要先补充：</p>
    <ul>
      <li v-for="(question, index) in result.questions" :key="index">{{ question }}</li>
    </ul>
    <p v-if="!result.questions.length" class="hint">{{ result.summary }}</p>
  </div>

  <div v-else class="result">
    <div class="result-title">
      <span class="badge" :class="statusClass()">{{ statusText() }}</span>
      <span v-if="result.round_no">第 {{ result.round_no }} 轮审查</span>
      <span v-if="result.decision"> · {{ result.decision }}</span>
      <span v-if="result.elapsed"> · {{ result.elapsed.toFixed(1) }} 秒</span>
    </div>

    <img v-if="result.png" :src="result.png" alt="地图预览" />

    <div class="result-actions">
      <a v-if="result.png" class="btn ghost" :href="result.png" download>下载 PNG</a>
      <a v-if="result.pdf" class="btn ghost" :href="result.pdf" download>下载 PDF</a>
    </div>

    <div class="review" :class="{ fail: result.status === 'failed' }">{{ reviewText() }}</div>

    <details v-if="hasIssues()">
      <summary>审查意见（{{ result.review?.issues?.length }} 条）</summary>
      <ul class="notes">
        <li v-for="issue in result.review?.issues" :key="issue.rule">
          <strong>{{ issue.rule }}</strong> · {{ issue.message }}
        </li>
      </ul>
    </details>

    <details v-if="result.notes.length">
      <summary>制图说明（{{ result.notes.length }} 条）</summary>
      <ul class="notes">
        <li v-for="(note, index) in result.notes" :key="index">{{ note }}</li>
      </ul>
    </details>

    <details v-if="result.spec">
      <summary>查看 MapSpec</summary>
      <pre>{{ JSON.stringify(result.spec, null, 2) }}</pre>
    </details>
  </div>
</template>