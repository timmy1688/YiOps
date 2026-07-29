<script setup lang="ts">
import {
  Connection,
  Cpu,
  Delete as DeleteIcon,
  Edit,
  Key,
  Plus,
} from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { computed, onMounted, reactive, ref } from 'vue'

import {
  createModelConfig,
  deleteModelConfig,
  listModelConfigs,
  testModelConfig,
  updateModelConfig,
  type AnalysisModelConfig,
  type AnalysisModelConfigInput,
} from '@/api/client'

const loading = ref(false)
const drawerVisible = ref(false)
const saving = ref(false)
const testingId = ref('')
const activatingId = ref('')
const deletingId = ref('')
const editingId = ref('')
const configs = ref<AnalysisModelConfig[]>([])
const form = reactive<AnalysisModelConfigInput>({
  name: '',
  provider: 'deepseek',
  base_url: 'https://api.deepseek.com',
  model_name: 'deepseek-chat',
  api_key: '',
  enabled: false,
})

const editingConfig = computed(
  () => configs.value.find((item) => item.id === editingId.value) ?? null,
)
const activeConfig = computed(() => configs.value.find((item) => item.enabled) ?? null)
const modeLabel = computed(() => {
  if (!activeConfig.value?.api_key_configured) return '本地规则降级'
  if (activeConfig.value.last_test_status === 'healthy') return '真实模型已连接'
  return '渠道已启用，等待测试'
})

async function load() {
  loading.value = true
  try {
    const items = await listModelConfigs()
    if (!Array.isArray(items)) {
      throw new Error('模型渠道接口返回格式错误')
    }
    configs.value = items
  } catch {
    ElMessage.error('模型渠道加载失败')
  } finally {
    loading.value = false
  }
}

function openCreate() {
  editingId.value = ''
  Object.assign(form, {
    name: '',
    provider: 'deepseek',
    base_url: 'https://api.deepseek.com',
    model_name: 'deepseek-chat',
    api_key: '',
    enabled: configs.value.length === 0,
  })
  drawerVisible.value = true
}

function openEdit(item: AnalysisModelConfig) {
  editingId.value = item.id
  Object.assign(form, {
    name: item.name,
    provider: item.provider,
    base_url: item.base_url,
    model_name: item.model_name,
    api_key: '',
    enabled: item.enabled,
  })
  drawerVisible.value = true
}

async function save() {
  if (!form.name.trim() || !form.base_url.trim() || !form.model_name.trim()) {
    ElMessage.warning('请完整填写渠道名称、API 地址和模型名称')
    return
  }
  if (!editingConfig.value?.api_key_configured && !form.api_key?.trim()) {
    ElMessage.warning('新建渠道必须填写 API Key')
    return
  }

  const payload: AnalysisModelConfigInput = {
    name: form.name.trim(),
    provider: form.provider,
    base_url: form.base_url.trim(),
    model_name: form.model_name.trim(),
    api_key: form.api_key?.trim() || undefined,
    enabled: form.enabled,
  }
  saving.value = true
  try {
    if (editingId.value) {
      await updateModelConfig(editingId.value, payload)
      ElMessage.success('模型渠道已更新')
    } else {
      await createModelConfig(payload)
      ElMessage.success('模型渠道已添加')
    }
    drawerVisible.value = false
    await load()
  } catch {
    ElMessage.error('保存失败，请检查渠道名称和连接参数')
  } finally {
    saving.value = false
  }
}

async function test(item: AnalysisModelConfig) {
  testingId.value = item.id
  try {
    const result = await testModelConfig(item.id)
    await load()
    result.ok ? ElMessage.success(result.message) : ElMessage.error(result.message)
  } catch {
    ElMessage.error('连接测试失败，请检查渠道配置')
  } finally {
    testingId.value = ''
  }
}

async function activate(item: AnalysisModelConfig) {
  activatingId.value = item.id
  try {
    await updateModelConfig(item.id, {
      name: item.name,
      provider: item.provider,
      base_url: item.base_url,
      model_name: item.model_name,
      enabled: true,
    })
    await load()
    ElMessage.success(`已切换到“${item.name}”`)
  } catch {
    ElMessage.error('渠道切换失败')
  } finally {
    activatingId.value = ''
  }
}

async function remove(item: AnalysisModelConfig) {
  try {
    await ElMessageBox.confirm(
      `确定删除模型渠道“${item.name}”吗？${item.enabled ? '删除当前渠道后，分析将降级为本地规则。' : ''}`,
      '删除模型渠道',
      {
        confirmButtonText: '确认删除',
        cancelButtonText: '取消',
        confirmButtonClass: 'el-button--danger',
        type: 'warning',
      },
    )
  } catch {
    return
  }

  deletingId.value = item.id
  try {
    await deleteModelConfig(item.id)
    await load()
    ElMessage.success('模型渠道已删除')
  } catch {
    ElMessage.error('模型渠道删除失败')
  } finally {
    deletingId.value = ''
  }
}

function applyProviderPreset(provider: AnalysisModelConfig['provider']) {
  if (provider === 'deepseek') {
    form.base_url = 'https://api.deepseek.com'
    form.model_name = 'deepseek-chat'
    return
  }
  form.base_url = 'https://api.openai.com/v1'
  form.model_name = ''
}

onMounted(() => void load())
</script>

