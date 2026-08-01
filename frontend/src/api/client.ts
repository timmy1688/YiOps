import axios from 'axios'

export interface AuthStatus {
  enabled: boolean
  authenticated: boolean
}

export interface CurrentUser {
  id: string
  username: string
  display_name: string
  role: string
  tenant_id: string
  tenant_name: string
}

export interface AnalysisRun {
  id: string
  incident_id: string
  status: string
  current_step: string | null
  progress: number
  model_name: string
  error_code: string | null
  error_message: string | null
  input_tokens: number
  output_tokens: number
  started_at: string | null
  completed_at: string | null
  created_at: string
}

export interface Incident {
  id: string
  title: string
  service: string
  cluster: string | null
  namespace: string | null
  severity: string
  status: string
  started_at: string
  ended_at: string | null
  alert_count: number
  is_test: boolean
  source: string | null
  created_at: string
  latest_run: AnalysisRun | null
}

export interface Evidence {
  id: string
  analysis_run_id: string
  tool_execution_id: string | null
  type: string
  source: string
  title: string
  summary: string
  observed_at: string | null
  subject: Record<string, unknown>
  values: Record<string, unknown>
  quality: number
}

export interface Hypothesis {
  cause: string
  confidence: number
  supporting_evidence_ids: string[]
  contradicting_evidence_ids: string[]
  missing_evidence: string[]
}

export interface RootCauseReport {
  id: string
  analysis_run_id: string
  status: string
  summary: string
  confidence: number
  hypotheses: Hypothesis[]
  recommended_actions: string[]
  missing_evidence: string[]
  created_at: string
}

export interface ToolExecution {
  id: string
  source: string
  query_pack: string
  template_id: string
  parameters: Record<string, unknown>
  status: string
  duration_ms: number
  result_count: number
  result_summary: Record<string, unknown> | null
  error_code: string | null
  created_at: string
}

export interface Datasource {
  id: string
  name: string
  type: 'prometheus' | 'loki' | 'elasticsearch' | 'kubernetes'
  base_url: string
  secret_configured: boolean
  settings: Record<string, unknown>
  enabled: boolean
  last_test_status: string | null
  last_tested_at: string | null
}

export interface DatasourceInput {
  name: string
  type: Datasource['type']
  base_url?: string
  kubeconfig?: string
  enabled: boolean
  credential?: string
  ca_cert?: string
  settings?: Record<string, unknown>
}

export interface ConnectorType {
  type: Datasource['type']
  display_name: string
  health_path: string
  capabilities: string[]
  credential_kind: string
}

export interface AlertIntegration {
  id: string
  name: string
  type: 'alertmanager'
  webhook_path: string
  default_cluster: string | null
  default_namespace: string | null
  auto_analyze: boolean
  enabled: boolean
  received_count: number
  last_received_at: string | null
  created_at: string
}

export interface AlertIntegrationInput {
  name: string
  type: 'alertmanager'
  default_cluster?: string
  default_namespace?: string
  auto_analyze?: boolean
  enabled: boolean
}

export interface AnalysisModelConfig {
  id: string
  name: string
  provider: 'deepseek' | 'openai_compatible'
  base_url: string
  model_name: string
  api_key_configured: boolean
  enabled: boolean
  last_test_status: string | null
  last_test_message: string | null
  last_tested_at: string | null
  created_at: string
  updated_at: string
}

export interface AnalysisModelConfigInput {
  name: string
  provider: AnalysisModelConfig['provider']
  base_url: string
  model_name: string
  api_key?: string
  enabled: boolean
}

export interface ChatCompletionInput {
  messages: Array<{ role: 'user' | 'assistant'; content: string }>
  incident_id?: string
}

export interface ChatCompletionResponse {
  content: string
  model_name: string
  context_scope: 'overview' | 'incident'
  tool_calls: ChatToolCall[]
}

export interface ChatToolCall {
  name: string
  status: string
  result_count: number
  duration_ms: number
  parameters: Record<string, unknown>
  error_code: string | null
}

export interface InvestigationMessage {
  id: string
  role: 'user' | 'assistant'
  content: string
  model_name: string | null
  tool_calls: ChatToolCall[]
  created_at: string
}

