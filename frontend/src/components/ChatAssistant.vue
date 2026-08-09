<script setup lang="ts">
import {
  Close,
  Connection,
  Delete,
  EditPen,
  MagicStick,
  Plus,
  Promotion,
} from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { computed, nextTick, onBeforeUnmount, ref, watch } from 'vue'
import { useRoute } from 'vue-router'

import {
  createChatConversation,
  deleteChatConversation,
  getChatConversation,
  importChatConversation,
  listChatConversations,
  streamChatConversationMessage,
  updateChatConversation,
  type ChatConversation,
  type ChatConversationMessage,
  type ChatToolCall,
} from '@/api/client'
import SafeMarkdown from '@/components/SafeMarkdown.vue'

interface LocalMessage {
  id: string
  role: 'user' | 'assistant'
  content: string
  createdAt: number
  modelName?: string
  toolCalls?: ChatToolCall[]
}

const props = defineProps<{ open: boolean; embedded?: boolean }>()
const emit = defineEmits<{ 'update:open': [value: boolean] }>()
const route = useRoute()
const input = ref('')
const sending = ref(false)
const receivedToken = ref(false)
const loading = ref(false)
const streamController = ref<AbortController>()
const messageList = ref<HTMLElement>()
const legacyStorageKey = 'yiops-chat-conversations-v1'
const migrationMarker = 'yiops-chat-conversations-server-migrated-v1'
const conversations = ref<ChatConversation[]>([])
const conversationMessages = ref<Record<string, LocalMessage[]>>({})
const activeConversationId = ref('')
const initialized = ref(false)
const incidentId = computed(() =>
  route.name === 'incident-detail' ? String(route.params.id) : undefined,
)
const scopeConversations = computed(() =>
  conversations.value.filter(
    (item) => item.incident_id === (incidentId.value || null),
  ),
)
const activeConversation = computed(() =>
  scopeConversations.value.find((item) => item.id === activeConversationId.value),
)
const messages = computed(
  () => conversationMessages.value[activeConversationId.value] || [],
)
const contextLabel = computed(() =>
  incidentId.value ? '已关联当前故障，可调用实时数据源' : '可调用实时数据源查询',
)
const suggestions = computed(() =>
  incidentId.value
    ? ['查询当前服务最近 10 条错误链路', '哪些证据支持这个根因？', '检查相关 Kubernetes 异常']
    : ['查询最近 10 条 Tempo 错误链路', '检查 Kubernetes 异常 Pod', '帮我分析当前运维风险'],
)

function toLocalMessage(message: ChatConversationMessage): LocalMessage {
  return {
    id: message.id,
    role: message.role,
    content: message.content,
    createdAt: Date.parse(message.created_at),
    modelName: message.model_name || undefined,
    toolCalls: message.tool_calls,
  }
}

async function migrateLegacyConversations() {
  if (localStorage.getItem(migrationMarker)) return
  try {
    const parsed = JSON.parse(localStorage.getItem(legacyStorageKey) || '{}') as Record<
      string,
      LocalMessage[]
    >
    for (const [scope, items] of Object.entries(parsed)) {
      const usable = Array.isArray(items)
        ? items.filter(
            (item) =>
              ['user', 'assistant'].includes(item.role) && Boolean(item.content?.trim()),
          )
        : []
      if (!usable.length) continue
      try {
        await importChatConversation({
          incident_id: scope === 'overview' ? undefined : scope,
          title:
            usable.find((item) => item.role === 'user')?.content.trim().slice(0, 60) ||
            '导入对话',
          messages: usable.slice(-24).map(({ role, content }) => ({ role, content })),
        })
      } catch {
        // A deleted Incident must not block migration of other conversations.
      }
    }
  } catch {
    // Ignore corrupt legacy localStorage and start with a clean server conversation.
  } finally {
    localStorage.setItem(migrationMarker, '1')
  }
}

async function initialize() {
  loading.value = true
  try {
    await migrateLegacyConversations()
    conversations.value = await listChatConversations()
    initialized.value = true
    await ensureScopeConversation()
  } catch (error) {
    ElMessage.error(errorMessage(error))
  } finally {
    loading.value = false
  }
}

async function ensureScopeConversation() {
  if (!initialized.value) return
  const current = scopeConversations.value.find(
    (item) => item.id === activeConversationId.value,
  )
  if (current) {
    await loadConversation(current.id)
    return
  }
  const first = scopeConversations.value[0]
  if (first) {
    await selectConversation(first.id)
  } else {
    await createNewConversation(false)
  }
}

async function loadConversation(id: string) {
  const detail = await getChatConversation(id)
  conversationMessages.value[id] = detail.messages.map(toLocalMessage)
  const index = conversations.value.findIndex((item) => item.id === id)
  if (index >= 0) conversations.value[index] = detail
  scrollToBottom()
}

async function selectConversation(id: string) {
  if (!id || sending.value) return
  activeConversationId.value = id
  loading.value = true
  try {
    await loadConversation(id)
  } catch (error) {
    ElMessage.error(errorMessage(error))
  } finally {
    loading.value = false
  }
}

