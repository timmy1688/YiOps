<script setup lang="ts">
import {
  Connection,
  Download,
  Link,
  Plus,
  Refresh,
  VideoPause,
  VideoPlay,
} from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import { computed, onMounted, onUnmounted, reactive, ref } from 'vue'

import {
  cancelInvestigation,
  createInvestigation,
  getInvestigation,
  investigationEventUrl,
  investigationExportUrl,
  listIncidents,
  listInvestigations,
  resumeInvestigation,
  sendInvestigationMessage,
  shareInvestigation,
  type Incident,
  type Investigation,
  type InvestigationDetail,
} from '@/api/client'
import SafeMarkdown from '@/components/SafeMarkdown.vue'

const investigations = ref<Investigation[]>([])
const incidents = ref<Incident[]>([])
const selected = ref<InvestigationDetail | null>(null)
const loading = ref(false)
const createOpen = ref(false)
const followUp = ref('')
const submitting = ref(false)
const form = reactive({ title: '', question: '', incident_id: '' })
let events: EventSource | null = null
let refreshTimer: number | undefined

const isRunning = computed(() => ['queued', 'running'].includes(selected.value?.status || ''))
const canResume = computed(() => ['cancelled', 'failed'].includes(selected.value?.status || ''))

async function loadList() {
  loading.value = true
  try {
    investigations.value = await listInvestigations()
    const first = investigations.value[0]
    if (!selected.value && first) {
      await selectInvestigation(first)
    }
  } catch {
    ElMessage.error('调查列表加载失败')
  } finally {
    loading.value = false
  }
}

async function loadDetail(id?: string) {
  const target = id || selected.value?.id
  if (!target) return
  selected.value = await getInvestigation(target)
  const index = investigations.value.findIndex((item) => item.id === target)
  if (index >= 0) investigations.value[index] = selected.value
}

async function selectInvestigation(item: Investigation) {
  closeEvents()
  try {
    await loadDetail(item.id)
    if (['queued', 'running'].includes(selected.value?.status || '')) openEvents(item.id)
  } catch {
    ElMessage.error('调查详情加载失败')
  }
}

function openEvents(id: string) {
  closeEvents()
  events = new EventSource(investigationEventUrl(id))
  const refresh = () => void loadDetail(id)
  ;[
    'snapshot',
    'step.started',
    'step.completed',
    'investigation.completed',
    'investigation.cancelled',
    'investigation.failed',
  ].forEach((name) => events?.addEventListener(name, refresh))
}

function closeEvents() {
  events?.close()
  events = null
}

async function submitCreate() {
  if (!form.title.trim() || !form.question.trim()) return
  submitting.value = true
  try {
    const item = await createInvestigation({
      title: form.title.trim(),
      question: form.question.trim(),
      incident_id: form.incident_id || undefined,
    })
    createOpen.value = false
    Object.assign(form, { title: '', question: '', incident_id: '' })
    await loadList()
    await selectInvestigation(item)
    ElMessage.success('调查已创建，Agent 开始取证')
  } catch {
    ElMessage.error('创建调查失败')
  } finally {
    submitting.value = false
  }
}

async function submitFollowUp() {
  if (!selected.value || !followUp.value.trim()) return
  submitting.value = true
  try {
    await sendInvestigationMessage(selected.value.id, followUp.value.trim())
    followUp.value = ''
    await loadDetail()
    openEvents(selected.value.id)
  } catch {
    ElMessage.error('追加分析失败，请确认当前任务已结束')
  } finally {
    submitting.value = false
  }
}

async function cancelCurrent() {
  if (!selected.value) return
  await cancelInvestigation(selected.value.id)
  await loadDetail()
}

async function resumeCurrent() {
  if (!selected.value) return
  await resumeInvestigation(selected.value.id)
  await loadDetail()
  openEvents(selected.value.id)
}

async function shareCurrent() {
  if (!selected.value) return
  const result = await shareInvestigation(selected.value.id)
  const url = `${window.location.origin}${result.share_path}`
  await navigator.clipboard.writeText(url)
  ElMessage.success('只读分享链接已复制')
  await loadDetail()
}

