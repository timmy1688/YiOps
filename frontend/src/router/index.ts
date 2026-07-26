import { createRouter, createWebHistory } from 'vue-router'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/', redirect: '/incidents' },
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

export default router
