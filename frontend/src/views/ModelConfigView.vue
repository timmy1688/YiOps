<script setup lang="ts">
import { Connection, Key, Cpu } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import { computed, onMounted, reactive, ref } from 'vue'

import {
  getModelConfig,
  saveModelConfig,
  testModelConfig,
  type AnalysisModelConfig,
  type AnalysisModelConfigInput,
} from '@/api/client'

const loading = ref(false)
const saving = ref(false)
const testing = ref(false)
const saved = ref<AnalysisModelConfig | null>(null)
const form = reactive<AnalysisModelConfigInput>({
  name: 'DeepSeek',
  provider: 'deepseek',
  base_url: 'https://api.deepseek.com',
  model_name: 'deepseek-chat',
  api_key: '',
  enabled: true,
})

const modeLabel = computed(() => {
  if (!saved.value?.enabled || !saved.value.api_key_configured) return '本地规则降级'
  if (saved.value.last_test_status === 'healthy') return '真实模型已连接'
  return '模型已配置，等待测试'
})

async function load() {
  loading.value = true
  try {
    saved.value = await getModelConfig()
    if (saved.value) {
      form.name = saved.value.name
      form.provider = saved.value.provider
      form.base_url = saved.value.base_url
      form.model_name = saved.value.model_name
      form.api_key = ''
      form.enabled = saved.value.enabled
    }
  } catch {
    ElMessage.error('模型配置加载失败')
  } finally {
    loading.value = false
  }
}

async function save() {
  if (!form.name.trim() || !form.base_url.trim() || !form.model_name.trim()) {
    ElMessage.warning('请完整填写名称、API 地址和模型名称')
    return
  }
  if (!saved.value?.api_key_configured && !form.api_key?.trim()) {
    ElMessage.warning('首次接入必须填写 API Key')
    return
  }
  saving.value = true
  try {
    saved.value = await saveModelConfig({
      ...form,
      name: form.name.trim(),
      base_url: form.base_url.trim(),
      model_name: form.model_name.trim(),
      api_key: form.api_key?.trim() || undefined,
    })
    form.api_key = ''
    ElMessage.success('模型配置已加密保存')
  } catch {
    ElMessage.error('保存失败，请检查填写内容')
  } finally {
    saving.value = false
  }
}

async function test() {
  testing.value = true
  try {
    const result = await testModelConfig()
    await load()
    result.ok ? ElMessage.success(result.message) : ElMessage.error(result.message)
  } catch {
    ElMessage.error('连接测试失败，请先保存配置')
  } finally {
    testing.value = false
  }
}

onMounted(() => void load())
</script>

<template>
  <section v-loading="loading">
    <header class="page-header">
      <div>
        <p class="eyebrow">ANALYSIS MODEL</p>
        <h1>分析模型</h1>
        <p class="page-subtitle">
          Agent 使用该模型制定调查计划并基于证据生成根因报告。
        </p>
      </div>
      <div class="model-mode-badge" :class="{ healthy: saved?.last_test_status === 'healthy' }">
        <i></i>{{ modeLabel }}
      </div>
    </header>

    <div class="model-config-layout">
      <section class="panel model-config-form">
        <div class="section-heading">
          <div>
            <h2>模型连接</h2>
            <p>当前 MVP 只启用一个分析模型，修改后对下一次分析生效</p>
          </div>
        </div>

        <el-form label-position="top">
          <div class="form-grid">
            <el-form-item label="配置名称">
              <el-input v-model="form.name" placeholder="例如：生产 DeepSeek" />
            </el-form-item>
            <el-form-item label="接口类型">
              <el-select v-model="form.provider">
                <el-option label="DeepSeek" value="deepseek" />
                <el-option label="OpenAI 兼容接口" value="openai_compatible" />
              </el-select>
            </el-form-item>
          </div>
          <el-form-item label="API 地址">
            <el-input v-model="form.base_url" placeholder="https://api.deepseek.com" />
          </el-form-item>
          <el-form-item label="模型名称">
            <el-input
              v-model="form.model_name"
              placeholder="填写服务商实际提供的模型 ID"
            />
          </el-form-item>
          <el-form-item label="API Key">
            <el-input
              v-model="form.api_key"
              type="password"
              show-password
              :placeholder="
                saved?.api_key_configured
                  ? '已配置；留空表示不修改'
                  : '请输入 API Key'
              "
            />
            <span class="field-help">
              Key 使用本机密钥加密保存，不会通过查询接口回显，也不会传给数据源。
            </span>
          </el-form-item>
          <el-form-item class="switch-form-item">
            <div>
              <strong>启用真实模型</strong>
              <span>关闭后分析自动降级为本地证据规则</span>
            </div>
            <el-switch v-model="form.enabled" />
          </el-form-item>
          <div class="model-form-actions">
            <el-button
              :icon="Connection"
              :loading="testing"
              :disabled="!saved?.api_key_configured"
              @click="test"
            >
              测试连接
            </el-button>
            <el-button type="primary" :loading="saving" @click="save">
              保存配置
            </el-button>
          </div>
        </el-form>
      </section>

      <aside class="model-config-side">
        <section class="panel model-status-card">
          <div class="model-status-icon"><Cpu /></div>
          <span>当前分析引擎</span>
          <strong>{{ saved?.model_name || 'local-evidence-rules' }}</strong>
          <p>{{ modeLabel }}</p>
        </section>

        <section class="panel model-security-card">
          <Key />
          <div>
            <strong>密钥安全</strong>
            <p>API Key 加密落库，前端只能看到是否已配置。</p>
          </div>
        </section>

        <section v-if="saved?.last_tested_at" class="panel model-test-card">
          <span>最近连接测试</span>
          <strong :class="saved.last_test_status || ''">
            {{ saved.last_test_status === 'healthy' ? '连接成功' : '连接失败' }}
          </strong>
          <p>{{ saved.last_test_message }}</p>
          <time>{{ new Date(saved.last_tested_at).toLocaleString() }}</time>
        </section>
      </aside>
    </div>
  </section>
</template>
