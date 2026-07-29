<script setup lang="ts">
import { ArrowLeft, Cpu, DocumentChecked, VideoPlay } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import {
  analysisEventUrl,
  getIncident,
  getReport,
  getRun,
  listEvidence,
  listToolExecutions,
  startAnalysis,
  type AnalysisRun,
  type Evidence,
  type Incident,
  type RootCauseReport,
  type ToolExecution,
} from '@/api/client'

const route = useRoute()
const router = useRouter()
const incident = ref<Incident>()
const run = ref<AnalysisRun>()
const evidence = ref<Evidence[]>([])
const tools = ref<ToolExecution[]>([])
const report = ref<RootCauseReport>()
const loading = ref(true)
const starting = ref(false)
let source: EventSource | undefined
let timer: number | undefined

const incidentId = computed(() => String(route.params.id))
const steps = [
  { key: 'normalize', title: '告警标准化' },
  { key: 'plan', title: '调查规划' },
  { key: 'collect', title: '并行采集' },
  { key: 'compress', title: '证据压缩' },
  { key: 'refine', title: '缺口补证' },
  { key: 'analyze', title: '根因分析' },
  { key: 'validate', title: '报告验证' },
  { key: 'save', title: '完成' },
]
const activeStep = computed(() => {
  if (!run.value?.current_step) return 0
  return Math.max(0, steps.findIndex((step) => step.key === run.value?.current_step))
})

async function loadAll() {
  incident.value = await getIncident(incidentId.value)
  if (incident.value.latest_run) {
    run.value = await getRun(incident.value.latest_run.id)
    await loadResults()
    if (['queued', 'running'].includes(run.value.status)) connectEvents(run.value.id)
  }
  loading.value = false
}

async function loadResults() {
  if (!run.value) return
  evidence.value = await listEvidence(run.value.id)
  tools.value = await listToolExecutions(run.value.id)
  if (['completed', 'insufficient_evidence'].includes(run.value.status)) {
    report.value = await getReport(run.value.id)
  }
}

async function start() {
  starting.value = true
  try {
    run.value = await startAnalysis(incidentId.value)
    report.value = undefined
    evidence.value = []
    tools.value = []
    connectEvents(run.value.id)
    ElMessage.success('分析已启动')
  } finally {
    starting.value = false
  }
}

function connectEvents(runId: string) {
  source?.close()
  source = new EventSource(analysisEventUrl(runId))
  const update = async () => {
    run.value = await getRun(runId)
    await loadResults()
  }
  for (const event of ['snapshot', 'node.started', 'node.completed', 'evidence.created']) {
    source.addEventListener(event, update)
  }
  source.addEventListener('report.completed', async () => {
    await update()
    source?.close()
  })
  source.addEventListener('run.failed', async () => {
    await update()
    source?.close()
  })
}

function evidenceById(id: string) {
  return evidence.value.find((item) => item.id === id)
}

function confidenceColor(value: number) {
  if (value >= 0.8) return '#24c78e'
  if (value >= 0.6) return '#f0ad4e'
  return '#ef6b73'
}

function displayValue(value: unknown) {
  if (typeof value !== 'number') return String(value)
  if (Math.abs(value) < 1 && value !== 0) return `${(value * 100).toFixed(1)}%`
  return Number.isInteger(value) ? String(value) : value.toFixed(2)
}

function evidenceValues(item: Evidence) {
  return Object.entries(item.values)
    .filter(([key, value]) => key !== 'samples' && typeof value === 'number')
    .slice(0, 3)
}

watch(incidentId, loadAll, { immediate: true })
timer = window.setInterval(async () => {
  if (run.value && ['queued', 'running'].includes(run.value.status)) {
    run.value = await getRun(run.value.id)
  }
}, 5000)
onBeforeUnmount(() => {
  source?.close()
  if (timer) window.clearInterval(timer)
})
</script>

