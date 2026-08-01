<script setup lang="ts">
import {
  Bell,
  ChatDotRound,
  Compass,
  Cpu,
  DataAnalysis,
  DataLine,
  Monitor,
  Lock,
  Setting,
  SetUp,
  SwitchButton,
} from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import { computed } from 'vue'
import { reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import { changePassword } from '@/api/client'
import { authState, logout } from '@/auth'

const route = useRoute()
const router = useRouter()
const isLoginPage = computed(() => route.path === '/login')
const passwordOpen = ref(false)
const passwordLoading = ref(false)
const passwordForm = reactive({ current: '', next: '', confirm: '' })
const activeMenu = computed(() => {
  if (route.path.startsWith('/chat')) return '/chat'
  if (route.path.startsWith('/investigations')) return '/investigations'
  if (route.path.startsWith('/evaluations')) return '/evaluations'
  if (route.path.startsWith('/datasources')) return '/datasources'
  if (route.path.startsWith('/integrations')) return '/integrations'
  if (route.path.startsWith('/model-config')) return '/model-config'
  return '/incidents'
})
const pageTitle = computed(() => {
  if (route.path.startsWith('/chat')) return 'AI 运维助手'
  if (route.path.startsWith('/investigations')) return '根因调查工作台'
  if (route.path.startsWith('/evaluations')) return 'RCA 评测中心'
  if (route.path.startsWith('/datasources')) return '数据源管理'
  if (route.path.startsWith('/integrations')) return '告警接入'
  if (route.path.startsWith('/model-config')) return '模型配置'
  return '智能故障分析'
})

async function signOut() {
  await logout()
  ElMessage.success('已安全退出')
  await router.replace('/login')
}

async function submitPasswordChange() {
  if (passwordForm.next.length < 12) {
    ElMessage.warning('新密码至少需要 12 位')
    return
  }
  if (passwordForm.next !== passwordForm.confirm) {
    ElMessage.warning('两次输入的新密码不一致')
    return
  }
  passwordLoading.value = true
  try {
    await changePassword(passwordForm.current, passwordForm.next)
    passwordOpen.value = false
    Object.assign(passwordForm, { current: '', next: '', confirm: '' })
    ElMessage.success('密码已更新，其他登录会话已失效')
  } catch (error: any) {
    ElMessage.error(error?.response?.data?.detail || '密码修改失败')
  } finally {
    passwordLoading.value = false
  }
}
</script>

<template>
  <router-view v-if="isLoginPage" />
  <div v-else class="app-shell">
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
        <el-menu-item index="/chat">
          <el-icon><ChatDotRound /></el-icon>
          <span>AI 助手</span>
        </el-menu-item>
        <el-menu-item index="/investigations">
          <el-icon><Compass /></el-icon>
          <span>调查工作台</span>
        </el-menu-item>
        <el-menu-item index="/evaluations">
          <el-icon><DataLine /></el-icon>
          <span>RCA 评测</span>
        </el-menu-item>
        <el-sub-menu index="system-settings">
          <template #title>
            <el-icon><Setting /></el-icon>
            <span>系统设置</span>
          </template>
          <el-menu-item index="/model-config">
            <el-icon><Cpu /></el-icon>
            <span>模型配置</span>
          </el-menu-item>
          <el-menu-item index="/datasources">
            <el-icon><SetUp /></el-icon>
            <span>数据源</span>
          </el-menu-item>
          <el-menu-item index="/integrations">
            <el-icon><Bell /></el-icon>
            <span>告警接入</span>
          </el-menu-item>
        </el-sub-menu>
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
          <el-dropdown v-if="authState.enabled && authState.user" trigger="click">
            <button type="button" class="user-menu">
              <span>{{ authState.user.display_name.slice(0, 1).toUpperCase() }}</span>
              <div>
                <strong>{{ authState.user.display_name }}</strong>
                <small>{{ authState.user.tenant_name }}</small>
              </div>
            </button>
            <template #dropdown>
              <el-dropdown-menu>
                <el-dropdown-item :icon="Lock" @click="passwordOpen = true">修改密码</el-dropdown-item>
                <el-dropdown-item :icon="SwitchButton" @click="signOut">退出登录</el-dropdown-item>
              </el-dropdown-menu>
            </template>
          </el-dropdown>
        </div>
      </header>
      <main class="main-content">
        <router-view />
      </main>
    </div>

    <el-dialog v-model="passwordOpen" title="修改管理员密码" width="440px">
      <el-form label-position="top">
        <el-form-item label="当前密码">
          <el-input v-model="passwordForm.current" type="password" show-password autocomplete="current-password" />
        </el-form-item>
        <el-form-item label="新密码">
          <el-input v-model="passwordForm.next" type="password" show-password autocomplete="new-password" placeholder="至少 12 位" />
        </el-form-item>
        <el-form-item label="确认新密码">
          <el-input v-model="passwordForm.confirm" type="password" show-password autocomplete="new-password" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="passwordOpen = false">取消</el-button>
        <el-button type="primary" :loading="passwordLoading" @click="submitPasswordChange">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>
