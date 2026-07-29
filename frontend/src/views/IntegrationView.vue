<script setup lang="ts">
import { CopyDocument, Delete as DeleteIcon, Plus } from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { computed, onMounted, reactive, ref } from 'vue'

import {
  createIntegration,
  deleteIntegration,
  listIntegrations,
  updateIntegration,
  type AlertIntegration,
  type AlertIntegrationInput,
} from '@/api/client'

const loading = ref(false)
const submitting = ref(false)
const drawerVisible = ref(false)
const deletingId = ref('')
const integrations = ref<AlertIntegration[]>([])
const form = reactive<AlertIntegrationInput>({
  name: '生产环境 Alertmanager',
  type: 'alertmanager',
  default_cluster: '',
  default_namespace: '',
  auto_analyze: true,
  enabled: true,
})

const enabledCount = computed(
  () => integrations.value.filter((item) => item.enabled).length,
)
const receivedCount = computed(() =>
  integrations.value.reduce((total, item) => total + item.received_count, 0),
)

async function load() {
  loading.value = true
  try {
    integrations.value = await listIntegrations()
  } catch {
    ElMessage.error('告警接入配置加载失败')
  } finally {
    loading.value = false
  }
}

onMounted(() => void load())

function webhookUrl(item: AlertIntegration) {
  return `${window.location.origin}${item.webhook_path}`
}

function alertmanagerYaml(item: AlertIntegration) {
  return `receivers:
  - name: yiops-${item.id.slice(-6)}
    webhook_configs:
      - url: '${webhookUrl(item)}'
        send_resolved: true

route:
  receiver: yiops-${item.id.slice(-6)}`
}

async function copy(value: string, success: string) {
  try {
    await navigator.clipboard.writeText(value)
    ElMessage.success(success)
  } catch {
    ElMessage.error('复制失败，请手动选择复制')
  }
}

async function submit() {
  const cluster = form.default_cluster?.trim()
  if (!form.name.trim()) {
    ElMessage.warning('请填写接入名称')
    return
  }
  if (!cluster) {
    ElMessage.warning('请填写第三方 K8s 集群标识')
    return
  }
  submitting.value = true
  try {
    await createIntegration({
      ...form,
      name: form.name.trim(),
      default_cluster: cluster,
      default_namespace: form.default_namespace?.trim() || undefined,
    })
    drawerVisible.value = false
    await load()
    ElMessage.success('告警接入已创建')
  } catch {
    ElMessage.error('创建失败，请检查名称是否重复')
  } finally {
    submitting.value = false
  }
}

async function changeEnabled(item: AlertIntegration) {
  try {
    const updated = await updateIntegration(item.id, { enabled: item.enabled })
    Object.assign(item, updated)
    ElMessage.success(item.enabled ? '接入已启用' : '接入已停用')
  } catch {
    item.enabled = !item.enabled
    ElMessage.error('状态更新失败')
  }
}

async function changeAutoAnalyze(item: AlertIntegration) {
  try {
    const updated = await updateIntegration(item.id, {
      auto_analyze: item.auto_analyze,
    })
    Object.assign(item, updated)
    ElMessage.success(item.auto_analyze ? '自动分析已开启' : '已切换为人工启动分析')
  } catch {
    item.auto_analyze = !item.auto_analyze
    ElMessage.error('自动分析设置更新失败')
  }
}