function statusLabel(status: string) {
  return (
    {
      idle: '待提问',
      queued: '排队中',
      running: '调查中',
      completed: '已完成',
      cancelled: '已取消',
      failed: '失败',
    }[status] || status
  )
}

function exportCurrent() {
  if (selected.value) window.location.href = investigationExportUrl(selected.value.id)
}

function formatTime(value: string) {
  return new Date(value).toLocaleString('zh-CN')
}

onMounted(async () => {
  incidents.value = await listIncidents().catch(() => [])
  await loadList()
  refreshTimer = window.setInterval(() => void loadList(), 15_000)
})

onUnmounted(() => {
  closeEvents()
  if (refreshTimer !== undefined) window.clearInterval(refreshTimer)
})
</script>

<template>
  <section>
    <header class="page-header investigation-header">
      <div>
        <p class="eyebrow">PERSISTENT INVESTIGATION</p>
        <h1>根因调查工作台</h1>
        <p class="page-subtitle">围绕假设持续取证，完整保留 Agent 步骤、证据链和对话。</p>
      </div>
      <el-button type="primary" :icon="Plus" @click="createOpen = true">新建调查</el-button>
    </header>

    <div class="investigation-layout">
      <aside class="panel investigation-list" v-loading="loading">
        <header>
          <div><strong>调查记录</strong><span>{{ investigations.length }}</span></div>
          <el-button :icon="Refresh" circle text @click="loadList" />
        </header>
        <button
          v-for="item in investigations"
          :key="item.id"
          type="button"
          :class="{ active: selected?.id === item.id }"
          @click="selectInvestigation(item)"
        >
          <span class="investigation-status" :class="item.status"></span>
          <span>
            <strong>{{ item.title }}</strong>
            <small>{{ statusLabel(item.status) }} · {{ formatTime(item.updated_at) }}</small>
          </span>
        </button>
        <div v-if="!investigations.length" class="empty-list">还没有调查，先创建一个。</div>
      </aside>

      <main v-if="selected" class="investigation-workspace">
        <div class="panel investigation-summary">
          <header>
            <div>
              <span class="status-pill" :class="selected.status"><i></i>{{ statusLabel(selected.status) }}</span>
              <h2>{{ selected.title }}</h2>
              <p>{{ selected.current_step || '等待下一步' }}</p>
            </div>
            <div class="workspace-actions">
              <el-button v-if="isRunning" :icon="VideoPause" @click="cancelCurrent">取消</el-button>
              <el-button v-if="canResume" :icon="VideoPlay" @click="resumeCurrent">继续</el-button>
              <el-button :icon="Link" @click="shareCurrent">分享</el-button>
              <el-button :icon="Download" @click="exportCurrent">导出</el-button>
            </div>
          </header>
          <el-progress
            :percentage="Math.round(selected.progress * 100)"
            :status="selected.status === 'failed' ? 'exception' : selected.status === 'completed' ? 'success' : undefined"
          />
          <div class="run-metrics">
            <span>工具调用 <b>{{ selected.tool_count }}</b></span>
            <span>输入 Token <b>{{ selected.input_tokens }}</b></span>
            <span>输出 Token <b>{{ selected.output_tokens }}</b></span>
            <span>模型 <b>{{ selected.model_name || '-' }}</b></span>
          </div>
        </div>

        <div class="investigation-grid">
          <section class="panel evidence-board">
            <header><strong>假设看板</strong><span>{{ selected.hypotheses.length }}</span></header>
            <article v-for="hypothesis in selected.hypotheses" :key="hypothesis.id">
              <div class="confidence">{{ Math.round(hypothesis.confidence * 100) }}%</div>
              <div><strong>{{ hypothesis.cause }}</strong><small>{{ hypothesis.status }} · 支持证据 {{ hypothesis.supporting_evidence_ids.length }}</small></div>
            </article>
            <p v-if="!selected.hypotheses.length" class="panel-empty">关联 Incident 的结构化报告后会生成假设。</p>
          </section>

          <section class="panel evidence-board">
            <header><strong>证据链</strong><span>{{ selected.evidence.length }}</span></header>
            <article v-for="evidence in selected.evidence.slice(0, 12)" :key="evidence.id">
              <div class="source-chip">{{ evidence.source }}</div>
              <div><strong>{{ evidence.title }}</strong><small>{{ evidence.summary }}</small></div>
            </article>
            <p v-if="!selected.evidence.length" class="panel-empty">Agent 调用数据源后，原始结果将在此沉淀。</p>
          </section>
        </div>

        <section class="panel investigation-timeline">
          <header><strong>调查时间线</strong><span>可审计执行轨迹</span></header>
          <div v-for="step in selected.steps" :key="step.id" class="timeline-step">
            <Connection />
            <div><strong>{{ step.description || step.name }}</strong><small>{{ step.source }} · {{ step.result_count }} 条 · {{ step.duration_ms }} ms</small></div>
            <span :class="step.status">{{ step.status }}</span>
          </div>
          <p v-if="!selected.steps.length" class="panel-empty">等待 Agent 开始执行查询。</p>
        </section>

        <section class="panel investigation-conversation">
          <header><strong>分析对话</strong><span>结论必须可追溯到上方证据</span></header>
          <article v-for="message in selected.messages" :key="message.id" :class="message.role">
            <b>{{ message.role === 'user' ? '你' : 'YiOps Agent' }}</b>
            <SafeMarkdown v-if="message.role === 'assistant'" :content="message.content" />
            <p v-else>{{ message.content }}</p>
          </article>
          <div v-if="!isRunning" class="follow-up">
            <el-input v-model="followUp" type="textarea" :rows="2" placeholder="继续追问、提出反证或指定数据源……" />
            <el-button type="primary" :loading="submitting" @click="submitFollowUp">继续调查</el-button>
          </div>
        </section>
      </main>

      <div v-else class="panel investigation-empty">选择一条调查，或创建新的根因分析任务。</div>
    </div>

    <el-dialog v-model="createOpen" title="创建根因调查" width="560px">
      <el-form label-position="top">
        <el-form-item label="调查标题">
          <el-input v-model="form.title" maxlength="500" placeholder="例如：支付 API 5xx 突增" />
        </el-form-item>
        <el-form-item label="关联 Incident（可选）">
          <el-select v-model="form.incident_id" clearable filterable placeholder="选择现有故障">
            <el-option v-for="incident in incidents" :key="incident.id" :label="incident.title" :value="incident.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="要验证的问题">
          <el-input v-model="form.question" type="textarea" :rows="5" maxlength="8000" placeholder="描述现象、时间范围，以及希望 Agent 验证的假设。" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="createOpen = false">取消</el-button>
        <el-button type="primary" :loading="submitting" @click="submitCreate">开始调查</el-button>
      </template>
    </el-dialog>
  </section>
