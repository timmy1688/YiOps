import { computed, reactive } from 'vue'

import {
  getAuthStatus,
  getCurrentUser,
  login as loginRequest,
  logout as logoutRequest,
  type CurrentUser,
} from '@/api/client'

const state = reactive<{
  initialized: boolean
  enabled: boolean
  user: CurrentUser | null
}>({
  initialized: false,
  enabled: false,
  user: null,
})

let bootstrapPromise: Promise<void> | null = null

export const authState = state
export const isAuthenticated = computed(() => !state.enabled || state.user !== null)

export async function bootstrapAuth(force = false) {
  if (state.initialized && !force) return
  if (bootstrapPromise && !force) return bootstrapPromise
  bootstrapPromise = (async () => {
    try {
      const status = await getAuthStatus()
      state.enabled = status.enabled
      state.user = status.enabled && status.authenticated ? await getCurrentUser() : null
    } catch {
      state.enabled = true
      state.user = null
    } finally {
      state.initialized = true
      bootstrapPromise = null
    }
  })()
  return bootstrapPromise
}

export async function login(username: string, password: string) {
  state.user = await loginRequest(username, password)
  state.enabled = true
  state.initialized = true
}

export async function logout() {
  try {
    await logoutRequest()
  } finally {
    state.user = null
  }
}

window.addEventListener('yiops:unauthorized', () => {
  if (!state.enabled) return
  state.user = null
  if (window.location.pathname !== '/login') {
    const redirect = encodeURIComponent(`${window.location.pathname}${window.location.search}`)
    window.location.assign(`/login?redirect=${redirect}`)
  }
})
