<script setup lang="ts">
import { Connection, Delete as DeleteIcon, Plus, UploadFilled } from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox, type UploadFile } from 'element-plus'
import { onMounted, reactive, ref, watch } from 'vue'

import {
  createDatasource,
  deleteDatasource,
  listConnectorTypes,
  listDatasources,
  testDatasource,
  type ConnectorType,
  type Datasource,
  type DatasourceInput,
} from '@/api/client'

const dialogVisible = ref(false)
const submitting = ref(false)
const testingId = ref('')
const deletingId = ref('')
const loading = ref(false)
const datasources = ref<Datasource[]>([])
const connectorTypes = ref<ConnectorType[]>([])
const kubeconfigFilename = ref('')
const form = reactive<
  DatasourceInput & {
    cluster_id: string
    default_namespace: string
    verify_ssl: boolean
    kubeconfig: string
  }
>({
  name: '',
  type: 'prometheus',
  base_url: 'http://',
  enabled: true,
  credential: '',
  ca_cert: '',
  cluster_id: '',
  default_namespace: '',
  verify_ssl: true,
  kubeconfig: '',
})

watch(
  () => form.type,
  (type) => {
    form.base_url = type === 'kubernetes' ? '' : 'http://'
    if (type !== 'kubernetes') {
      form.kubeconfig = ''
      kubeconfigFilename.value = ''
    }
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
  if (form.type === 'kubernetes' && !form.kubeconfig.trim()) {
    ElMessage.warning('请选择 kubeconfig 文件')
    return
  }
  if (
    form.type !== 'kubernetes' &&
    !form.base_url?.replace(/^https?:\/\//, '').trim()
  ) {
    ElMessage.warning('请填写数据源地址')
    return
  }
  submitting.value = true
  try {
    await createDatasource({
      name: form.name.trim(),
      type: form.type,
      base_url: form.type === 'kubernetes' ? undefined : form.base_url?.trim(),
      kubeconfig: form.type === 'kubernetes' ? form.kubeconfig : undefined,
      enabled: form.enabled,
      settings: {},
    })
    dialogVisible.value = false
    await loadDatasources()
    ElMessage.success('数据源已添加')
  } catch (error) {
    const detail = (error as { response?: { data?: { detail?: string } } }).response?.data
      ?.detail
    ElMessage.error(detail || '数据源添加失败')
  } finally {
    submitting.value = false
  }
}

async function selectKubeconfig(file: UploadFile) {
  if (!file.raw) return
  if (file.raw.size > 1_000_000) {
    ElMessage.error('kubeconfig 文件不能超过 1 MB')
    return
  }
  form.kubeconfig = await file.raw.text()
  kubeconfigFilename.value = file.name
}

function openCreate() {
  Object.assign(form, {
    name: '',
    type: 'prometheus',
    base_url: 'http://',
    enabled: true,
    credential: '',
    ca_cert: '',
    cluster_id: '',
    default_namespace: '',
    verify_ssl: true,
    kubeconfig: '',
  })
  kubeconfigFilename.value = ''
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
          </span>
          <code>{{ item.base_url }}</code>
          <small>凭据：{{ item.secret_configured ? '已配置' : '未配置' }}</small>
        </div>
        <div class="datasource-actions">
          <el-button
            :loading="testingId === item.id"
            :disabled="!item.enabled"
            @click="test(item)"
          >
            测试连接
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

    <el-drawer v-model="dialogVisible" title="添加数据源" size="480px">
      <p class="drawer-intro">数据源仅用于受控的只读查询，不会向模型暴露凭据。</p>
      <el-form label-position="top">
        <el-form-item label="名称"><el-input v-model="form.name" /></el-form-item>
        <el-form-item label="类型">
          <el-select v-model="form.type">
            <el-option
              v-for="connector in connectorTypes"
              :key="connector.type"
              :label="connector.display_name"
              :value="connector.type"
            />
          </el-select>
        </el-form-item>
        <el-form-item v-if="form.type !== 'kubernetes'" label="地址">
          <el-input v-model="form.base_url" placeholder="例如：http://prometheus:9090" />
        </el-form-item>
        <template v-if="form.type === 'kubernetes'">
          <el-form-item label="kubeconfig 文件">
            <el-upload
              class="kubeconfig-upload"
              drag
              accept=".yaml,.yml,.conf"
              :auto-upload="false"
              :on-change="selectKubeconfig"
              :show-file-list="false"
            >
              <el-icon class="el-icon--upload"><UploadFilled /></el-icon>
              <div class="el-upload__text">
                拖入 kubeconfig，或<em>点击选择</em>
              </div>
              <template #tip>
                <div class="el-upload__tip">
                  自动读取当前 context、API Server 和凭据，最大 1 MB
                </div>
              </template>
            </el-upload>
            <div v-if="kubeconfigFilename" class="selected-kubeconfig">
              <Connection />
              <span>{{ kubeconfigFilename }}</span>
              <b>已读取</b>
            </div>
          </el-form-item>
        </template>
        <el-form-item><el-switch v-model="form.enabled" />&nbsp;启用</el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="submitting" @click="submit">保存</el-button>
      </template>
    </el-drawer>
  </section>
</template>
