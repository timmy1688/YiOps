<script setup lang="ts">
import { Lock, User } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import { reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import { login } from '@/auth'

const route = useRoute()
const router = useRouter()
const loading = ref(false)
const form = reactive({ username: 'admin', password: '' })

async function submit() {
  if (!form.username.trim() || !form.password) return
  loading.value = true
  try {
    await login(form.username.trim(), form.password)
    const redirect = typeof route.query.redirect === 'string' ? route.query.redirect : '/incidents'
    await router.replace(redirect.startsWith('/') ? redirect : '/incidents')
  } catch (error: any) {
    const detail = error?.response?.data?.detail
    ElMessage.error(typeof detail === 'string' ? detail : '登录失败，请检查用户名和密码')
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <main class="login-page">
    <section class="login-story">
      <div class="login-brand"><span>Y</span><strong>YiOps</strong></div>
      <div>
        <p class="eyebrow">EVIDENCE-DRIVEN RCA</p>
        <h1>让每一个根因结论，<br />都能回到真实证据。</h1>
        <p>跨 Loki、Prometheus 与 Kubernetes 持续取证，形成可追溯、可复核的故障调查。</p>
      </div>
      <div class="login-points">
        <span>只读工具边界</span><span>多源证据链</span><span>完整审计轨迹</span>
      </div>
    </section>

    <section class="login-panel">
      <form class="login-card" @submit.prevent="submit">
        <div class="login-card-mark">Y</div>
        <h2>登录 YiOps</h2>
        <p>进入你的根因分析工作空间</p>
        <el-input v-model="form.username" size="large" autocomplete="username" placeholder="用户名" :prefix-icon="User" />
        <el-input v-model="form.password" size="large" type="password" show-password autocomplete="current-password" placeholder="密码" :prefix-icon="Lock" @keyup.enter="submit" />
        <el-button type="primary" size="large" native-type="submit" :loading="loading">登录</el-button>
        <small>管理员凭据由部署时生成的私有环境文件管理</small>
      </form>
    </section>
  </main>
</template>

<style scoped>
.login-page { min-height: 100vh; display: grid; grid-template-columns: minmax(420px, 1.1fr) minmax(420px, .9fr); background: #f8faff; }
.login-story { position: relative; display: flex; flex-direction: column; justify-content: space-between; overflow: hidden; padding: 44px 64px; color: #fff; background: linear-gradient(145deg, #172b66 0%, #294bc2 55%, #4d6de2 100%); }
.login-story::before, .login-story::after { position: absolute; content: ''; border: 1px solid rgb(255 255 255 / 12%); border-radius: 50%; }
.login-story::before { width: 520px; height: 520px; right: -220px; top: -160px; }
.login-story::after { width: 360px; height: 360px; left: -170px; bottom: -160px; }
.login-brand { position: relative; z-index: 1; display: flex; align-items: center; gap: 12px; font-size: 20px; }
.login-brand span, .login-card-mark { display: grid; place-items: center; width: 40px; height: 40px; border-radius: 10px; color: #3151c6; background: #fff; font-weight: 750; }
.login-story > div { position: relative; z-index: 1; }
.login-story .eyebrow { color: #bdcaff; }
.login-story h1 { margin: 14px 0 22px; font-size: clamp(38px, 4vw, 62px); line-height: 1.18; letter-spacing: -2px; }
.login-story > div > p:last-child { max-width: 560px; color: #dbe3ff; font-size: 16px; line-height: 1.9; }
.login-points { display: flex; gap: 26px; color: #dbe3ff; font-size: 12px; }
.login-points span::before { margin-right: 8px; color: #66e3af; content: '●'; }
.login-panel { display: grid; place-items: center; padding: 48px; }
.login-card { display: grid; width: min(390px, 100%); gap: 16px; padding: 42px; border: 1px solid #e4e8f2; border-radius: 18px; background: #fff; box-shadow: 0 22px 70px rgb(36 55 112 / 10%); }
.login-card-mark { color: #fff; background: #4161d7; }
.login-card h2 { margin: 8px 0 -8px; font-size: 27px; }
.login-card > p { margin: 0 0 10px; color: #7a849d; font-size: 13px; }
.login-card .el-button { width: 100%; margin-top: 5px; }
.login-card small { color: #98a2b3; font-size: 10px; text-align: center; }
@media (max-width: 900px) { .login-page { grid-template-columns: 1fr; } .login-story { display: none; } .login-panel { padding: 28px; } }
</style>
