<script setup lang="ts">
import { Bell, Cpu, DataAnalysis, Monitor, SetUp } from '@element-plus/icons-vue'
import { computed } from 'vue'
import { useRoute } from 'vue-router'

const route = useRoute()
const activeMenu = computed(() => {
  if (route.path.startsWith('/datasources')) return '/datasources'
  if (route.path.startsWith('/integrations')) return '/integrations'
  if (route.path.startsWith('/model-config')) return '/model-config'
  return '/incidents'
})
const pageTitle = computed(() => {
  if (route.path.startsWith('/datasources')) return '数据源管理'
  if (route.path.startsWith('/integrations')) return '告警接入'
  if (route.path.startsWith('/model-config')) return '分析模型'
  return '智能故障分析'
})
</script>

<template>
  <div class="app-shell">
    <aside class="sidebar">
      <div class="brand">
        <div class="brand-mark">Y</div>
        <div>
          <strong>YiOps</strong>
          <span>智能运维</span>
        </div>
      </div>

      <el-menu :default-active="activeMenu" router class="nav-menu">
        <el-menu-item index="/incidents">
          <el-icon><Monitor /></el-icon>
          <span>故障调查</span>
        </el-menu-item>
        <el-menu-item index="/integrations">
          <el-icon><Bell /></el-icon>
          <span>告警接入</span>
        </el-menu-item>
        <el-menu-item index="/datasources">
          <el-icon><SetUp /></el-icon>
          <span>数据源</span>
        </el-menu-item>
        <el-menu-item index="/model-config">
          <el-icon><Cpu /></el-icon>
          <span>分析模型</span>
        </el-menu-item>
      </el-menu>

      <div class="agent-status">
        <DataAnalysis />
        <span class="live-dot"></span>
        <b>Agent 正常</b>
      </div>
    </aside>

    <div class="workspace">
      <header class="topbar">
        <strong>{{ pageTitle }}</strong>
        <div class="topbar-actions">
          <span class="environment-badge"><i></i> 只读模式</span>
        </div>
      </header>
      <main class="main-content">
        <router-view />
      </main>
    </div>
  </div>
</template>