async function createNewConversation(notify = true) {
  if (sending.value) return
  loading.value = true
  try {
    const created = await createChatConversation({ incident_id: incidentId.value })
    conversations.value = [created, ...conversations.value]
    conversationMessages.value[created.id] = []
    activeConversationId.value = created.id
    if (notify) ElMessage.success('已创建新对话')
  } catch (error) {
    ElMessage.error(errorMessage(error))
  } finally {
    loading.value = false
  }
}

async function renameCurrentConversation() {
  const current = activeConversation.value
  if (!current || sending.value) return
  try {
    const result = await ElMessageBox.prompt('请输入新的会话名称', '重命名对话', {
      inputValue: current.title,
      inputPattern: /\S+/,
      inputErrorMessage: '名称不能为空',
      confirmButtonText: '保存',
      cancelButtonText: '取消',
    })
    const updated = await updateChatConversation(current.id, result.value.trim())
    const index = conversations.value.findIndex((item) => item.id === current.id)
    if (index >= 0) conversations.value[index] = updated
    ElMessage.success('对话已重命名')
  } catch (error) {
    if (error !== 'cancel' && error !== 'close') ElMessage.error(errorMessage(error))
  }
}

async function removeCurrentConversation() {
  const current = activeConversation.value
  if (!current || sending.value) return
  try {
    await ElMessageBox.confirm(
      `确定永久删除对话“${current.title}”及其全部消息吗？`,
      '删除对话',
      {
        type: 'warning',
        confirmButtonText: '删除',
        cancelButtonText: '取消',
      },
    )
  } catch {
    return
  }
  loading.value = true
  try {
    await deleteChatConversation(current.id)
    conversations.value = conversations.value.filter((item) => item.id !== current.id)
    delete conversationMessages.value[current.id]
    activeConversationId.value = ''
    await ensureScopeConversation()
    ElMessage.success('对话已删除')
  } catch (error) {
    ElMessage.error(errorMessage(error))
  } finally {
    loading.value = false
  }
}

function scrollToBottom() {
  nextTick(() => {
    if (messageList.value) messageList.value.scrollTop = messageList.value.scrollHeight
  })
}

function errorMessage(error: unknown) {
  const candidate = error as { response?: { data?: { detail?: string } }; message?: string }
  return candidate.response?.data?.detail || candidate.message || '请求失败，请稍后重试'
}

function messageId() {
  return `${Date.now()}-${Math.random().toString(36).slice(2)}`
}

async function sendMessage(preset?: string) {
  const content = (preset ?? input.value).trim()
  if (!content || sending.value) return
  if (!activeConversation.value) await createNewConversation(false)
  const conversation = activeConversation.value
  if (!conversation) return

  const localMessages = conversationMessages.value[conversation.id] || []
  conversationMessages.value[conversation.id] = localMessages
  localMessages.push({
    id: messageId(),
    role: 'user',
    content,
    createdAt: Date.now(),
  })
  input.value = ''
  sending.value = true
  receivedToken.value = false
  const assistantId = messageId()
  localMessages.push({
    id: assistantId,
    role: 'assistant',
    content: '',
    createdAt: Date.now(),
  })
  scrollToBottom()

  try {
    const controller = new AbortController()
    streamController.value = controller
    await streamChatConversationMessage(
      conversation.id,
      content,
      {
        onToken: (token) => {
          const assistant = localMessages.find((item) => item.id === assistantId)
          if (!assistant || !token) return
          assistant.content += token
          receivedToken.value = true
          scrollToBottom()
        },
        onDone: (response) => {
          const assistant = localMessages.find((item) => item.id === assistantId)
          if (!assistant) return
          assistant.content = response.content
          assistant.modelName = response.model_name
          assistant.toolCalls = response.tool_calls
          receivedToken.value = true
          if (response.conversation_title) conversation.title = response.conversation_title
        },
      },
      controller.signal,
    )
    await loadConversation(conversation.id)
    conversations.value = await listChatConversations()
  } catch (error) {
    if ((error as { name?: string }).name !== 'AbortError') {
      ElMessage.error(errorMessage(error))
    }
    await loadConversation(conversation.id).catch(() => undefined)
  } finally {
    streamController.value = undefined
    sending.value = false
    receivedToken.value = false
    scrollToBottom()
  }
}

function handleKeydown(event: KeyboardEvent) {
  if (event.key === 'Enter' && !event.shiftKey) {
    event.preventDefault()
    sendMessage()
  }
}

function formatTime(value: number) {
  return new Intl.DateTimeFormat('zh-CN', {
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
  }).format(value)
}

function toolLabel(name: string) {
  return (
    {
      query_loki_logs: 'Loki 日志查询',
      query_prometheus: 'Prometheus 指标查询',
      search_tempo_traces: 'Tempo 链路搜索',
      get_tempo_trace: 'Tempo 链路详情',
      inspect_kubernetes: 'Kubernetes 状态检查',
      query_elasticsearch_logs: 'Elasticsearch 日志查询',
      get_incident_analysis: '故障证据读取',
    }[name] || name
  )
}

