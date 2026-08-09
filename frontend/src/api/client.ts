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
  type: 'prometheus' | 'loki' | 'tempo' | 'elasticsearch' | 'kubernetes'
  base_url: string
  auth_type: 'none' | 'bearer' | 'basic' | 'api_key'
  username: string | null
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
  auth_type: Datasource['auth_type']
  username?: string
  enabled: boolean
  credential?: string
  settings?: Record<string, unknown>
}

export interface ConnectorType {
  type: Datasource['type']
  display_name: string
  health_path: string
  capabilities: string[]
  credential_kind: string
}

export interface WikiDocument {
  id: string
  title: string
  content: string
  tags: string[]
  status: 'draft' | 'published'
  version: number
  chunk_count: number
  created_at: string
  updated_at: string
}

export interface WikiSearchResult {
  document_id: string
  title: string
  heading: string | null
  excerpt: string
  score: number
  version: number
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
  conversation_id?: string
  conversation_title?: string
}

export interface ChatToolCall {
  name: string
  status: string
  result_count: number
  duration_ms: number
  parameters: Record<string, unknown>
  error_code: string | null
}

export interface ChatConversationMessage {
  id: string
  role: 'user' | 'assistant'
  content: string
  model_name: string | null
  tool_calls: ChatToolCall[]
  created_at: string
}

export interface ChatConversation {
  id: string
  title: string
  incident_id: string | null
  message_count: number
  last_message_at: string | null
  created_at: string
  updated_at: string
}

export interface ChatConversationDetail extends ChatConversation {
  messages: ChatConversationMessage[]
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
export const updateDatasource = async (
  id: string,
  payload: Partial<DatasourceInput>,
) => (await api.patch<Datasource>(`/datasources/${id}`, payload)).data
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
export const listChatConversations = async () =>
  (await api.get<ChatConversation[]>('/chat/conversations')).data
export const createChatConversation = async (payload: {
  title?: string
  incident_id?: string
}) => (await api.post<ChatConversationDetail>('/chat/conversations', payload)).data
export const importChatConversation = async (payload: {
  title?: string
  incident_id?: string
  messages: Array<{ role: 'user' | 'assistant'; content: string }>
}) => (await api.post<ChatConversationDetail>('/chat/conversations/import', payload)).data
export const getChatConversation = async (id: string) =>
  (await api.get<ChatConversationDetail>(`/chat/conversations/${id}`)).data
export const updateChatConversation = async (id: string, title: string) =>
  (await api.patch<ChatConversation>(`/chat/conversations/${id}`, { title })).data
export const deleteChatConversation = async (id: string) => {
  await api.delete(`/chat/conversations/${id}`)
}
export const sendChatConversationMessage = async (id: string, content: string) =>
  (
    await api.post<ChatCompletionResponse>(
      `/chat/conversations/${id}/messages`,
      { content },
      { timeout: 70_000 },
    )
  ).data
export const streamChatConversationMessage = async (
  id: string,
  content: string,
  handlers: {
    onToken: (content: string) => void
    onDone: (response: ChatCompletionResponse) => void
  },
  signal?: AbortSignal,
) => {
  const csrf = cookie('yiops_csrf')
  const response = await fetch(
    `/api/v1/chat/conversations/${encodeURIComponent(id)}/messages/stream`,
    {
      method: 'POST',
      credentials: 'include',
      signal,
      headers: {
        'Content-Type': 'application/json',
        ...(csrf ? { 'X-YiOps-CSRF': csrf } : {}),
      },
      body: JSON.stringify({ content }),
    },
  )
  if (!response.ok || !response.body) {
    let message = `流式请求失败（${response.status}）`
    try {
      const payload = await response.json() as { detail?: string }
      message = payload.detail || message
    } catch {
      // Keep the HTTP status fallback.
    }
    throw new Error(message)
  }
  const reader = response.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  const consume = (block: string) => {
    let event = 'message'
    const data: string[] = []
    for (const line of block.split('\n')) {
      if (line.startsWith('event:')) event = line.slice(6).trim()
      if (line.startsWith('data:')) data.push(line.slice(5).trimStart())
    }
    if (!data.length || event === 'ping' || event === 'conversation') return
    const payload = JSON.parse(data.join('\n')) as Record<string, unknown>
    if (event === 'token') handlers.onToken(String(payload.content || ''))
    else if (event === 'done') handlers.onDone(payload as unknown as ChatCompletionResponse)
    else if (event === 'error') throw new Error(String(payload.message || '流式生成失败'))
  }
  while (true) {
    const { value, done } = await reader.read()
    buffer += decoder.decode(value, { stream: !done }).replace(/\r\n/g, '\n')
    let boundary = buffer.indexOf('\n\n')
    while (boundary >= 0) {
      consume(buffer.slice(0, boundary))
      buffer = buffer.slice(boundary + 2)
      boundary = buffer.indexOf('\n\n')
    }
    if (done) break
  }
  if (buffer.trim()) consume(buffer)
}
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

export const listWikiDocuments = async () =>
  (await api.get<WikiDocument[]>('/wiki')).data
export const createWikiDocument = async (payload: {
  title: string
  content: string
  tags: string[]
  status: 'draft' | 'published'
}) => (await api.post<WikiDocument>('/wiki', payload)).data
export const updateWikiDocument = async (
  id: string,
  payload: Partial<Pick<WikiDocument, 'title' | 'content' | 'tags' | 'status'>>,
) => (await api.patch<WikiDocument>(`/wiki/${id}`, payload)).data
export const deleteWikiDocument = async (id: string) => api.delete(`/wiki/${id}`)
export const reindexWikiDocument = async (id: string) =>
  (await api.post<WikiDocument>(`/wiki/${id}/reindex`)).data
export const searchWiki = async (query: string, limit = 6) =>
  (await api.post<WikiSearchResult[]>('/wiki/search/query', { query, limit })).data
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
