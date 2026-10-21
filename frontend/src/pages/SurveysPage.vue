<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { RouterLink, useRouter } from 'vue-router'
import { api } from '../api/client'
import type { Survey } from '../api/types'
import { useAuthStore } from '../stores/auth'
import { parseBeijingInput } from '../utils/beijingTime'

const auth = useAuthStore()
const router = useRouter()
const surveys = ref<Survey[]>([])
const title = ref('')
const description = ref('')
const allowAnonymous = ref(false)
const allowMultiple = ref(false)
const deadline = ref('')
const loading = ref(true)
const pending = ref(false)
const error = ref('')
const copiedSurveyId = ref<string | null>(null)
const copyErrorSurveyId = ref<string | null>(null)

function surveyLink(survey: Survey): string {
  return new URL(`/survey/${survey.slug}`, window.location.origin).toString()
}

async function copySurveyLink(survey: Survey) {
  const url = surveyLink(survey)
  copiedSurveyId.value = null
  copyErrorSurveyId.value = null
  try {
    try {
      if (!navigator.clipboard?.writeText) throw new Error('Clipboard API unavailable')
      await navigator.clipboard.writeText(url)
    } catch {
      const field = document.createElement('textarea')
      field.value = url
      field.style.position = 'fixed'
      field.style.opacity = '0'
      document.body.appendChild(field)
      field.select()
      const copied = document.execCommand('copy')
      field.remove()
      if (!copied) throw new Error('Copy failed')
    }
    copiedSurveyId.value = survey.id
  } catch {
    copyErrorSurveyId.value = survey.id
  }
}

async function refresh() {
  loading.value = true
  try { surveys.value = await api<Survey[]>('/surveys') }
  catch (reason) { error.value = reason instanceof Error ? reason.message : '读取失败' }
  finally { loading.value = false }
}

async function createSurvey() {
  error.value = ''
  pending.value = true
  try {
    const survey = await api<Survey>('/surveys', {
      method: 'POST',
      body: JSON.stringify({
        title: title.value,
        description: description.value,
        allowAnonymous: allowAnonymous.value,
        allowMultipleSubmissions: allowMultiple.value,
        deadlineAt: deadline.value ? parseBeijingInput(deadline.value) : null,
      }),
    })
    await router.push(`/surveys/${survey.id}/edit`)
  } catch (reason) {
    error.value = reason instanceof Error ? reason.message : '创建失败'
  } finally { pending.value = false }
}

onMounted(() => { void auth.loadUser(); void refresh() })
</script>

<template>
  <div class="page-container">
    <section class="page-heading">
      <div><span class="eyebrow">YOUR WORKSPACE</span><h1>我的问卷</h1><p>从一个好问题开始，逐步构建完整的问卷。</p></div>
      <div class="heading-count"><strong>{{ surveys.length }}</strong><span>份问卷</span></div>
    </section>
    <div class="workspace-grid">
      <section class="card create-panel">
        <div class="section-heading"><span class="section-icon">＋</span><div><h2>创建新问卷</h2><p>先确定问卷的基本信息</p></div></div>
        <form class="form-stack" @submit.prevent="createSurvey">
          <label>问卷标题<input v-model="title" required maxlength="160" placeholder="例如：校园阅读习惯调查" /></label>
          <label>问卷说明<textarea v-model="description" rows="3" maxlength="2000" placeholder="告诉填写者这份问卷的目的" /></label>
          <label>截止时间 <span class="optional">可选 · 北京时间</span><input v-model="deadline" type="datetime-local" /></label>
          <label class="check-row"><input v-model="allowAnonymous" type="checkbox" /><span>允许填写者匿名展示</span></label>
          <label class="check-row"><input v-model="allowMultiple" type="checkbox" /><span>允许同一账户多次填写</span></label>
          <p v-if="error" class="form-error" role="alert">{{ error }}</p>
          <button class="button button-primary" :disabled="pending" type="submit">{{ pending ? '创建中…' : '创建问卷' }} <span aria-hidden="true">→</span></button>
        </form>
      </section>
      <section class="survey-list">
        <div class="list-topline"><h2>最近的问卷</h2><span>{{ surveys.length }} 项</span></div>
        <p v-if="loading" class="card empty-card">正在载入问卷…</p>
        <div v-else-if="surveys.length === 0" class="card empty-card"><div class="empty-illustration">✦</div><h3>这里还没有问卷</h3><p>在左侧填写基本信息，创建你的第一份问卷。</p></div>
        <div v-else class="survey-cards">
          <article v-for="survey in surveys" :key="survey.id" class="card survey-card">
            <RouterLink class="survey-card-main" :to="`/surveys/${survey.id}/edit`" :aria-label="`管理问卷：${survey.title}`">
              <div class="survey-card-top"><span class="status-badge">{{ survey.availability === 'draft' ? '未发布' : survey.availability === 'open' ? '已发布' : survey.availability === 'expired' ? '已截止' : '已关闭' }}</span><span class="arrow">↗</span></div>
              <h3>{{ survey.title }}</h3><p>{{ survey.description || '尚未添加说明' }}</p>
            </RouterLink>
            <div class="survey-card-foot"><span class="survey-url">{{ survey.status === 'draft' ? '预留地址（发布后可访问）' : '访问地址' }}<br />{{ surveyLink(survey) }}</span><button class="copy-link-button" type="button" :aria-label="`复制${survey.title}的问卷地址`" @click="copySurveyLink(survey)">复制地址</button></div>
            <RouterLink class="results-card-link" :to="`/surveys/${survey.id}/results`">查看统计结果 →</RouterLink>
            <p v-if="copiedSurveyId === survey.id" class="copy-status" role="status">{{ survey.status === 'draft' ? '预留地址已复制，发布后才能访问' : '完整访问地址已复制' }}</p>
            <p v-if="copyErrorSurveyId === survey.id" class="copy-status copy-error" role="alert">复制失败，请选中上方地址手动复制。</p>
          </article>
        </div>
      </section>
    </div>
  </div>
</template>