export interface InvestigationStep {
  id: string
  sequence: number
  name: string
  source: string
  status: string
  description: string | null
  parameters: Record<string, unknown>
  result_count: number
  duration_ms: number
  error_code: string | null
  created_at: string
  completed_at: string | null
}

export interface InvestigationEvidence {
  id: string
  step_id: string | null
  source: string
  title: string
  summary: string
  observed_at: string | null
  subject: Record<string, unknown>
  values: Record<string, unknown>
  quality: number
  created_at: string
}

export interface InvestigationHypothesis {
  id: string
  cause: string
  confidence: number
  status: string
  supporting_evidence_ids: string[]
  contradicting_evidence_ids: string[]
  missing_evidence: string[]
  created_at: string
  updated_at: string
}

export interface Investigation {
  id: string
  incident_id: string | null
  title: string
  status: string
  current_step: string | null
  progress: number
  model_name: string | null
  summary: string | null
  input_tokens: number
  output_tokens: number
  tool_count: number
  error_code: string | null
  error_message: string | null
  share_token: string | null
  started_at: string | null
  completed_at: string | null
  created_at: string
  updated_at: string
}

export interface InvestigationDetail extends Investigation {
  messages: InvestigationMessage[]
  steps: InvestigationStep[]
  evidence: InvestigationEvidence[]
  hypotheses: InvestigationHypothesis[]
}

export interface EvaluationMetrics {
  root_cause_top1: number
  evidence_precision: number
  evidence_recall: number
  source_recall: number
  unsupported_claim_rate: number
  brier_score: number
  latency_ms: number
  tool_calls: number
  tokens: number
}

export interface EvaluationScenarioResult {
  scenario_id: string
  title: string
  category: string
  service: string
  alert: string
  required_sources: string[]
  prediction: { root_cause: string; confidence: number; evidence_ids: string[] }
  metrics: EvaluationMetrics
}

export interface EvaluationReport {
  id?: string
  benchmark: string
  engine?: string
  scenario_count: number
  aggregate: EvaluationMetrics
  categories: Record<string, EvaluationMetrics>
  results: EvaluationScenarioResult[]
  duration_ms?: number
  created_at?: string
}

const api = axios.create({
  baseURL: '/api/v1',
  timeout: 20_000,
  withCredentials: true,
})

function cookie(name: string) {
  const prefix = `${encodeURIComponent(name)}=`
  const item = document.cookie.split('; ').find((value) => value.startsWith(prefix))
  return item ? decodeURIComponent(item.slice(prefix.length)) : ''
}

api.interceptors.request.use((config) => {
  const csrf = cookie('yiops_csrf')
  if (csrf && !['get', 'head', 'options'].includes(config.method?.toLowerCase() || 'get')) {
    config.headers.set('X-YiOps-CSRF', csrf)
  }
  return config
})

api.interceptors.response.use(
  (response) => response,
  (error) => {
    if (error?.response?.status === 401) {
      window.dispatchEvent(new CustomEvent('yiops:unauthorized'))
    }
    return Promise.reject(error)
  },
)

export const getAuthStatus = async () => (await api.get<AuthStatus>('/auth/status')).data
export const getCurrentUser = async () => (await api.get<CurrentUser>('/auth/me')).data
export const login = async (username: string, password: string) =>
  (await api.post<CurrentUser>('/auth/login', { username, password })).data
export const logout = async () => {
  await api.post('/auth/logout')
}
export const changePassword = async (currentPassword: string, newPassword: string) => {
  await api.post('/auth/password', {
    current_password: currentPassword,
    new_password: newPassword,
  })
}

export const listIncidents = async () => (await api.get<Incident[]>('/incidents')).data
export const getIncident = async (id: string) =>
  (await api.get<Incident>(`/incidents/${id}`)).data
export const startAnalysis = async (incidentId: string) =>
  (await api.post<AnalysisRun>(`/incidents/${incidentId}/analysis-runs`)).data
export const getRun = async (runId: string) =>
  (await api.get<AnalysisRun>(`/analysis-runs/${runId}`)).data
export const listEvidence = async (runId: string) =>
  (await api.get<Evidence[]>(`/analysis-runs/${runId}/evidence`)).data
