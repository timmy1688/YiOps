<script setup lang="ts">
import { Download, Refresh, VideoPlay } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import { computed, onMounted, ref } from 'vue'

import {
  createEvaluationRun,
  importOfficialDemos,
  listEvaluationRuns,
  previewEvaluation,
  type EvaluationReport,
  type EvaluationScenarioResult,
} from '@/api/client'

const report = ref<EvaluationReport | null>(null)
const runs = ref<EvaluationReport[]>([])
const loading = ref(false)
const running = ref(false)
const importing = ref(false)
const category = ref('all')

const categories = computed(() => Object.keys(report.value?.categories || {}))
const rows = computed(() => {
  if (category.value === 'all') return report.value?.results || []
  return (report.value?.results || []).filter((item) => item.category === category.value)
})

function percent(value?: number) {
  return `${Math.round((value || 0) * 100)}%`
}

function categoryTop1(name: string) {
  return report.value?.categories[name]?.root_cause_top1 || 0
}

function categoryLabel(value: string) {
  return ({
    configuration: '配置', database: '数据库', kubernetes: 'Kubernetes', resource: '资源',
    dependency: '依赖', network: '网络', deployment: '发布',
  } as Record<string, string>)[value] || value
}

function rowClass({ row }: { row: EvaluationScenarioResult }) {
  return row.metrics.root_cause_top1 === 1 ? 'eval-pass' : 'eval-fail'
}

async function load() {
  loading.value = true
  try {
    const [preview, history] = await Promise.all([previewEvaluation(), listEvaluationRuns()])
    runs.value = history
    report.value = history[0] || preview
  } catch {
    ElMessage.error('评测数据加载失败')
  } finally {
    loading.value = false
  }
}

async function run() {
  running.value = true
  try {
    const result = await createEvaluationRun()
    report.value = result
    runs.value = [result, ...runs.value.filter((item) => item.id !== result.id)]
    ElMessage.success(`已完成 ${result.scenario_count} 个 RCA 场景评测`)
  } catch {
    ElMessage.error('评测执行失败')
  } finally {
    running.value = false
  }
}

async function importDemos() {
  importing.value = true
  try {
    const result = await importOfficialDemos()
    if (result.created_incident_ids.length) {
      ElMessage.success(`已导入 ${result.created_incident_ids.length} 个官方 RCA Demo`)
    } else {
      ElMessage.info('官方 Demo 已存在，无需重复导入')
    }
  } catch {
    ElMessage.error('官方 Demo 导入失败')
  } finally {
    importing.value = false
  }
}

onMounted(load)
</script>

