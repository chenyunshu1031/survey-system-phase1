<script setup lang="ts">
import { ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { api } from '../api/client'
import { useAuthStore } from '../stores/auth'

const auth = useAuthStore()
const route = useRoute()
const router = useRouter()
const mode = ref<'login' | 'register'>('login')
const username = ref('')
const password = ref('')
const pending = ref(false)
const error = ref('')

async function submit() {
  error.value = ''
  pending.value = true
  try {
    if (mode.value === 'register') {
      await api('/auth/register', { method: 'POST', body: JSON.stringify({ username: username.value, password: password.value }) })
    }
    await auth.login(username.value, password.value)
    await router.push(typeof route.query.next === 'string' ? route.query.next : '/surveys')
  } catch (reason) {
    error.value = reason instanceof Error ? reason.message : '操作失败'
  } finally {
    pending.value = false
  }
}
</script>

<template>
  <section class="auth-layout">
    <div class="auth-intro">
      <span class="eyebrow">SURVEY WORKSPACE</span>
      <h1>让每一个问题<br /><em>都有清晰的去处。</em></h1>
      <p>创建问卷、组织题目与收集答案，从一个简洁的工作台开始。</p>
      <div class="intro-line"><span>01</span> 设计问卷 <span>→</span> 发布分享 <span>→</span> 理解结果</div>
    </div>
    <div class="card auth-card">
      <div class="pill">欢迎使用问序</div>
      <h2>{{ mode === 'login' ? '登录账户' : '创建账户' }}</h2>
      <p class="muted">{{ mode === 'login' ? '继续管理你的问卷。' : '几步即可开始创建第一份问卷。' }}</p>
      <form @submit.prevent="submit" class="form-stack">
        <label>用户名<input v-model="username" autocomplete="username" required minlength="3" maxlength="40" placeholder="请输入用户名" /></label>
        <label>密码<input v-model="password" type="password" :autocomplete="mode === 'login' ? 'current-password' : 'new-password'" required minlength="8" placeholder="至少 8 位" /></label>
        <p v-if="error" class="form-error" role="alert">{{ error }}</p>
        <button class="button button-primary button-wide" type="submit" :disabled="pending">{{ pending ? '处理中…' : mode === 'login' ? '登录' : '注册并登录' }}</button>
      </form>
      <div class="auth-switch">
        {{ mode === 'login' ? '还没有账户？' : '已有账户？' }}
        <button class="inline-button" type="button" @click="mode = mode === 'login' ? 'register' : 'login'; error = ''">{{ mode === 'login' ? '立即注册' : '返回登录' }}</button>
      </div>
    </div>
  </section>
</template>