<template>
  <section v-loading="loading">
    <header class="page-header detail-header">
      <div>
        <el-button class="back-button" text :icon="ArrowLeft" @click="router.push('/incidents')">
          返回事件中心
        </el-button>
        <h1>{{ incident?.title }}</h1>
        <div class="incident-meta">
          <span class="meta-severity" :class="incident?.severity">{{ incident?.severity }}</span>
          <span>{{ incident?.cluster || 'default' }}</span>
          <span>{{ incident?.namespace || '-' }}</span>
          <span>{{ incident?.service }}</span>
        </div>
      </div>
      <el-button
        type="primary"
        size="large"
        :icon="VideoPlay"
        :loading="starting"
        :disabled="run ? ['queued', 'running'].includes(run.status) : false"
        @click="start"
      >
        {{ run ? '重新分析' : '开始分析' }}
      </el-button>
    </header>

    <div v-if="incident?.is_test" class="test-alert-notice">
      <strong>模拟告警触发</strong>
      <p>
        这条告警用于验证分析流程，并非监控系统检测到的真实故障。下方 Pod、Event、指标和日志来自真实集群，只表示调查时发现的实际状态。
      </p>
    </div>

    <article v-if="incident && !run" class="panel review-pending-card">
      <div class="review-pending-icon">!</div>
      <div>
        <span>等待人工判断</span>
        <h2>告警已接收，Agent 尚未开始调查</h2>
        <p>
          请先根据告警级别、服务和集群信息判断是否值得分析。点击“开始分析”后，系统才会查询指标、日志和 Kubernetes 事件。
        </p>
      </div>
      <el-button
        type="primary"
        size="large"
        :icon="VideoPlay"
        :loading="starting"
        @click="start"
      >
        开始分析
      </el-button>
    </article>

    <article v-if="report" class="panel conclusion-card">
      <div class="conclusion-head">
        <div>
          <span class="conclusion-label">
            <i :class="{ healthy: !report.hypotheses.length }"></i>
            {{ report.hypotheses.length ? '已定位可能原因' : '当前未发现活动故障' }}
          </span>
          <h2>{{ report.summary }}</h2>
        </div>
        <div class="confidence-box">
          <strong :style="{ color: confidenceColor(report.confidence) }">
            {{ Math.round(report.confidence * 100) }}%
          </strong>
          <span>结论置信度</span>
        </div>
      </div>

      <div class="conclusion-body">
        <div class="cause-section">
          <h3>{{ incident?.is_test ? '同时段调查发现' : '原因判断' }}</h3>
          <div
            v-for="hypothesis in report.hypotheses"
            :key="hypothesis.cause"
            class="cause-item"
          >
            <DocumentChecked />
            <div>
              <strong>{{ hypothesis.cause }}</strong>
              <p>该判断由 {{ hypothesis.supporting_evidence_ids.length }} 条证据支持</p>
              <p v-if="hypothesis.missing_evidence.length" class="evidence-boundary">
                证据边界：{{ hypothesis.missing_evidence.join('；') }}
              </p>
              <div class="evidence-links">
                <el-popover
                  v-for="id in hypothesis.supporting_evidence_ids"
                  :key="id"
                  placement="top"
                  :width="420"
                  trigger="click"
                >
                  <template #reference>
                    <button>{{ evidenceById(id)?.title || '查看证据' }}</button>
                  </template>
                  <strong>{{ evidenceById(id)?.title }}</strong>
                  <p>{{ evidenceById(id)?.summary }}</p>
                </el-popover>
              </div>
            </div>
          </div>
          <p v-if="!report.hypotheses.length" class="healthy-copy">
            已采集的指标没有形成可归因的故障证据。可以继续观察，或补充日志和事件后重新分析。
          </p>
        </div>

        <div class="next-actions">
          <h3>建议处理</h3>
          <ol>
            <li v-for="action in report.recommended_actions" :key="action">{{ action }}</li>
          </ol>
        </div>
      </div>
    </article>

    <div v-if="run && !report" class="panel analysis-running">
      <div>
        <span class="running-spinner"></span>
        <div>
          <h2>{{ run.error_message ? '分析未完成' : 'Agent 正在分析' }}</h2>
          <p>
            {{ run.error_message || `当前步骤：${steps[activeStep]?.title || '准备中'}` }}
          </p>
        </div>
      </div>
      <strong>{{ Math.round(run.progress * 100) }}%</strong>
    </div>

    <div v-if="run" class="detail-content-grid">
      <section class="panel evidence-section">
        <div class="section-heading">
          <div>
            <h2>判断依据</h2>
            <p>共 {{ evidence.length }} 条经过压缩和去重的证据</p>
          </div>
          <span class="real-data-badge"><i></i> 真实数据</span>
        </div>

        <div v-if="evidence.length" class="evidence-list">
          <article v-for="item in evidence" :key="item.id" class="evidence-row">
            <div class="evidence-source">
              <el-icon><Cpu /></el-icon>
              <span>{{ item.source }}</span>
            </div>
            <div class="evidence-main">
              <div>
                <h3>{{ item.title }}</h3>
                <span class="quality-badge">可信度 {{ Math.round(item.quality * 100) }}%</span>
              </div>
              <p>{{ item.summary }}</p>
              <div v-if="evidenceValues(item).length" class="evidence-values">
                <div v-for="[key, value] in evidenceValues(item)" :key="key">
                  <span>{{ key.replaceAll('_', ' ') }}</span>
                  <strong>{{ displayValue(value) }}</strong>
                </div>
              </div>
            </div>
          </article>
        </div>
        <el-empty v-else description="尚未生成有效证据" />
      </section>

      <aside class="detail-side">
        <section class="panel process-section">
          <div class="section-heading">
            <div>
              <h2>分析过程</h2>
              <p>{{ run.model_name }}</p>
            </div>
          </div>
          <div class="process-list">
            <div
              v-for="(step, index) in steps"
              :key="step.key"
              :class="{ done: index <= activeStep }"
            >
              <i>{{ index < activeStep || run.status === 'completed' ? '✓' : index + 1 }}</i>
              <span>{{ step.title }}</span>
            </div>
          </div>
        </section>

        <section class="panel tool-summary">
          <div class="section-heading">
            <div>
              <h2>工具调用</h2>
              <p>{{ tools.length }} 次只读查询</p>
            </div>
          </div>
          <div class="tool-list">
            <div v-for="tool in tools" :key="tool.id">
              <span>{{ tool.source }} · {{ tool.template_id }}</span>
              <b :class="tool.status">{{ tool.status === 'completed' ? '成功' : '失败' }}</b>
            </div>
          </div>
        </section>
      </aside>
    </div>

    <el-empty v-if="!loading && !run" description="还没有分析记录">
      <el-button type="primary" @click="start">开始第一次分析</el-button>
    </el-empty>
  </section>
</template>
