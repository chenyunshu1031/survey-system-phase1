import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { test } from 'node:test'
import ts from 'typescript'
import { createPinia, setActivePinia } from 'pinia'

const storage = new Map()
globalThis.sessionStorage = {
  getItem: (key) => storage.get(key) ?? null,
  setItem: (key, value) => storage.set(key, value),
  removeItem: (key) => storage.delete(key),
}

function moduleUrl(path, replacements = {}) {
  let source = readFileSync(new URL(path, import.meta.url), 'utf8')
  for (const [name, url] of Object.entries({ vue: import.meta.resolve('vue'), pinia: import.meta.resolve('pinia'), ...replacements })) {
    source = source.replaceAll(`from '${name}'`, `from '${url}'`)
  }
  const compiled = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2022 } }).outputText
  return `data:text/javascript;base64,${Buffer.from(compiled).toString('base64')}`
}

const clientUrl = moduleUrl('../src/api/client.ts')
const { api, saveToken, readToken, clearToken } = await import(clientUrl)
const { useAuthStore } = await import(moduleUrl('../src/stores/auth.ts', { '../api/client': clientUrl }))
const { parseBeijingInput, formatBeijingInput, formatBeijingDisplay } = await import(moduleUrl('../src/utils/beijingTime.ts'))
const failure = () => new Response(JSON.stringify({ detail: '登录已失效' }), { status: 401 })

test('401 clears the matching session and immediately updates the store', async () => {
  setActivePinia(createPinia())
  const auth = useAuthStore()
  saveToken('old-session')
  assert.equal(auth.isSignedIn, true)
  globalThis.fetch = async () => failure()
  await assert.rejects(api('/surveys'), /登录已失效/)
  assert.equal(readToken(), null)
  assert.equal(auth.isSignedIn, false)
})

test('an old request cannot clear a newer login', async () => {
  saveToken('old-session')
  let finish
  globalThis.fetch = () => new Promise((resolve) => { finish = resolve })
  const pending = api('/surveys')
  saveToken('new-session')
  finish(failure())
  await assert.rejects(pending, /登录已失效/)
  assert.equal(readToken(), 'new-session')
})

test('a failed login does not send or clear an existing session token', async () => {
  saveToken('existing-session')
  globalThis.fetch = async (_url, init) => {
    assert.equal(init.headers.has('Authorization'), false)
    return failure()
  }
  await assert.rejects(api('/auth/login', { method: 'POST' }))
  assert.equal(readToken(), 'existing-session')
})

test('a temporary network failure does not sign the user out', async () => {
  setActivePinia(createPinia())
  const auth = useAuthStore()
  saveToken('network-session')
  globalThis.fetch = async () => { throw new TypeError('network error') }
  await auth.loadUser()
  assert.equal(readToken(), 'network-session')
  assert.equal(auth.isSignedIn, true)
})

test('an old profile response cannot replace the newly logged in user', async () => {
  setActivePinia(createPinia())
  const auth = useAuthStore()
  saveToken('old-session')
  let finish
  globalThis.fetch = () => new Promise((resolve) => { finish = resolve })
  const pending = auth.loadUser()
  saveToken('new-session')
  globalThis.fetch = async () => Response.json({ id: 'new', username: '新账号' })
  await auth.loadUser()
  finish(Response.json({ id: 'old', username: '旧账号' }))
  await pending
  assert.equal(auth.user.id, 'new')
  assert.equal(auth.username, '新账号')
  clearToken()
  assert.equal(auth.username, '我的账户')
})

test('Beijing input is converted to UTC with valid leap days', () => {
  assert.equal(parseBeijingInput('2028-02-29T13:21'), '2028-02-29T05:21:00.000Z')
  assert.equal(formatBeijingInput('2026-10-19T05:21:00Z'), '2026-10-19T13:21')
  assert.equal(formatBeijingDisplay('2026-10-19T05:21:00Z'), '2026/10/19 13:21:00')
})

test('invalid calendar dates are rejected instead of silently normalized', () => {
  for (const input of ['2026-02-29T13:21', '2026-02-30T13:21', '2026-04-31T12:00', '2026-10-19T24:00', '2026-13-01T12:00', '2026-10-19']) {
    assert.throws(() => parseBeijingInput(input))
  }
})