</template>

<style scoped>
.investigation-layout { display: grid; grid-template-columns: 290px minmax(0, 1fr); gap: 16px; align-items: start; }
.investigation-list { position: sticky; top: 78px; overflow: hidden; }
.investigation-list > header, .evidence-board > header, .investigation-timeline > header, .investigation-conversation > header { display: flex; align-items: center; justify-content: space-between; padding: 15px 17px; border-bottom: 1px solid var(--line-soft); }
.investigation-list header div { display: flex; gap: 8px; align-items: center; }
.investigation-list header span, .evidence-board header span { color: var(--subtle); font-size: 10px; }
.investigation-list > button { display: flex; width: 100%; gap: 11px; padding: 14px 16px; border: 0; border-top: 1px solid var(--line-soft); text-align: left; background: #fff; cursor: pointer; }
.investigation-list > button:hover, .investigation-list > button.active { background: #f5f7ff; }
.investigation-list > button.active { box-shadow: inset 3px 0 var(--primary); }
.investigation-list button > span:last-child { min-width: 0; }
.investigation-list button strong, .investigation-list button small { display: block; }
.investigation-list button strong { overflow: hidden; color: var(--text); font-size: 12px; text-overflow: ellipsis; white-space: nowrap; }
.investigation-list button small { margin-top: 6px; color: var(--subtle); font-size: 9px; }
.investigation-status { flex: 0 0 auto; width: 7px; height: 7px; margin-top: 4px; border-radius: 50%; background: #98a2b3; }
.investigation-status.running, .investigation-status.queued { background: var(--amber); box-shadow: 0 0 0 4px var(--amber-soft); }
.investigation-status.completed { background: var(--green); }
.investigation-status.failed { background: var(--red); }
.empty-list, .investigation-empty, .panel-empty { padding: 30px 18px; color: var(--subtle); font-size: 11px; text-align: center; }
.investigation-workspace { display: grid; gap: 15px; min-width: 0; }
.investigation-summary { padding: 20px; }
.investigation-summary > header { display: flex; justify-content: space-between; gap: 20px; margin-bottom: 17px; }
.investigation-summary h2 { margin: 10px 0 5px; font-size: 20px; }
.investigation-summary p { margin: 0; color: var(--muted); font-size: 11px; }
.workspace-actions { display: flex; align-items: flex-start; gap: 7px; }
.run-metrics { display: flex; gap: 28px; padding-top: 15px; color: var(--muted); font-size: 10px; }
.run-metrics b { margin-left: 5px; color: var(--text); }
.investigation-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 15px; }
.evidence-board { overflow: hidden; }
.evidence-board article { display: flex; gap: 12px; padding: 14px 17px; border-top: 1px solid var(--line-soft); }
.evidence-board article:first-of-type { border-top: 0; }
.evidence-board article > div:last-child { min-width: 0; }
.evidence-board article strong, .evidence-board article small { display: block; }
.evidence-board article strong { color: #344054; font-size: 11px; }
.evidence-board article small { display: -webkit-box; overflow: hidden; margin-top: 5px; color: var(--muted); font-size: 9px; line-height: 1.45; -webkit-box-orient: vertical; -webkit-line-clamp: 2; }
.confidence { flex: 0 0 auto; color: var(--primary); font-size: 15px; font-weight: 750; }
.source-chip { flex: 0 0 auto; height: 21px; padding: 4px 7px; border-radius: 5px; color: #3855b3; background: var(--primary-soft); font-size: 8px; text-transform: uppercase; }
.investigation-timeline { overflow: hidden; }
.investigation-timeline header span, .investigation-conversation header span { color: var(--subtle); font-size: 9px; }
.timeline-step { display: grid; grid-template-columns: 20px minmax(0, 1fr) auto; gap: 10px; align-items: center; padding: 12px 17px; border-top: 1px solid var(--line-soft); }
.timeline-step svg { width: 15px; color: var(--primary); }
.timeline-step strong, .timeline-step small { display: block; }
.timeline-step strong { font-size: 11px; }
.timeline-step small { margin-top: 4px; color: var(--subtle); font-size: 9px; }
.timeline-step > span { color: var(--muted); font-size: 9px; }
.timeline-step > span.completed { color: var(--green); }
.timeline-step > span.failed { color: var(--red); }
.investigation-conversation { overflow: hidden; }
.investigation-conversation article { padding: 17px 20px; border-top: 1px solid var(--line-soft); }
.investigation-conversation article.user { background: #fafbfc; }
.investigation-conversation article > b { color: var(--primary); font-size: 10px; }
.investigation-conversation article > p { margin: 9px 0 0; color: #344054; font-size: 12px; line-height: 1.65; white-space: pre-wrap; }
.follow-up { display: flex; gap: 10px; align-items: flex-end; padding: 16px; border-top: 1px solid var(--line-soft); }
.follow-up .el-button { height: 54px; }
@media (max-width: 1200px) { .investigation-layout { grid-template-columns: 240px minmax(0, 1fr); } .investigation-grid { grid-template-columns: 1fr; } .workspace-actions { flex-wrap: wrap; } }
</style>