<template>
  <section v-loading="loading">
    <header class="page-header evaluation-header">
      <div>
        <p class="eyebrow">RCA BENCHMARK</p>
        <h1>RCA 评测中心</h1>
        <p class="page-subtitle">用固定场景持续衡量根因命中、证据质量、幻觉率、延迟与成本。</p>
      </div>
      <div class="header-actions">
        <el-button :icon="Refresh" circle @click="load" />
        <el-button :icon="Download" :loading="importing" @click="importDemos">导入官方 Demo</el-button>
        <el-button type="primary" :icon="VideoPlay" :loading="running" @click="run">运行基准评测</el-button>
      </div>
    </header>

    <template v-if="report">
      <div class="metric-strip evaluation-metrics">
        <div class="metric-card"><div class="metric-label"><span class="metric-icon blue"></span>根因 Top-1</div><strong>{{ percent(report.aggregate.root_cause_top1) }}</strong><small>{{ report.scenario_count }} 个固定场景</small></div>
        <div class="metric-card success"><div class="metric-label"><span class="metric-icon green"></span>证据召回率</div><strong>{{ percent(report.aggregate.evidence_recall) }}</strong><small>关键证据是否被引用</small></div>
        <div class="metric-card"><div class="metric-label"><span class="metric-icon blue"></span>跨源覆盖率</div><strong>{{ percent(report.aggregate.source_recall) }}</strong><small>日志、指标与集群状态</small></div>
        <div class="metric-card" :class="{ success: report.aggregate.unsupported_claim_rate === 0 }"><div class="metric-label"><span class="metric-icon green"></span>无证据声明</div><strong>{{ percent(report.aggregate.unsupported_claim_rate) }}</strong><small>越低越可信</small></div>
      </div>

      <div class="evaluation-grid">
        <section class="panel category-scoreboard">
          <header><div><h2>能力雷达</h2><span>按故障类型拆分 Top-1</span></div><small>{{ report.benchmark }}</small></header>
          <div v-for="name in categories" :key="name" class="category-row">
            <span>{{ categoryLabel(name) }}</span>
            <el-progress :percentage="Math.round(categoryTop1(name) * 100)" :stroke-width="8" />
          </div>
        </section>
        <section class="panel evaluation-meta">
          <header><h2>本次运行</h2><span v-if="report.created_at">{{ new Date(report.created_at).toLocaleString() }}</span><span v-else>实时预览，尚未保存</span></header>
          <div><span>评测引擎</span><strong>{{ report.engine || 'evidence-rules-baseline' }}</strong></div>
          <div><span>Brier 分数</span><strong>{{ report.aggregate.brier_score.toFixed(3) }}</strong></div>
          <div><span>平均工具调用</span><strong>{{ report.aggregate.tool_calls.toFixed(1) }}</strong></div>
          <div><span>平均延迟</span><strong>{{ report.aggregate.latency_ms.toFixed(2) }} ms</strong></div>
          <p>后续接入任意 Agent 预测结果，都可以在相同场景和评分器下横向比较。</p>
        </section>
      </div>

      <section class="panel evaluation-table">
        <header>
          <div><h2>场景明细</h2><span>每个结论都检查根因、证据引用和跨数据源覆盖</span></div>
          <el-select v-model="category" style="width: 150px"><el-option label="全部类型" value="all" /><el-option v-for="name in categories" :key="name" :label="categoryLabel(name)" :value="name" /></el-select>
        </header>
        <el-table :data="rows" :row-class-name="rowClass">
          <el-table-column label="场景" min-width="260"><template #default="{ row }"><div class="eval-title"><strong>{{ row.title }}</strong><small>{{ row.service }} · {{ row.alert }}</small></div></template></el-table-column>
          <el-table-column label="类型" width="110"><template #default="{ row }">{{ categoryLabel(row.category) }}</template></el-table-column>
          <el-table-column label="预测根因" min-width="230"><template #default="{ row }">{{ row.prediction.root_cause }}</template></el-table-column>
          <el-table-column label="数据源" min-width="180"><template #default="{ row }"><span v-for="source in row.required_sources" :key="source" class="eval-source">{{ source }}</span></template></el-table-column>
          <el-table-column label="Top-1" width="90" align="center"><template #default="{ row }"><span class="eval-result" :class="row.metrics.root_cause_top1 ? 'pass' : 'fail'">{{ row.metrics.root_cause_top1 ? 'PASS' : 'MISS' }}</span></template></el-table-column>
          <el-table-column label="证据召回" width="110" align="center"><template #default="{ row }">{{ percent(row.metrics.evidence_recall) }}</template></el-table-column>
        </el-table>
      </section>
    </template>
  </section>
</template>

<style scoped>
.evaluation-grid { display: grid; grid-template-columns: 1.35fr .65fr; gap: 16px; margin: 16px 0; }
.category-scoreboard, .evaluation-meta, .evaluation-table { overflow: hidden; }
.category-scoreboard > header, .evaluation-meta > header, .evaluation-table > header { display: flex; align-items: center; justify-content: space-between; padding: 17px 19px; border-bottom: 1px solid var(--line-soft); }
.category-scoreboard h2, .evaluation-meta h2, .evaluation-table h2 { margin: 0; font-size: 14px; }
.category-scoreboard header span, .category-scoreboard header small, .evaluation-meta header span, .evaluation-table header span { color: var(--subtle); font-size: 9px; }
.category-scoreboard header span, .evaluation-table header span { display: block; margin-top: 5px; }
.category-row { display: grid; grid-template-columns: 110px 1fr; align-items: center; gap: 16px; padding: 12px 19px; border-top: 1px solid var(--line-soft); font-size: 10px; }
.category-row:first-of-type { border-top: 0; }
.evaluation-meta > div { display: flex; justify-content: space-between; padding: 11px 19px; border-top: 1px solid var(--line-soft); color: var(--muted); font-size: 10px; }
.evaluation-meta > div strong { color: var(--text); }
.evaluation-meta p { margin: 12px 19px 17px; color: var(--subtle); font-size: 9px; line-height: 1.6; }
.evaluation-table { margin-top: 16px; }
.eval-title strong, .eval-title small { display: block; }
.eval-title strong { font-size: 11px; }
.eval-title small { margin-top: 5px; color: var(--subtle); font-size: 9px; }
.eval-source { display: inline-block; margin: 2px 4px 2px 0; padding: 3px 6px; border-radius: 4px; color: #3855b3; background: var(--primary-soft); font-size: 8px; }
.eval-result { font-size: 9px; font-weight: 750; }
.eval-result.pass { color: var(--green); }
.eval-result.fail { color: var(--red); }
@media (max-width: 1050px) { .evaluation-grid { grid-template-columns: 1fr; } }
</style>
