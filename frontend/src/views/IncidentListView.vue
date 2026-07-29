<script setup lang="ts">
import { Refresh, Search } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { useRouter } from 'vue-router'

import { listIncidents, type Incident } from '@/api/client'

const router = useRouter()
const loading = ref(false)
const incidents = ref<Incident[]>([])
const search = ref('')
const statusFilter = ref('all')
const pendingCount = computed(
  () => incidents.value.filter((item) => !item.latest_run).length,
)
const runningCount = computed(
  () => incidents.value.filter((item) => item.latest_run?.status === 'running').length,
)
const completedCount = computed(
  () => incidents.value.filter((item) => item.latest_run?.status === 'completed').length,
)
const filteredIncidents = computed(() => {
  const keyword = search.value.trim().toLowerCase()
  return incidents.value.filter((item) => {
    const matchesKeyword =
      !keyword ||
      item.title.toLowerCase().includes(keyword) ||
      item.service.toLowerCase().includes(keyword) ||
      item.cluster?.toLowerCase().includes(keyword)
    const matchesStatus =
      statusFilter.value === 'all' ||
      (statusFilter.value === 'unprocessed' && !item.latest_run) ||
      item.latest_run?.status === statusFilter.value
    return matchesKeyword && matchesStatus
  })
})
let refreshTimer: number | undefined

async function loadIncidents() {
  loading.value = true
  try {
    incidents.value = await listIncidents()
  } catch {
    ElMessage.error('Incident 列表加载失败')
  } finally {
    loading.value = false
  }
}

onMounted(() => {
  void loadIncidents()
  refreshTimer = window.setInterval(() => void loadIncidents(), 10_000)
})

onUnmounted(() => {
  if (refreshTimer !== undefined) window.clearInterval(refreshTimer)
})

function openIncident(row: Incident) {
  void router.push(`/incidents/${row.id}`)
}

function severityType(severity: string) {
  return severity === 'critical' ? 'danger' : severity === 'warning' ? 'warning' : 'info'
}

function runStatusLabel(status?: string) {
  const labels: Record<string, string> = {
    queued: '等待分析',
    running: '分析中',
    completed: '已完成',
    insufficient_evidence: '证据不足',
    failed_final: '失败',
  }
  return status ? labels[status] ?? status : '等待分析'
}
</script>

<template>
  <section>
    <header class="page-header">
      <div>
        <p class="eyebrow">INCIDENT OPERATIONS</p>
        <h1>事件中心</h1>
        <p class="page-subtitle">自动跟踪真实告警、证据采集、根因结论与恢复状态。</p>
      </div>
      <div class="header-actions">
        <el-button :icon="Refresh" circle @click="loadIncidents" />
      </div>
    </header>

    <div class="metric-strip">
      <div class="metric-card">
        <div class="metric-label"><span class="metric-icon blue"></span>全部事件</div>
        <strong>{{ incidents.length }}</strong>
        <small>已接入的 Incident</small>
      </div>
      <div class="metric-card pending">
        <div class="metric-label"><span class="metric-icon amber"></span>等待分析</div>
        <strong>{{ pendingCount }}</strong>
        <small>尚未创建分析任务</small>
      </div>
      <div class="metric-card active">
        <div class="metric-label"><span class="metric-icon amber"></span>分析中</div>
        <strong>{{ runningCount }}</strong>
        <small>Agent 正在调查</small>
      </div>
      <div class="metric-card success">
        <div class="metric-label"><span class="metric-icon green"></span>已完成</div>
        <strong>{{ completedCount }}</strong>
        <small>已生成根因报告</small>
      </div>
    </div>

    <div class="panel table-panel">
      <div class="table-toolbar">
        <div>
          <h2>最近事件</h2>
          <span>按时间倒序展示全部告警调查</span>
        </div>
        <div class="table-filters">
          <el-input
            v-model="search"
            :prefix-icon="Search"
            clearable
            placeholder="搜索事件、服务或集群"
          />
          <el-select v-model="statusFilter">
            <el-option label="全部状态" value="all" />
            <el-option label="等待分析" value="unprocessed" />
            <el-option label="分析中" value="running" />
            <el-option label="已完成" value="completed" />
            <el-option label="证据不足" value="insufficient_evidence" />
          </el-select>
        </div>
      </div>
      <el-table
        v-loading="loading"
        :data="filteredIncidents"
        row-class-name="clickable-row"
        @row-click="openIncident"
      >
        <el-table-column label="事件" min-width="250">
          <template #default="{ row }">
            <div class="incident-title">
              <div>
                <span class="severity-marker" :class="row.severity"></span>
                <strong>{{ row.title }}</strong>
              </div>
              <span>{{ row.cluster || 'default' }} · {{ row.namespace || '-' }}</span>
            </div>
          </template>
        </el-table-column>
        <el-table-column prop="service" label="服务" min-width="150" />
        <el-table-column label="级别" width="100">
          <template #default="{ row }">
            <el-tag :type="severityType(row.severity)" effect="dark">
              {{ row.severity }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="alert_count" label="告警数" width="90" align="center" />
        <el-table-column label="分析状态" width="120">
          <template #default="{ row }">
            <span class="status-pill" :class="row.latest_run?.status">
              <i></i>{{ runStatusLabel(row.latest_run?.status) }}
            </span>
          </template>
        </el-table-column>
        <el-table-column label="开始时间" width="190">
          <template #default="{ row }">
            {{ new Date(row.started_at).toLocaleString() }}
          </template>
        </el-table-column>
      </el-table>
    </div>
  </section>
</template>
