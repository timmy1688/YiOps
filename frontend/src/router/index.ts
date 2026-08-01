import { createRouter, createWebHistory } from 'vue-router'

import { authState, bootstrapAuth, isAuthenticated } from '@/auth'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/', redirect: '/incidents' },
    {
      path: '/login',
      name: 'login',
      component: () => import('@/views/LoginView.vue'),
      meta: { public: true },
    },
    {
      path: '/incidents',
      name: 'incidents',
      component: () => import('@/views/IncidentListView.vue'),
    },
    {
      path: '/incidents/:id',
      name: 'incident-detail',
      component: () => import('@/views/IncidentDetailView.vue'),
    },
    {
      path: '/chat',
      name: 'chat',
      component: () => import('@/views/ChatView.vue'),
    },
    {
      path: '/investigations',
      name: 'investigations',
      component: () => import('@/views/InvestigationView.vue'),
    },
    {
      path: '/evaluations',
      name: 'evaluations',
      component: () => import('@/views/EvaluationView.vue'),
    },
    {
      path: '/datasources',
      name: 'datasources',
      component: () => import('@/views/DatasourceView.vue'),
    },
    {
      path: '/integrations',
      name: 'integrations',
      component: () => import('@/views/IntegrationView.vue'),
    },
    {
      path: '/model-config',
      name: 'model-config',
      component: () => import('@/views/ModelConfigView.vue'),
    },
  ],
})

router.beforeEach(async (to) => {
  await bootstrapAuth()
  if (to.meta.public) {
    if (to.path === '/login' && isAuthenticated.value) return '/incidents'
    return true
  }
  if (!isAuthenticated.value) {
    return { path: '/login', query: { redirect: to.fullPath } }
  }
  if (!authState.initialized) return false
  return true
})

export default router
