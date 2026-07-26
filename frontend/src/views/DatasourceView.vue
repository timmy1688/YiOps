<script setup lang="ts">
import { Connection, Delete as DeleteIcon, Plus } from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { onMounted, reactive, ref, watch } from 'vue'

import {
  createDatasource,
  deleteDatasource,
  listDatasources,
  testDatasource,
  type Datasource,
  type DatasourceInput,
} from '@/api/client'

const dialogVisible = ref(false)
const submitting = ref(false)
const testingId = ref('')
const deletingId = ref('')
const loading = ref(false)
const datasources = ref<Datasource[]>([])
const form = reactive<
  DatasourceInput & {
    cluster_id: string
    default_namespace: string
    verify_ssl: boolean
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
})

watch(
  () => form.type,
  (type) => {
    form.base_url = type === 'kubernetes' ? 'https://' : 'http://'
  },
)

async function loadDatasources() {
  loading.value = true
  try {
    datasources.value = await listDatasources()
  } catch {
    ElMessage.error('数据源加载失败')
  } finally {
    loading.value = false
  }
}

onMounted(() => void loadDatasources())

async function submit() {
  if (!form.name.trim() || !form.base_url.replace(/^https?:\/\//, '').trim()) {
    ElMessage.warning('请填写名称和数据源地址')
    return
  }
  if (form.type === 'kubernetes' && (!form.cluster_id.trim() || !form.credential?.trim())) {
    ElMessage.warning('Kubernetes 数据源必须填写集群标识和 ServiceAccount Token')
    return
  }
  submitting.value = true
  try {
    await createDatasource({
      name: form.name.trim(),
      type: form.type,
      base_url: form.base_url.trim(),
      enabled: form.enabled,
      credential: form.type === 'kubernetes' ? form.credential?.trim() : undefined,
      ca_cert: form.type === 'kubernetes' ? form.ca_cert?.trim() : undefined,
      settings:
        form.type === 'kubernetes'
          ? {
              cluster_id: form.cluster_id.trim(),
              default_namespace: form.default_namespace.trim(),
              verify_ssl: form.verify_ssl,
            }
          : {},
    })
    dialogVisible.value = false
    await loadDatasources()
    ElMessage.success('数据源已添加')
  } finally {
    submitting.value = false
  }
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
      <el-button type="primary" :icon="Plus" @click="dialogVisible = true">
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
            <el-option label="Prometheus" value="prometheus" />
            <el-option label="Loki" value="loki" />
            <el-option label="Elasticsearch" value="elasticsearch" />
            <el-option label="Kubernetes 集群" value="kubernetes" />
          </el-select>
        </el-form-item>
        <el-form-item :label="form.type === 'kubernetes' ? 'API Server 地址' : '地址'">
          <el-input
            v-model="form.base_url"
            :placeholder="
              form.type === 'kubernetes'
                ? '例如：https://k8s-api.example.com:6443'
                : '例如：http://prometheus:9090'
            "
          />
        </el-form-item>
        <template v-if="form.type === 'kubernetes'">
          <div class="form-grid">
            <el-form-item label="集群标识">
              <el-input
                v-model="form.cluster_id"
                placeholder="必须与告警中的 cluster 一致"
              />
            </el-form-item>
            <el-form-item label="默认 Namespace（可选）">
              <el-input v-model="form.default_namespace" placeholder="留空表示全部" />
            </el-form-item>
          </div>
          <el-form-item label="ServiceAccount Token">
            <el-input
              v-model="form.credential"
              type="password"
              show-password
              placeholder="仅授予 get/list/watch 权限"
            />
          </el-form-item>
          <el-form-item label="CA 证书（PEM，可选）">
            <el-input
              v-model="form.ca_cert"
              type="textarea"
              :rows="5"
              placeholder="-----BEGIN CERTIFICATE-----"
            />
          </el-form-item>
          <el-form-item class="switch-form-item">
            <div>
              <strong>校验 API Server 证书</strong>
              <span>生产环境建议开启；实验环境无 CA 时可关闭</span>
            </div>
            <el-switch v-model="form.verify_ssl" />
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
