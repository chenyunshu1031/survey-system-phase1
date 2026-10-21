<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { RouterLink, useRoute } from 'vue-router'
import { api } from '../api/client'
import type { QuestionStatistics, Survey, SurveyStatistics } from '../api/types'
import { formatBeijingDisplay } from '../utils/beijingTime'

const surveyId = String(useRoute().params.id)
const survey = ref<Survey | null>(null)
const results = ref<SurveyStatistics | null>(null)
const selectedQuestionId = ref('')
const loading = ref(true)
const error = ref('')
const loadingMore = ref<string | null>(null)
const moreError = ref<{ questionId: string; message: string } | null>(null)
const visibleQuestions = computed(() => selectedQuestionId.value
  ? (results.value?.questions || []).filter((question) => question.id === selectedQuestionId.value)
  : results.value?.questions || [])
const typeLabel = { single: '单选题', multiple: '多选题', text: '文本填空', number: '数字填空' }

function percentage(count: number, answered: number): number {
  return answered ? Math.round(count / answered * 100) : 0
}

function numberDisplay(value: number): string {
  return Number.isInteger(value) ? String(value) : String(Math.round(value * 100) / 100)
}

function choiceQuestion(question: QuestionStatistics): boolean {
  return question.type === 'single' || question.type === 'multiple'
}

async function refresh() {
  loading.value = true
  error.value = ''
  try {
    const [surveyResult, statisticsResult] = await Promise.all([
      api<Survey>(`/surveys/${surveyId}`),
      api<SurveyStatistics>(`/surveys/${surveyId}/statistics`),
    ])
    survey.value = surveyResult
    results.value = statisticsResult
  } catch (reason) {
    error.value = reason instanceof Error ? reason.message : '读取统计结果失败'
  } finally { loading.value = false }
}

async function loadMore(question: QuestionStatistics) {
  if (!results.value || loadingMore.value || loading.value) return
  const currentResults = results.value
  loadingMore.value = question.id
  moreError.value = null
  try {
    const offset = question.entries?.length || 0
    const snapshot = encodeURIComponent(currentResults.asOf)
    const page = await api<{ question: QuestionStatistics }>(
      `/surveys/${surveyId}/statistics/questions/${question.id}?offset=${offset}&limit=100&asOf=${snapshot}&submissionRevision=${currentResults.submissionRevision}`,
    )
    if (results.value !== currentResults) return
    results.value = {
      ...results.value,
      questions: results.value.questions.map((item) => item.id === question.id ? {
        ...item,
        entries: [...(item.entries || []), ...(page.question.entries || [])],
        hasMoreEntries: page.question.hasMoreEntries,
      } : item),
    }
  } catch (reason) {
    if (results.value === currentResults) moreError.value = { questionId: question.id, message: reason instanceof Error ? reason.message : '读取更多内容失败' }
  } finally { loadingMore.value = null }
}

onMounted(() => { void refresh() })
</script>

<template>
  <div class="page-container results-page">
    <RouterLink class="back-link" :to="`/surveys/${surveyId}/edit`">← 返回问卷管理</RouterLink>
    <p v-if="loading" class="card empty-card">正在统计答卷…</p>
    <p v-else-if="error" class="form-error" role="alert">{{ error }}</p>
    <template v-else-if="survey && results">
      <section class="page-heading results-heading">
        <div><span class="eyebrow">SURVEY RESULTS</span><h1>{{ survey.title }}</h1><p>统计根据已提交的答卷实时计算。</p></div>
        <div class="heading-count"><strong>{{ results.responseCount }}</strong><span>份答卷</span></div>
      </section>
      <div class="results-toolbar card">
        <label>查看范围
          <select v-model="selectedQuestionId" aria-label="选择要查看统计的题目">
            <option value="">整份问卷</option>
            <option v-for="question in results.questions" :key="question.id" :value="question.id">第 {{ question.order }} 题 · {{ question.title }}</option>
          </select>
        </label>
        <button class="button button-outline" type="button" @click="refresh">刷新统计</button>
      </div>
      <p class="results-explainer">“到达本题”包含未作答者；“回答本题”只统计有效答案。跳转时被跳过的题不计入到达或回答人数。</p>
      <div v-if="results.questions.length === 0" class="card empty-card">这份问卷还没有题目。</div>
      <div v-else class="results-list">
        <article v-for="question in visibleQuestions" :key="question.id" class="card result-card">
          <div class="question-meta"><span>Q{{ String(question.order).padStart(2, '0') }}</span><span>{{ typeLabel[question.type] }}</span></div>
          <h2>{{ question.title }}</h2>
          <div class="result-metrics"><span>到达本题 <strong>{{ question.reachedCount }}</strong> 人</span><span>回答本题 <strong>{{ question.answeredCount }}</strong> 人</span></div>
          <template v-if="choiceQuestion(question)">
            <p v-if="question.type === 'multiple'" class="result-hint">多选题每个选项独立计数，百分比以回答本题的人数为基数。</p>
            <div v-for="option in question.optionCounts || []" :key="option.optionId" class="result-option">
              <div class="result-option-line"><span>{{ option.label }}</span><strong>{{ option.count }} 人 · {{ percentage(option.count, question.answeredCount) }}%</strong></div>
              <div class="result-bar"><span :style="{ width: `${percentage(option.count, question.answeredCount)}%` }"></span></div>
            </div>
          </template>
          <template v-else>
            <div v-if="question.type === 'number'" class="result-average">平均值 <strong>{{ question.average === null || question.average === undefined ? '暂无平均值' : numberDisplay(question.average) }}</strong></div>
            <p v-if="!question.entries?.length" class="result-hint">暂无填写内容。</p>
            <ul v-else class="result-entries">
              <li v-for="(entry, index) in question.entries" :key="index">
                <span class="result-entry-value">{{ entry.value }}</span>
                <small>{{ entry.respondent }} · {{ formatBeijingDisplay(entry.submittedAt) }}（北京时间）</small>
              </li>
            </ul>
            <p v-if="moreError?.questionId === question.id" class="form-error" role="alert">{{ moreError.message }}</p>
            <button v-if="question.hasMoreEntries" class="button button-outline" type="button" :disabled="loadingMore !== null || loading" @click="loadMore(question)">{{ loadingMore === question.id ? '加载中…' : '加载更多填写内容' }}</button>
          </template>
        </article>
      </div>
    </template>
  </div>
</template>
