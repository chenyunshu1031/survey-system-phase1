import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import ts from 'typescript'

// Exercise the actual TypeScript utility without adding a browser test framework.
const source = readFileSync(new URL('../src/utils/surveyAnswers.ts', import.meta.url), 'utf8')
const compiled = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2022 } }).outputText
const { validateAnswer, nextQuestionId } = await import(`data:text/javascript;base64,${Buffer.from(compiled).toString('base64')}`)
const text = { id: 'text', type: 'text', options: [], required: true, validation: { minLength: 1, maxLength: 1 }, jumpRules: [] }
assert.equal(validateAnswer(text, '😀'), null)
assert.equal(validateAnswer(text, '中'), null)
assert.equal(validateAnswer(text, ' 😀中 '), '最多输入 1 字')
assert.equal(validateAnswer({ ...text, validation: { minLength: 2 } }, '😀'), '至少输入 2 字')

const sourceQuestion = { id: 'q1', type: 'multiple', order: 1, options: [], validation: {}, jumpRules: [
  { priority: 1, operator: 'containsAll', optionIds: ['x', 'y'], targetQuestionId: 'q3' },
  { priority: 2, operator: 'containsAny', optionIds: ['x'], targetQuestionId: 'q2' },
] }
const questions = [sourceQuestion, { id: 'q2', order: 2 }, { id: 'q3', order: 3 }]
assert.equal(nextQuestionId(sourceQuestion, questions, ['x', 'y']), 'q3')
assert.equal(nextQuestionId(sourceQuestion, questions, ['x']), 'q2')
assert.equal(nextQuestionId(sourceQuestion, questions, []), 'q2')
assert.equal(nextQuestionId({ ...sourceQuestion, id: 'q3', order: 3, jumpRules: [] }, questions, null), null)

for (const space of ['\u0085', '\u001c', '\ufeff', '\u3000', '\u00a0']) {
  assert.equal(validateAnswer(text, `${space}中${space}`), null)
  assert.equal(validateAnswer(text, space), '此题必答')
}
for (const kind of ['single', 'text', 'number']) {
  assert.notEqual(validateAnswer({ ...text, type: kind, required: false }, []), null)
}
assert.notEqual(validateAnswer({ ...text, type: 'multiple', required: false }, ''), null)
const numericCases = [
  { operator: 'eq', value: 50, hits: [50], misses: [49, 51] },
  { operator: 'gt', value: 50, hits: [51], misses: [49, 50] },
  { operator: 'gte', value: 50, hits: [50, 51], misses: [49] },
  { operator: 'lt', value: 50, hits: [49], misses: [50, 51] },
  { operator: 'lte', value: 50, hits: [49, 50], misses: [51] },
  { operator: 'between', minValue: 0, maxValue: 100, hits: [0, 50, 100], misses: [-1, 101] },
]
let numericAssertions = 0
for (const { hits, misses, ...rule } of numericCases) {
  const numberQuestion = { ...text, id: 'q1', type: 'number', order: 1, validation: {}, jumpRules: [{ ...rule, priority: 1, targetQuestionId: 'q3' }] }
  for (const value of hits) {
    assert.equal(nextQuestionId(numberQuestion, [numberQuestion, questions[1], questions[2]], value), 'q3')
    numericAssertions += 1
  }
  for (const value of [...misses, null]) {
    assert.equal(nextQuestionId(numberQuestion, [numberQuestion, questions[1], questions[2]], value), 'q2')
    numericAssertions += 1
  }
}
console.log(`${22 + numericAssertions} frontend answer, whitespace, type and jump assertions passed`)