export const listToolExecutions = async (runId: string) =>
  (await api.get<ToolExecution[]>(`/analysis-runs/${runId}/tool-executions`)).data
export const getReport = async (runId: string) =>
  (await api.get<RootCauseReport>(`/analysis-runs/${runId}/report`)).data
export const listDatasources = async () =>
  (await api.get<Datasource[]>('/datasources')).data
export const listConnectorTypes = async () =>
  (await api.get<ConnectorType[]>('/connector-types')).data
export const createDatasource = async (payload: DatasourceInput) =>
  (await api.post<Datasource>('/datasources', payload)).data
export const testDatasource = async (id: string) =>
  (await api.post<{ ok: boolean; message: string }>(`/datasources/${id}/test`)).data
export const deleteDatasource = async (id: string) => {
  await api.delete(`/datasources/${id}`)
}
export const listIntegrations = async () =>
  (await api.get<AlertIntegration[]>('/integrations')).data
export const createIntegration = async (payload: AlertIntegrationInput) =>
  (await api.post<AlertIntegration>('/integrations', payload)).data
export const updateIntegration = async (
  id: string,
  payload: Partial<AlertIntegrationInput>,
) => (await api.patch<AlertIntegration>(`/integrations/${id}`, payload)).data
export const deleteIntegration = async (id: string) => {
  await api.delete(`/integrations/${id}`)
}
export const listModelConfigs = async () =>
  (await api.get<AnalysisModelConfig[]>('/model-configs')).data
export const createModelConfig = async (payload: AnalysisModelConfigInput) =>
  (await api.post<AnalysisModelConfig>('/model-configs', payload)).data
export const updateModelConfig = async (
  id: string,
  payload: AnalysisModelConfigInput,
) => (await api.put<AnalysisModelConfig>(`/model-configs/${id}`, payload)).data
export const deleteModelConfig = async (id: string) => {
  await api.delete(`/model-configs/${id}`)
}
export const testModelConfig = async (id: string) =>
  (await api.post<{ ok: boolean; message: string }>(`/model-configs/${id}/test`)).data
export const createChatCompletion = async (payload: ChatCompletionInput) =>
  (await api.post<ChatCompletionResponse>('/chat/completions', payload, { timeout: 70_000 })).data
export const listInvestigations = async () =>
  (await api.get<Investigation[]>('/investigations')).data
export const createInvestigation = async (payload: {
  title: string
  question: string
  incident_id?: string
}) => (await api.post<Investigation>('/investigations', payload)).data
export const getInvestigation = async (id: string) =>
  (await api.get<InvestigationDetail>(`/investigations/${id}`)).data
export const sendInvestigationMessage = async (id: string, content: string) =>
  (await api.post<Investigation>(`/investigations/${id}/messages`, { content })).data
export const cancelInvestigation = async (id: string) =>
  (await api.post<Investigation>(`/investigations/${id}/cancel`)).data
export const resumeInvestigation = async (id: string) =>
  (await api.post<Investigation>(`/investigations/${id}/resume`)).data
export const shareInvestigation = async (id: string) =>
  (
    await api.post<{ share_token: string; share_path: string }>(
      `/investigations/${id}/share`,
    )
  ).data
export const investigationEventUrl = (id: string) =>
  `${window.location.origin}/api/v1/investigations/${id}/events`
export const investigationExportUrl = (id: string) =>
  `${window.location.origin}/api/v1/investigations/${id}/export`

export const previewEvaluation = async () =>
  (await api.get<EvaluationReport>('/evaluations/preview')).data
export const listEvaluationRuns = async () =>
  (await api.get<EvaluationReport[]>('/evaluations/runs')).data
export const createEvaluationRun = async () =>
  (await api.post<EvaluationReport>('/evaluations/runs')).data
export const importOfficialDemos = async () =>
  (
    await api.post<{
      created_incident_ids: string[]
      existing_incident_ids: string[]
      investigation_ids: string[]
      demo_count: number
    }>('/demos/official')
  ).data

export const analysisEventUrl = (runId: string) =>
  `${window.location.origin}/api/v1/analysis-runs/${runId}/events`
