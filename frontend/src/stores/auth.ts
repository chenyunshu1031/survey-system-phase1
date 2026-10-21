import { defineStore } from 'pinia'
import { api, clearToken, readToken, saveToken, sessionToken } from '../api/client'

interface User { id: string; username: string; createdAt: string }

export const useAuthStore = defineStore('auth', {
  state: () => ({ user: null as User | null, userToken: null as string | null }),
  getters: {
    isSignedIn: () => Boolean(sessionToken.value),
    username: (state) => state.userToken === sessionToken.value ? state.user?.username || '我的账户' : '我的账户',
  },
  actions: {
    async login(username: string, password: string) {
      const result = await api<{ accessToken: string }>('/auth/login', {
        method: 'POST', body: JSON.stringify({ username, password }),
      })
      saveToken(result.accessToken)
      await this.loadUser()
    },
    async loadUser() {
      const token = readToken()
      if (!token) return
      try {
        const user = await api<User>('/auth/me')
        if (readToken() === token) {
          this.user = user
          this.userToken = token
        }
      } catch {
        // The API client clears an expired session; a network failure does not.
      }
    },
    signOut() {
      clearToken()
      this.user = null
      this.userToken = null
    },
  },
})
