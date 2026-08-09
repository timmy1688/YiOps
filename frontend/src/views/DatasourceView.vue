<script setup lang="ts">
import { Connection, Delete as DeleteIcon, EditPen, Plus } from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { nextTick, onMounted, reactive, ref, watch } from 'vue'

import {
  createDatasource,
  deleteDatasource,
  listConnectorTypes,
  listDatasources,
  testDatasource,
  updateDatasource,
  type ConnectorType,
  type Datasource,
  type DatasourceInput,
} from '@/api/client'

const dialogVisible = ref(false)
const editingId = ref('')
const submitting = ref(false)
const testingId = ref('')
const deletingId = ref('')
const loading = ref(false)
const datasources = ref<Datasource[]>([])
const connectorTypes = ref<ConnectorType[]>([])
const form = reactive<
  DatasourceInput & {
    cluster_id: string
    default_namespace: string
    tenant_id: string
    index_alias: string
    verify_ssl: boolean
  }
>({
  name: '',
  type: 'prometheus',
  base_url: 'http://prometheus:9090',
  auth_type: 'none',
  username: '',
  enabled: true,
  credential: '',
  cluster_id: '',
  default_namespace: '',
  tenant_id: '',
  index_alias: 'logs-*',
  verify_ssl: true,
})

const nativeEndpoints: Record<Datasource['type'], string> = {
  prometheus: 'http://prometheus:9090',
  loki: 'http://loki:3100',
  tempo: 'http://tempo:3200',
  elasticsearch: 'http://elasticsearch:9200',
  kubernetes: 'https://kubernetes.default.svc',
}

function defaultEndpoint() {
  return nativeEndpoints[form.type]
}

watch(
  () => form.type,
  () => {
    form.base_url = defaultEndpoint()
  },
)

async function loadDatasources() {
  loading.value = true
  try {
    const [items, connectors] = await Promise.all([
      listDatasources(),
      listConnectorTypes(),
    ])
    datasources.value = items
    connectorTypes.value = connectors
  } catch {
    ElMessage.error('数据源加载失败')
  } finally {
    loading.value = false
  }
}

onMounted(() => void loadDatasources())

