import axios from 'axios'

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
  base_url: string
  enabled: boolean
  credential?: string
  ca_cert?: string
  settings?: Record<string, unknown>
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

const api = axios.create({
  baseURL: '/api/v1',
  timeout: 20_000,
})

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

export const analysisEventUrl = (runId: string) =>
  `${window.location.origin}/api/v1/analysis-runs/${runId}/events`
