<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { api } from '../api/client'
import type { JumpOperator, JumpRule, Question } from '../api/types'

interface RuleDraft {
  key: number
  id?: string
  operator: JumpOperator
  optionIds: string[]
  value: number | '' | null
  minValue: number | '' | null
  maxValue: number | '' | null
  targetQuestionId: string
}

const props = defineProps<{ surveyId: string; question: Question; questions: Question[]; editable: boolean }>()
const emit = defineEmits<{ saved: [question: Question] }>()
const expanded = ref(false)
const pending = ref(false)
const error = ref('')
const drafts = ref<RuleDraft[]>([])
let nextKey = 0
const laterQuestions = computed(() => props.questions.filter((item) => item.order > props.question.order))
const numericOperators: { value: JumpOperator; label: string }[] = [
  { value: 'eq', label: '等于' }, { value: 'gt', label: '大于' },
  { value: 'gte', label: '大于或等于' }, { value: 'lt', label: '小于' },
  { value: 'lte', label: '小于或等于' }, { value: 'between', label: '介于（含边界）' },
]

function fromSaved(rule: JumpRule): RuleDraft {
  return {
    key: nextKey++, id: rule.id, operator: rule.operator,
    optionIds: [...rule.optionIds], value: rule.value ?? null,
    minValue: rule.minValue ?? null, maxValue: rule.maxValue ?? null,
    targetQuestionId: rule.targetQuestionId,
  }
}

watch(() => props.question, (question) => {
  drafts.value = [...question.jumpRules].sort((a, b) => a.priority - b.priority).map(fromSaved)
  error.value = ''
}, { immediate: true })

function addRule() {
  const operator: JumpOperator = props.question.type === 'single' ? 'equals'
    : props.question.type === 'multiple' ? 'containsAny' : 'gte'
  drafts.value.push({
    key: nextKey++, operator,
    optionIds: props.question.type === 'number' ? [] : props.question.options[0] ? [props.question.options[0].id] : [],
    value: props.question.type === 'number' ? 0 : null,
    minValue: null, maxValue: null,
    targetQuestionId: laterQuestions.value[0]?.id || '',
  })
}

function moveRule(index: number, offset: number) {
  const target = index + offset
  if (target < 0 || target >= drafts.value.length) return
  const [item] = drafts.value.splice(index, 1)
  if (item) drafts.value.splice(target, 0, item)
}

async function saveRules() {
  error.value = ''
  const rules = []
  for (const [index, draft] of drafts.value.entries()) {
    if (!draft.targetQuestionId) { error.value = '请为每条规则选择跳转目标'; return }
    const base = {
      ...(draft.id ? { id: draft.id } : {}),
      priority: index + 1, targetQuestionId: draft.targetQuestionId, operator: draft.operator,
    }
    if (props.question.type === 'single' || props.question.type === 'multiple') {
      if (!draft.optionIds.length) { error.value = '请为每条规则选择至少一个选项'; return }
      rules.push({ ...base, optionIds: draft.optionIds })
    } else if (draft.operator === 'between') {
      if (draft.minValue === null || draft.maxValue === null || draft.minValue === '' || draft.maxValue === '') {
        error.value = '请填写数字区间的上下限'; return
      }
      rules.push({ ...base, minValue: Number(draft.minValue), maxValue: Number(draft.maxValue) })
    } else {
      if (draft.value === null || draft.value === '') { error.value = '请填写比较数值'; return }
      rules.push({ ...base, value: Number(draft.value) })
    }
  }
  pending.value = true
  try {
    const question = await api<Question>(`/surveys/${props.surveyId}/questions/${props.question.id}/jump-rules`, {
      method: 'PUT', body: JSON.stringify({ rules }),
    })
    emit('saved', question)
    expanded.value = Boolean(question.jumpRuleWarnings?.length)
  } catch (reason) {
    error.value = reason instanceof Error ? reason.message : '保存失败'
  } finally { pending.value = false }
}
</script>

