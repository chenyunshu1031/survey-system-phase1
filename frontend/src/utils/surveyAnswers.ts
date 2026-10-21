import type { Question } from '../api/types'

export type AnswerValue = string | string[] | number | null

export function trimTextAnswer(value: string): string {
  // JS whitespace plus Python's control separators and NEL.
  return value.replace(/^[\s\u001c-\u001f\u0085]+|[\s\u001c-\u001f\u0085]+$/gu, '')
}

export function validateAnswer(question: Question, value: AnswerValue): string | null {
  const options = new Set(question.options.map((item) => item.id))
  const empty = value === null || (question.type !== 'multiple' && value === '')
    || (question.type === 'multiple' && Array.isArray(value) && value.length === 0)
  if (empty) return question.required ? '此题必答' : null

  if (question.type === 'single') {
    if (typeof value !== 'string' || !options.has(value)) return '请选择有效选项'
  } else if (question.type === 'multiple') {
    if (!Array.isArray(value) || value.some((item) => !options.has(item)) || new Set(value).size !== value.length) return '请选择有效选项'
    if (question.validation.minSelections !== undefined && value.length < question.validation.minSelections) return `至少选择 ${question.validation.minSelections} 项`
    if (question.validation.maxSelections !== undefined && value.length > question.validation.maxSelections) return `最多选择 ${question.validation.maxSelections} 项`
  } else if (question.type === 'text') {
    if (typeof value !== 'string') return '请输入文字'
    const count = Array.from(trimTextAnswer(value)).length
    if (question.required && !count) return '此题必答'
    if (!count) return null
    if (question.validation.minLength !== undefined && count < question.validation.minLength) return `至少输入 ${question.validation.minLength} 字`
    if (question.validation.maxLength !== undefined && count > question.validation.maxLength) return `最多输入 ${question.validation.maxLength} 字`
  } else {
    if (typeof value !== 'number' || !Number.isFinite(value) || !Number.isSafeInteger(Math.trunc(value))) return '请输入有效数字'
    if (question.validation.integerOnly && !Number.isInteger(value)) return '必须输入整数'
    if (question.validation.minValue !== undefined && value < question.validation.minValue) return `不能小于 ${question.validation.minValue}`
    if (question.validation.maxValue !== undefined && value > question.validation.maxValue) return `不能大于 ${question.validation.maxValue}`
  }
  return null
}

export function nextQuestionId(question: Question, questions: Question[], value: AnswerValue): string | null {
  for (const rule of [...question.jumpRules].sort((a, b) => a.priority - b.priority)) {
    let matched = false
    if (question.type === 'single' && typeof value === 'string') {
      matched = rule.operator === 'equals' && value === rule.optionIds[0]
    } else if (question.type === 'multiple' && Array.isArray(value)) {
      const selected = new Set(value)
      matched = (rule.operator === 'containsAny' && rule.optionIds.some((id) => selected.has(id)))
        || (rule.operator === 'containsAll' && rule.optionIds.every((id) => selected.has(id)))
    } else if (question.type === 'number' && typeof value === 'number') {
      matched = rule.operator === 'between'
        ? rule.minValue !== undefined && rule.maxValue !== undefined && value >= rule.minValue && value <= rule.maxValue
        : rule.value !== undefined && (
          (rule.operator === 'eq' && value === rule.value) ||
          (rule.operator === 'gt' && value > rule.value) ||
          (rule.operator === 'gte' && value >= rule.value) ||
          (rule.operator === 'lt' && value < rule.value) ||
          (rule.operator === 'lte' && value <= rule.value)
        )
    }
    if (matched) return rule.targetQuestionId
  }
  return questions.find((item) => item.order > question.order)?.id ?? null
}
