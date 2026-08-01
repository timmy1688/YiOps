<script setup lang="ts">
import { Close, Connection, Delete, MagicStick, Promotion } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import { computed, nextTick, ref, watch } from 'vue'
import { useRoute } from 'vue-router'

import { createChatCompletion, type ChatToolCall } from '@/api/client'
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
const messageList = ref<HTMLElement>()
const storageKey = 'yiops-chat-conversations-v1'

function loadConversations(): Record<string, LocalMessage[]> {
  try {
    return JSON.parse(localStorage.getItem(storageKey) || '{}')
  } catch {
    return {}
  }
}

const conversations = ref<Record<string, LocalMessage[]>>(loadConversations())
const incidentId = computed(() =>
  route.name === 'incident-detail' ? String(route.params.id) : undefined,
)
const conversationKey = computed(() => incidentId.value || 'overview')
const messages = computed(() => conversations.value[conversationKey.value] || [])
const contextLabel = computed(() =>
  incidentId.value ? '已关联当前故障，可调用实时数据源' : '可调用实时数据源查询',
)
const suggestions = computed(() =>
  incidentId.value
    ? ['查询当前服务最近 10 条 Loki 日志', '哪些证据支持这个根因？', '检查相关 Kubernetes 异常']
    : ['查询最近 10 条 Loki 日志', '检查 Kubernetes 异常 Pod', '帮我分析当前运维风险'],
)

function currentConversation() {
  const key = conversationKey.value
  const existing = conversations.value[key]
  if (existing) return existing
  const created: LocalMessage[] = []
  conversations.value[key] = created
  return created
}

function persist() {
  try {
    localStorage.setItem(storageKey, JSON.stringify(conversations.value))
  } catch {
    // A full or disabled localStorage should not prevent chatting.
  }
}

function scrollToBottom() {
  nextTick(() => {
    if (messageList.value) messageList.value.scrollTop = messageList.value.scrollHeight
  })
}

function clearConversation() {
  conversations.value[conversationKey.value] = []
  persist()
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

  const conversation = currentConversation()
  conversation.push({
    id: messageId(),
    role: 'user',
    content,
    createdAt: Date.now(),
  })
  input.value = ''
  persist()
  sending.value = true
  scrollToBottom()

  try {
    const response = await createChatCompletion({
      incident_id: incidentId.value,
      messages: conversation.slice(-24).map(({ role, content: messageContent }) => ({
        role,
        content: messageContent,
      })),
    })
    conversation.push({
      id: messageId(),
      role: 'assistant',
      content: response.content,
      createdAt: Date.now(),
      modelName: response.model_name,
      toolCalls: response.tool_calls,
    })
    persist()
  } catch (error) {
    ElMessage.error(errorMessage(error))
  } finally {
    sending.value = false
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
      inspect_kubernetes: 'Kubernetes 状态检查',
      query_elasticsearch_logs: 'Elasticsearch 日志查询',
      get_incident_analysis: '故障证据读取',
    }[name] || name
  )
}

watch([() => route.fullPath, conversationKey], scrollToBottom)
watch(
  () => props.open,
  (open) => {
    if (open) scrollToBottom()
  },
)
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
          <el-popconfirm title="确定清空当前对话吗？" @confirm="clearConversation">
            <template #reference>
              <el-tooltip content="清空当前对话" placement="bottom">
                <button type="button" aria-label="清空当前对话">
                  <Delete />
                </button>
              </el-tooltip>
            </template>
          </el-popconfirm>
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

      <div class="chat-context"><i></i>{{ contextLabel }}</div>

      <div ref="messageList" class="chat-messages" aria-live="polite">
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

        <div v-if="sending" class="chat-message assistant">
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