<template>
  <section v-if="question.type !== 'text' && laterQuestions.length" class="jump-panel">
    <button class="jump-toggle" type="button" :aria-expanded="expanded" @click="expanded = !expanded">
      <span>条件跳转 <small>{{ question.jumpRules.length ? `已设置 ${question.jumpRules.length} 条` : '未设置，默认下一题' }}</small></span>
      <span aria-hidden="true">{{ expanded ? '收起 ↑' : '配置 ↓' }}</span>
    </button>
    <div v-if="question.jumpRuleWarnings?.length" class="jump-warnings" role="status">
      <strong>已保存规则的检查提示</strong>
      <ul><li v-for="warning in question.jumpRuleWarnings" :key="warning">{{ warning }}</li></ul>
    </div>
    <div v-if="expanded" class="jump-panel-content">
      <p class="jump-help">按从上到下的优先级匹配；没有命中时进入下一题。保存时会检查条件能否命中；已保存规则的提示显示在上方。</p>
      <div v-for="(rule, index) in drafts" :key="rule.key" class="jump-rule">
        <div class="jump-rule-heading"><strong>优先级 {{ index + 1 }}</strong><div v-if="editable" class="jump-rule-actions"><button type="button" :disabled="index === 0" @click="moveRule(index, -1)">上移</button><button type="button" :disabled="index === drafts.length - 1" @click="moveRule(index, 1)">下移</button><button type="button" @click="drafts.splice(index, 1)">删除</button></div></div>
        <template v-if="question.type === 'single'">
          <label>当选择<select v-model="rule.optionIds[0]" :disabled="!editable"><option v-for="option in question.options" :key="option.id" :value="option.id">{{ option.label }}</option></select></label>
        </template>
        <template v-else-if="question.type === 'multiple'">
          <label>匹配方式<select v-model="rule.operator" :disabled="!editable"><option value="containsAny">包含任意所选项</option><option value="containsAll">同时包含全部所选项</option></select></label>
          <div class="jump-option-grid"><label v-for="option in question.options" :key="option.id" class="jump-option"><input v-model="rule.optionIds" type="checkbox" :value="option.id" :disabled="!editable" />{{ option.label }}</label></div>
        </template>
        <template v-else>
          <label>数字条件<select v-model="rule.operator" :disabled="!editable"><option v-for="operator in numericOperators" :key="operator.value" :value="operator.value">{{ operator.label }}</option></select></label>
          <div v-if="rule.operator === 'between'" class="two-fields"><label>最小值<input v-model.number="rule.minValue" type="number" step="any" :disabled="!editable" /></label><label>最大值<input v-model.number="rule.maxValue" type="number" step="any" :disabled="!editable" /></label></div>
          <label v-else>比较值<input v-model.number="rule.value" type="number" step="any" :disabled="!editable" /></label>
        </template>
        <label>跳转到<select v-model="rule.targetQuestionId" :disabled="!editable"><option v-for="target in laterQuestions" :key="target.id" :value="target.id">第 {{ target.order }} 题 · {{ target.title }}</option></select></label>
      </div>
      <template v-if="editable">
        <button class="add-option" type="button" @click="addRule">＋ 添加跳转规则</button>
        <p v-if="error" class="form-error" role="alert">{{ error }}</p>
        <button class="button button-primary button-wide" type="button" :disabled="pending" @click="saveRules">{{ pending ? '保存中…' : '保存跳转规则' }}</button>
      </template>
    </div>
  </section>
</template>

<style scoped>
.jump-warnings { margin-top: 12px; padding: 12px 14px; border: 1px solid #e7c98c; border-radius: 9px; background: #fff8e8; color: #78531a; font-size: 12px; line-height: 1.65; }
.jump-warnings ul { margin: 5px 0 0; padding-left: 19px; }
</style>
