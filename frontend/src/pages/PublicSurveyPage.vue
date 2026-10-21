<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { RouterLink, useRoute, useRouter } from 'vue-router'
import { api, readToken } from '../api/client'
import type { PublicSurvey, Question, QuestionType } from '../api/types'
import { formatBeijingDisplay } from '../utils/beijingTime'
import SurveyFillForm from '../components/SurveyFillForm.vue'

const route = useRoute()
const router = useRouter()
const survey = ref<PublicSurvey | null>(null)
const questions = ref<Question[]>([])
const loading = ref(true)
const error = ref('')
const typeLabel: Record<QuestionType, string> = {
  single: '单选题', multiple: '多选题', text: '文本填空', number: '数字填空',
}

onMounted(async () => {
  try {
    const result = await api<{ survey: PublicSurvey; questions: Question[] }>(`/public/surveys/${encodeURIComponent(String(route.params.slug))}`)
    survey.value = result.survey
    questions.value = result.questions
  } catch (reason) {
    if (!readToken()) {
      await router.replace({ path: '/login', query: { next: route.fullPath } })
      return
    }
    error.value = reason instanceof Error ? reason.message : '问卷无法打开'
  } finally { loading.value = false }
})
</script>

<template>
  <div class="page-container public-page">
    <RouterLink class="back-link" to="/surveys">← 返回我的问卷</RouterLink>
    <p v-if="loading" class="card empty-card">正在读取问卷…</p>
    <p v-else-if="error" class="form-error" role="alert">{{ error }}</p>
    <template v-else-if="survey">
      <section class="page-heading"><div><span class="eyebrow">SURVEY</span><h1>{{ survey.title }}</h1><p>{{ survey.description }}</p></div></section>
      <div class="card public-status"><strong>{{ survey.availability === 'open' ? '问卷正在收集答案' : survey.availability === 'expired' ? '问卷已截止' : '问卷已关闭' }}</strong><p v-if="survey.availability === 'open'">{{ survey.hasSubmitted && !survey.allowMultipleSubmissions ? '你已提交过这份问卷。' : '请按页面提示逐题填写，完成后提交。' }}</p><p v-else>此问卷目前不能填写。</p><small v-if="survey.deadlineAt">截止时间（北京时间）：{{ formatBeijingDisplay(survey.deadlineAt) }}</small></div>
      <SurveyFillForm v-if="survey.availability === 'open' && (!survey.hasSubmitted || survey.allowMultipleSubmissions)" :survey="survey" :questions="questions" />
      <p v-else-if="survey.availability === 'open'" class="card empty-card">此账号已提交；这份问卷不允许重复填写。</p>
      <section v-else class="public-questions"><div class="list-topline"><h2>问卷题目</h2><span>共 {{ questions.length }} 题</span></div>
        <article v-for="question in questions" :key="question.id" class="card question-card"><div class="question-meta"><span>Q{{ String(question.order).padStart(2, '0') }}</span><span>{{ typeLabel[question.type] }}</span><span v-if="question.required" class="required-tag">必答</span></div><h3>{{ question.title }}</h3><ul v-if="question.options.length" class="option-preview"><li v-for="option in question.options" :key="option.id"><span class="option-circle"></span>{{ option.label }}</li></ul><p v-else class="input-preview">{{ question.type === 'number' ? '数字填空' : '文本填空' }}</p></article>
      </section>
    </template>
  </div>
</template>