watch(
  () => incidentId.value,
  () => void ensureScopeConversation(),
)
watch(
  () => props.open,
  (open) => {
    if (open) scrollToBottom()
  },
)

onBeforeUnmount(() => streamController.value?.abort())

void initialize()
</script>

<template>
  <Transition name="chat-slide">
    <aside
      v-if="open"
      class="chat-assistant"
      :class="{ embedded }"
      aria-label="YiOps AI 助手"
    >
      <header class="chat-head">
        <div class="chat-avatar"><MagicStick /></div>
        <div>
          <strong>YiOps AI</strong>
          <span><i></i> 智能运维助手</span>
        </div>
        <div class="chat-head-actions">
          <el-tooltip content="新建对话" placement="bottom">
            <button
              type="button"
              aria-label="新建对话"
              :disabled="sending"
              @click="createNewConversation()"
            >
              <Plus />
            </button>
          </el-tooltip>
          <el-tooltip content="重命名当前对话" placement="bottom">
            <button
              type="button"
              aria-label="重命名当前对话"
              :disabled="!activeConversation || sending"
              @click="renameCurrentConversation"
            >
              <EditPen />
            </button>
          </el-tooltip>
          <el-tooltip content="删除当前对话" placement="bottom">
            <button
              type="button"
              aria-label="删除当前对话"
              :disabled="!activeConversation || sending"
              @click="removeCurrentConversation"
            >
              <Delete />
            </button>
          </el-tooltip>
          <button
            v-if="!embedded"
            type="button"
            aria-label="关闭 AI 助手"
            @click="emit('update:open', false)"
          >
            <Close />
          </button>
        </div>
      </header>

      <div class="chat-context">
        <i></i>
        <span>{{ contextLabel }}</span>
        <el-select
          v-model="activeConversationId"
          class="chat-conversation-select"
          size="small"
          :disabled="sending || loading"
          @change="selectConversation"
        >
          <el-option
            v-for="conversation in scopeConversations"
            :key="conversation.id"
            :label="conversation.title"
            :value="conversation.id"
          >
            <span class="chat-conversation-option">
              <b>{{ conversation.title }}</b>
              <small>{{ conversation.message_count }} 条</small>
            </span>
          </el-option>
        </el-select>
      </div>

      <div
        ref="messageList"
        v-loading="loading"
        class="chat-messages"
        aria-live="polite"
      >
        <div v-if="!messages.length" class="chat-empty">
          <div><MagicStick /></div>
          <h2>需要我帮你看什么？</h2>
          <p>我可以基于 YiOps 已采集的故障、报告和证据进行查询、归纳与分析。</p>
          <button
            v-for="suggestion in suggestions"
            :key="suggestion"
            type="button"
            @click="sendMessage(suggestion)"
          >
            {{ suggestion }}
            <span>→</span>
          </button>
        </div>

        <div
          v-for="message in messages"
          :key="message.id"
          class="chat-message"
          :class="message.role"
        >
          <div v-if="message.role === 'assistant'" class="message-avatar"><MagicStick /></div>
          <div class="message-content">
            <div v-if="message.toolCalls?.length" class="message-tools">
              <div
                v-for="(tool, toolIndex) in message.toolCalls"
                :key="`${message.id}-${tool.name}-${toolIndex}`"
              >
                <Connection />
                <span>
                  <strong>{{ toolLabel(tool.name) }}</strong>
                  {{ tool.status === 'completed' ? `返回 ${tool.result_count} 条` : '查询失败' }}
                </span>
                <i :class="tool.status"></i>
              </div>
            </div>
            <SafeMarkdown v-if="message.role === 'assistant'" :content="message.content" />
            <p v-else>{{ message.content }}</p>
            <small>
              {{ formatTime(message.createdAt) }}
              <template v-if="message.modelName"> · {{ message.modelName }}</template>
            </small>
          </div>
        </div>

        <div v-if="sending && !receivedToken" class="chat-message assistant">
          <div class="message-avatar"><MagicStick /></div>
          <div class="message-content typing" aria-label="AI 正在思考">
            <i></i><i></i><i></i>
          </div>
        </div>
      </div>

      <footer class="chat-composer">
        <div :class="{ focused: input }">
          <textarea
            v-model="input"
            rows="1"
            maxlength="8000"
            placeholder="输入问题，Enter 发送，Shift + Enter 换行"
            :disabled="sending"
            @keydown="handleKeydown"
          ></textarea>
          <button
            type="button"
            aria-label="发送消息"
            :disabled="!input.trim() || sending"
            @click="sendMessage()"
          >
            <Promotion />
          </button>
        </div>
        <p>数据源查询只读执行；AI 分析结果请结合原始证据确认。</p>
      </footer>
    </aside>
  </Transition>
</template>