<template>
  <section>
    <header class="page-header">
      <div>
        <p class="eyebrow">ANALYSIS MODEL CHANNELS</p>
        <h1>分析模型</h1>
        <p class="page-subtitle">
          可维护多个模型渠道，并选择一个供 Agent 执行后续分析。
        </p>
      </div>
      <el-button type="primary" :icon="Plus" @click="openCreate">
        添加模型渠道
      </el-button>
    </header>

    <div class="model-summary-grid">
      <section class="panel model-status-card">
        <div class="model-status-icon"><Cpu /></div>
        <span>当前分析渠道</span>
        <strong>{{ activeConfig?.name || 'local-evidence-rules' }}</strong>
        <p>
          {{ activeConfig ? `${activeConfig.model_name} · ${modeLabel}` : modeLabel }}
        </p>
      </section>
      <section class="panel model-security-card">
        <Key />
        <div>
          <strong>OpenAI 兼容协议</strong>
          <p>所有渠道均使用 Chat Completions 接口；API Key 加密落库且不回显。</p>
        </div>
      </section>
    </div>

    <section v-loading="loading" class="model-channel-list">
      <article
        v-for="item in configs"
        :key="item.id"
        class="panel model-channel-card"
        :class="{ active: item.enabled }"
      >
        <div class="model-channel-main">
          <div class="model-channel-icon"><Connection /></div>
          <div class="model-channel-copy">
            <div class="model-channel-title">
              <h3>{{ item.name }}</h3>
              <el-tag type="info">
                {{ item.provider === 'deepseek' ? 'DeepSeek' : 'OpenAI Compatible' }}
              </el-tag>
              <el-tag v-if="item.enabled" type="primary">当前渠道</el-tag>
              <el-tag
                :type="item.last_test_status === 'healthy' ? 'success' : item.last_test_status === 'failed' ? 'danger' : 'info'"
              >
                {{
                  item.last_test_status === 'healthy'
                    ? '连接正常'
                    : item.last_test_status === 'failed'
                      ? '连接失败'
                      : '未测试'
                }}
              </el-tag>
            </div>
            <strong>{{ item.model_name }}</strong>
            <code>{{ item.base_url }}</code>
            <small>
              API Key：{{ item.api_key_configured ? '已配置' : '未配置' }}
              <template v-if="item.last_tested_at">
                · 最近测试 {{ new Date(item.last_tested_at).toLocaleString() }}
              </template>
            </small>
            <p v-if="item.last_test_message">{{ item.last_test_message }}</p>
          </div>
        </div>
        <div class="model-channel-actions">
          <el-button
            :loading="testingId === item.id"
            :disabled="!item.api_key_configured"
            @click="test(item)"
          >
            测试连接
          </el-button>
          <el-button
            v-if="!item.enabled"
            type="primary"
            plain
            :loading="activatingId === item.id"
            @click="activate(item)"
          >
            设为当前
          </el-button>
          <el-button :icon="Edit" @click="openEdit(item)">编辑</el-button>
          <el-button
            plain
            type="danger"
            :icon="DeleteIcon"
            :loading="deletingId === item.id"
            @click="remove(item)"
          >
            删除
          </el-button>
        </div>
      </article>
      <el-empty
        v-if="!loading && !configs.length"
        description="还没有模型渠道；当前分析使用本地证据规则"
      >
        <el-button type="primary" @click="openCreate">添加第一个渠道</el-button>
      </el-empty>
    </section>

    <el-drawer
      v-model="drawerVisible"
      :title="editingId ? '编辑模型渠道' : '添加模型渠道'"
      size="500px"
    >
      <p class="drawer-intro">
        填写服务商提供的 OpenAI Compatible Base URL、模型 ID 和 API Key。
      </p>
      <el-form label-position="top">
        <el-form-item label="渠道名称">
          <el-input v-model="form.name" placeholder="例如：生产 DeepSeek" />
        </el-form-item>
        <el-form-item label="渠道类型">
          <el-select
            v-model="form.provider"
            @change="applyProviderPreset"
          >
            <el-option label="DeepSeek" value="deepseek" />
            <el-option label="其他 OpenAI Compatible" value="openai_compatible" />
          </el-select>
          <span class="field-help">
            DeepSeek 渠道会自动填入官方默认地址；两种类型均使用 OpenAI 协议。
          </span>
        </el-form-item>
        <el-form-item label="API 地址">
          <el-input
            v-model="form.base_url"
            placeholder="例如：https://api.openai.com/v1"
          />
        </el-form-item>
        <el-form-item label="模型名称">
          <el-input v-model="form.model_name" placeholder="服务商提供的模型 ID" />
        </el-form-item>
        <el-form-item label="API Key">
          <el-input
            v-model="form.api_key"
            type="password"
            show-password
            :placeholder="
              editingConfig?.api_key_configured
                ? '已配置；留空表示不修改'
                : '请输入 API Key'
            "
          />
          <span class="field-help">
            Key 使用本机密钥加密保存，不会通过查询接口回显。
          </span>
        </el-form-item>
        <el-form-item class="switch-form-item">
          <div>
            <strong>设为当前分析渠道</strong>
            <span>开启后会自动停用其他渠道，下一次分析起生效</span>
          </div>
          <el-switch v-model="form.enabled" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="drawerVisible = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="save">保存</el-button>
      </template>
    </el-drawer>
  </section>
</template>