async function submit() {
  if (!form.name.trim()) {
    ElMessage.warning('请填写数据源名称')
    return
  }
  if (!form.base_url?.replace(/^https?:\/\//, '').trim()) {
    ElMessage.warning('请填写数据源地址')
    return
  }
  if (form.type === 'kubernetes' && !form.cluster_id.trim()) {
    ElMessage.warning('请填写 Kubernetes 集群标识')
    return
  }
  submitting.value = true
  try {
    const payload: DatasourceInput = {
      name: form.name.trim(),
      type: form.type,
      base_url: form.base_url?.trim(),
      auth_type: form.auth_type,
      username: form.auth_type === 'basic' ? form.username?.trim() : undefined,
      credential: form.credential?.trim() || undefined,
      enabled: form.enabled,
      settings: {
        ...(['prometheus', 'loki', 'tempo'].includes(form.type) && form.tenant_id.trim()
          ? { tenant_id: form.tenant_id.trim() }
          : {}),
        ...(form.type === 'elasticsearch'
          ? { index_alias: form.index_alias.trim() || 'logs-*' }
          : {}),
        ...(form.type === 'kubernetes'
          ? {
              cluster_id: form.cluster_id.trim(),
              default_namespace: form.default_namespace.trim(),
              verify_ssl: form.verify_ssl,
            }
          : {}),
      },
    }
    if (editingId.value) {
      await updateDatasource(editingId.value, payload)
    } else {
      await createDatasource(payload)
    }
    dialogVisible.value = false
    await loadDatasources()
    ElMessage.success(editingId.value ? '数据源已更新' : '数据源已添加')
  } catch (error) {
    const detail = (error as { response?: { data?: { detail?: string } } }).response?.data
      ?.detail
    ElMessage.error(detail || '数据源添加失败')
  } finally {
    submitting.value = false
  }
}

function openCreate() {
  editingId.value = ''
  Object.assign(form, {
    name: '',
    type: 'prometheus',
    base_url: nativeEndpoints.prometheus,
    auth_type: 'none',
    username: '',
    enabled: true,
    credential: '',
    cluster_id: '',
    default_namespace: '',
    tenant_id: '',
    index_alias: 'logs-*',
    verify_ssl: true,
  })
  dialogVisible.value = true
}

async function openEdit(item: Datasource) {
  editingId.value = item.id
  Object.assign(form, {
    name: item.name,
    type: item.type,
    enabled: item.enabled,
    auth_type: item.auth_type,
    username: item.username || '',
    credential: '',
    cluster_id: String(item.settings.cluster_id || ''),
    default_namespace: String(item.settings.default_namespace || ''),
    tenant_id: String(item.settings.tenant_id || ''),
    index_alias: String(item.settings.index_alias || 'logs-*'),
    verify_ssl: item.settings.verify_ssl !== false,
  })
  await nextTick()
  form.base_url = item.base_url
  dialogVisible.value = true
}

async function test(item: Datasource) {
  testingId.value = item.id
  try {
    const result = await testDatasource(item.id)
    await loadDatasources()
    result.ok ? ElMessage.success('连接成功') : ElMessage.error(result.message)
  } finally {
    testingId.value = ''
  }
}

async function remove(item: Datasource) {
  try {
    await ElMessageBox.confirm(
      `确定删除数据源“${item.name}”吗？删除后新的分析将无法再查询该数据源，历史证据和报告会保留。`,
      '删除数据源',
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
    await deleteDatasource(item.id)
    await loadDatasources()
    ElMessage.success('数据源已删除')
  } catch {
    ElMessage.error('数据源删除失败')
  } finally {
    deletingId.value = ''
  }
}
</script>

<template>
  <section>
    <header class="page-header">
      <div>
        <p class="eyebrow">OBSERVABILITY SOURCES</p>
        <h1>数据源</h1>
        <p class="page-subtitle">所有连接器均以只读方式访问，模型无法获得凭据。</p>
      </div>
      <el-button type="primary" :icon="Plus" @click="openCreate">
        添加数据源
      </el-button>
    </header>

    <div v-loading="loading" class="datasource-grid">
      <article
        v-for="item in datasources"
        :key="item.id"
        class="panel datasource-card"
      >
        <div class="datasource-icon" :class="item.type">
          <Connection />
        </div>
        <div class="datasource-copy">
          <div class="datasource-title">
            <h3>{{ item.name }}</h3>
            <el-tag :type="item.last_test_status === 'healthy' ? 'success' : 'info'">
              {{ item.last_test_status || '未测试' }}
            </el-tag>
          </div>
          <span>
            {{ item.type }}
            <template v-if="item.type === 'kubernetes'">
              · {{ item.settings.cluster_id }}
            </template>
            <template v-if="item.type === 'tempo' && item.settings.tenant_id">
              · tenant {{ item.settings.tenant_id }}
            </template>
          </span>
          <code>{{ item.base_url }}</code>
          <small>凭据：{{ item.secret_configured ? '已配置' : '未配置' }}</small>
          <small>MCP：外部只读服务</small>
        </div>
        <div class="datasource-actions">
          <el-button
            :loading="testingId === item.id"
            :disabled="!item.enabled"
            @click="test(item)"
          >
            测试连接
          </el-button>
          <el-button plain :icon="EditPen" @click="openEdit(item)">
            编辑
          </el-button>
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
        v-if="!loading && !datasources.length"
        description="还没有数据源；模拟模式下仍可运行完整分析"
      />
    </div>

    <el-drawer
      v-model="dialogVisible"
      :title="editingId ? '更新数据源' : '添加数据源'"
      size="480px"
    >
      <p class="drawer-intro">填写原生数据源 API 地址；查询统一由内部 yiops-mcp 以只读方式执行。</p>
      <el-form label-position="top">
        <el-form-item label="名称"><el-input v-model="form.name" /></el-form-item>
        <el-form-item label="类型">
          <el-select v-model="form.type" :disabled="Boolean(editingId)">
            <el-option
              v-for="connector in connectorTypes"
              :key="connector.type"
              :label="connector.display_name"
              :value="connector.type"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="原生 API 地址">
          <el-input
            v-model="form.base_url"
            :placeholder="defaultEndpoint()"
          />
        </el-form-item>
        <template v-if="['prometheus', 'loki', 'tempo'].includes(form.type)">
          <el-form-item label="租户 ID（可选）">
            <el-input v-model="form.tenant_id" placeholder="作为 X-Scope-OrgID 发送" />
          </el-form-item>
        </template>
        <el-form-item v-if="form.type === 'elasticsearch'" label="索引模式">
          <el-input v-model="form.index_alias" placeholder="logs-*" />
        </el-form-item>
        <template v-if="form.type === 'kubernetes'">
          <el-form-item label="集群标识">
            <el-input v-model="form.cluster_id" placeholder="例如：prod-cn" />
          </el-form-item>
          <el-form-item label="默认 Namespace（可选）">
            <el-input v-model="form.default_namespace" placeholder="留空表示全局" />
          </el-form-item>
          <el-form-item label="校验 TLS 证书">
            <el-switch v-model="form.verify_ssl" />
          </el-form-item>
        </template>
        <el-form-item label="认证方式">
          <el-select v-model="form.auth_type">
            <el-option label="无认证" value="none" />
            <el-option label="Bearer Token" value="bearer" />
            <el-option label="Basic Auth" value="basic" />
            <el-option label="API Key" value="api_key" />
          </el-select>
        </el-form-item>
        <el-form-item v-if="form.auth_type === 'basic'" label="用户名">
          <el-input v-model="form.username" autocomplete="username" />
        </el-form-item>
        <el-form-item
          v-if="form.auth_type !== 'none'"
          :label="editingId ? '凭据（留空则保持不变）' : form.auth_type === 'basic' ? '密码' : '凭据'"
        >
          <el-input
            v-model="form.credential"
            type="password"
            show-password
            autocomplete="new-password"
          />
        </el-form-item>
        <el-form-item><el-switch v-model="form.enabled" />&nbsp;启用</el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="submitting" @click="submit">
          {{ editingId ? '更新' : '保存' }}
        </el-button>
      </template>
    </el-drawer>
  </section>
</template>
