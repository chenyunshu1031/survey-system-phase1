<script setup lang="ts">
import { computed, ref } from 'vue'
import { api } from '../api/client'
import type { PublicSurvey, Question } from '../api/types'
import { nextQuestionId, trimTextAnswer, validateAnswer, type AnswerValue } from '../utils/surveyAnswers'

const props = defineProps<{ survey: PublicSurvey; questions: Question[] }>()
const emit = defineEmits<{ submitted: [] }>()
const visitedIds = ref<string[]>(props.questions[0] ? [props.questions[0].id] : [])
const currentIndex = ref(0)
const answers = ref<Record<string, AnswerValue>>({})
const singleValue = ref('')
const multiValues = ref<string[]>([])
const textValue = ref('')
const numberValue = ref<string | number>('')
const isAnonymous = ref(false)
const pending = ref(false)
const error = ref('')
const submissionId = ref<string | null>(null)
const currentQuestion = computed(() => props.questions.find((item) => item.id === visitedIds.value[currentIndex.value]))
const nextId = computed(() => currentQuestion.value ? nextQuestionId(currentQuestion.value, props.questions, currentValue()) : null)

function currentValue(): AnswerValue {
  const question = currentQuestion.value
  if (!question) return null
  if (question.type === 'single') return singleValue.value || null
  if (question.type === 'multiple') return [...multiValues.value]
  if (question.type === 'text') return trimTextAnswer(textValue.value) || null
  return numberValue.value === '' ? null : Number(numberValue.value)
}

function loadAnswer(questionId: string) {
  const value = answers.value[questionId]
  singleValue.value = typeof value === 'string' ? value : ''
  multiValues.value = Array.isArray(value) ? [...value] : []
  textValue.value = typeof value === 'string' ? value : ''
  numberValue.value = typeof value === 'number' ? String(value) : ''
  error.value = ''
}

function previous() {
  const question = currentQuestion.value
  if (!question || currentIndex.value === 0) return
  answers.value[question.id] = currentValue()
  currentIndex.value -= 1
  loadAnswer(visitedIds.value[currentIndex.value]!)
}

async function advance() {
  const question = currentQuestion.value
  if (!question || pending.value) return
  try {
    const value = currentValue()
    const problem = validateAnswer(question, value)
    if (problem) { error.value = problem; return }
    error.value = ''
    answers.value[question.id] = value
    const target = nextQuestionId(question, props.questions, value)
    const currentPath = visitedIds.value.slice(0, currentIndex.value + 1)
    if (target) {
      visitedIds.value = visitedIds.value[currentIndex.value + 1] === target
        ? visitedIds.value : [...currentPath, target]
      currentIndex.value += 1
      loadAnswer(target)
      return
    }
    visitedIds.value = currentPath
    pending.value = true
    const result = await api<{ id: string }>(`/public/surveys/${encodeURIComponent(props.survey.slug)}/responses`, {
      method: 'POST',
      body: JSON.stringify({
        isAnonymous: props.survey.allowAnonymous && isAnonymous.value,
        answers: currentPath.map((id) => ({ questionId: id, value: answers.value[id] ?? null })),
      }),
    })
    submissionId.value = result.id
    emit('submitted')
  } catch (reason) {
    error.value = reason instanceof Error ? reason.message : '页面处理失败，请重试'
  } finally { pending.value = false }
}

function startAgain() {
  visitedIds.value = props.questions[0] ? [props.questions[0].id] : []
  currentIndex.value = 0
  answers.value = {}
  isAnonymous.value = false
  submissionId.value = null
  loadAnswer(visitedIds.value[0] || '')
}
</script>

<template>
  <section v-if="submissionId" class="card fill-complete" role="status">
    <span class="fill-complete-mark">✓</span>
    <h2>提交成功</h2>
    <p>你的答卷已保存。记录编号：{{ submissionId }}</p>
    <button v-if="survey.allowMultipleSubmissions" class="button button-outline" type="button" @click="startAgain">再填一次</button>
  </section>
  <form v-else-if="currentQuestion" class="card fill-card" @submit.prevent="advance">
    <div class="fill-progress"><span>第 {{ currentQuestion.order }} 题 · 共 {{ questions.length }} 题</span><span>{{ currentQuestion.type === 'single' ? '单选' : currentQuestion.type === 'multiple' ? '多选' : currentQuestion.type === 'text' ? '文字填空' : '数字填空' }}</span></div>
    <div class="fill-progress-track"><span :style="{ width: `${currentQuestion.order / questions.length * 100}%` }"></span></div>
    <div class="fill-question-heading"><h2>{{ currentQuestion.title }}</h2><span v-if="currentQuestion.required" class="required-tag">必答</span><span v-else class="optional">选答</span></div>
    <div v-if="currentQuestion.type === 'single'" class="answer-choices">
      <label v-for="option in currentQuestion.options" :key="option.id" class="answer-choice"><input v-model="singleValue" type="radio" :name="currentQuestion.id" :value="option.id" /><span>{{ option.label }}</span></label>
      <button v-if="!currentQuestion.required && singleValue" class="clear-answer" type="button" @click="singleValue = ''">清除选择</button>
    </div>
    <div v-else-if="currentQuestion.type === 'multiple'" class="answer-choices">
      <label v-for="option in currentQuestion.options" :key="option.id" class="answer-choice"><input v-model="multiValues" type="checkbox" :value="option.id" /><span>{{ option.label }}</span></label>
      <p class="answer-hint">{{ currentQuestion.validation.minSelections !== undefined ? `至少选 ${currentQuestion.validation.minSelections} 项` : '可多选' }}{{ currentQuestion.validation.maxSelections !== undefined ? `，最多选 ${currentQuestion.validation.maxSelections} 项` : '' }}</p>
    </div>
    <div v-else-if="currentQuestion.type === 'text'" class="answer-field">
      <textarea v-model="textValue" rows="5" placeholder="请在这里填写答案"></textarea>
      <p class="answer-hint">{{ currentQuestion.validation.minLength !== undefined ? `至少 ${currentQuestion.validation.minLength} 字` : '不限最少字数' }}{{ currentQuestion.validation.maxLength !== undefined ? `，最多 ${currentQuestion.validation.maxLength} 字` : '' }}</p>
    </div>
    <div v-else class="answer-field">
      <input v-model="numberValue" type="number" :step="currentQuestion.validation.integerOnly ? '1' : 'any'" placeholder="请输入数字" />
      <p class="answer-hint">{{ currentQuestion.validation.integerOnly ? '仅限整数；' : '' }}{{ currentQuestion.validation.minValue !== undefined ? `最小值 ${currentQuestion.validation.minValue}` : '' }}{{ currentQuestion.validation.maxValue !== undefined ? `，最大值 ${currentQuestion.validation.maxValue}` : '' }}</p>
    </div>
    <label v-if="survey.allowAnonymous" class="check-row fill-anonymous"><input v-model="isAnonymous" type="checkbox" /><span>匿名提交：创建者查看结果时不显示我的账户名</span></label>
    <p v-if="error" class="form-error" role="alert">{{ error }}</p>
    <div class="fill-actions"><button class="button button-outline" type="button" :disabled="currentIndex === 0 || pending" @click="previous">上一题</button><button class="button button-primary" type="submit" :disabled="pending">{{ pending ? '提交中…' : nextId ? '下一题' : '提交问卷' }}</button></div>
    <p class="fill-note">本次填写只在当前页面保留；刷新页面后不会恢复未提交内容。</p>
  </form>
  <p v-else class="card empty-card">此问卷没有可填写的题目。</p>
</template>