async function remove(item: AlertIntegration) {
  try {
    await ElMessageBox.confirm(
      `确定删除告警源“${item.name}”吗？删除后该 Webhook URL 将立即失效，历史告警和分析报告会保留。`,
      '删除告警源',
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
    await deleteIntegration(item.id)
    await load()
    ElMessage.success('告警源已删除')
  } catch {
    ElMessage.error('告警源删除失败')
  } finally {
    deletingId.value = ''
  }
}
</script>

<template>
  <section>
    <header class="page-header">
      <div>
        <h1>告警接入</h1>
        <p class="page-subtitle">
          填写第三方 K8s 集群，生成专属 URL，并配置到该集群的 Alertmanager。
        </p>
      </div>
      <el-button type="primary" :icon="Plus" @click="drawerVisible = true">
        新建接入
      </el-button>
    </header>

    <div class="integration-summary">
      <div>
        <span>接入点</span>
        <strong>{{ integrations.length }}</strong>
      </div>
      <div>
        <span>已启用</span>
        <strong>{{ enabledCount }}</strong>
      </div>
      <div>
        <span>累计接收告警</span>
        <strong>{{ receivedCount }}</strong>
      </div>
    </div>

    <div v-loading="loading" class="integration-list">
      <article v-for="item in integrations" :key="item.id" class="panel integration-card">
        <div class="integration-card-head">
          <div>
            <div class="integration-name">
              <span class="source-logo">A</span>
              <div>
                <h2>{{ item.name }}</h2>
                <p>Alertmanager Webhook</p>
              </div>
            </div>
          </div>
          <div class="integration-head-actions">
            <div class="integration-enabled">
              <span>{{ item.enabled ? '已启用' : '已停用' }}</span>
              <el-switch v-model="item.enabled" @change="changeEnabled(item)" />
            </div>
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
        </div>

        <div class="integration-url">
          <label>Webhook 地址</label>
          <div>
            <code>{{ webhookUrl(item) }}</code>
            <el-button
              :icon="CopyDocument"
              @click="copy(webhookUrl(item), 'Webhook 地址已复制')"
            >
              复制
            </el-button>
          </div>
        </div>

        <div class="integration-info">
          <div>
            <span>关联 K8s 集群</span>
            <strong>{{ item.default_cluster || '-' }}</strong>
          </div>
          <div>
            <span>默认命名空间</span>
            <strong>{{ item.default_namespace || '使用告警标签' }}</strong>
          </div>
          <div>
            <span>已接收</span>
            <strong>{{ item.received_count }} 条</strong>
          </div>
          <div>
            <span>最近接收</span>
            <strong>
              {{
                item.last_received_at
                  ? new Date(item.last_received_at).toLocaleString()
                  : '暂未收到告警'
              }}
            </strong>
          </div>
        </div>

        <div class="integration-card-foot">
          <label>
            <el-switch
              v-model="item.auto_analyze"
              @change="changeAutoAnalyze(item)"
            />
            {{
              item.auto_analyze
                ? '告警到达后自动启动 Agent 分析'
                : '由值班人员确认后启动 Agent 分析'
            }}
          </label>
          <div class="integration-actions">
            <el-button
              text
              :icon="CopyDocument"
              @click="copy(alertmanagerYaml(item), 'Alertmanager 配置已复制')"
            >
              复制 Alertmanager 配置
            </el-button>
          </div>
        </div>
      </article>

      <el-empty
        v-if="!loading && !integrations.length"
        description="还没有告警接入点"
      >
        <el-button type="primary" @click="drawerVisible = true">创建第一个接入</el-button>
      </el-empty>
    </div>

    <el-drawer v-model="drawerVisible" title="新建告警接入" size="500px">
      <p class="drawer-intro">
        填写集群后会生成带独立令牌的 Webhook URL，可直接配置到第三方
        K8s 集群的 Alertmanager。
      </p>
      <el-form label-position="top">
        <el-form-item label="接入名称">
          <el-input v-model="form.name" placeholder="例如：生产环境 Alertmanager" />
        </el-form-item>
        <div class="form-grid">
          <el-form-item label="第三方 K8s 集群">
            <el-input
              v-model="form.default_cluster"
              placeholder="例如：prod-k8s 或 k8s-api.example.com"
            />
          </el-form-item>
          <el-form-item label="默认命名空间（可选）">
            <el-input
              v-model="form.default_namespace"
              placeholder="告警无 namespace 标签时使用"
            />
          </el-form-item>
        </div>
        <el-form-item class="switch-form-item">
          <div>
            <strong>自动分析</strong>
            <span>真实 firing 告警到达后立即采集证据并调用当前模型渠道</span>
          </div>
          <el-switch v-model="form.auto_analyze" />
        </el-form-item>
        <el-form-item class="switch-form-item">
          <div>
            <strong>立即启用</strong>
            <span>停用时 Webhook 会拒绝新的告警请求</span>
          </div>
          <el-switch v-model="form.enabled" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="drawerVisible = false">取消</el-button>
        <el-button type="primary" :loading="submitting" @click="submit">
          创建接入
        </el-button>
      </template>
    </el-drawer>
  </section>
</template>
