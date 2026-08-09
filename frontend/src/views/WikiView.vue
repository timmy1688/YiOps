<script setup lang="ts">
import { Delete, Edit, Plus, Refresh, Search, UploadFilled } from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { onMounted, reactive, ref } from 'vue'

import {
  createWikiDocument,
  deleteWikiDocument,
  listWikiDocuments,
  reindexWikiDocument,
  searchWiki,
  updateWikiDocument,
  type WikiDocument,
  type WikiSearchResult,
} from '@/api/client'

const loading = ref(false)
const saving = ref(false)
const uploading = ref(false)
const deletingId = ref('')
const fileInput = ref<HTMLInputElement>()
const documents = ref<WikiDocument[]>([])
const results = ref<WikiSearchResult[]>([])
const searchText = ref('')
const editorOpen = ref(false)
const editingId = ref('')
const form = reactive({
  title: '',
  content: '',
  tags: [] as string[],
  status: 'published' as 'draft' | 'published',
})

async function load() {
  loading.value = true
  try {
    documents.value = await listWikiDocuments()
  } catch {
    ElMessage.error('Wiki 加载失败')
  } finally {
    loading.value = false
  }
}

onMounted(() => void load())

function createNew() {
  editingId.value = ''
  Object.assign(form, { title: '', content: '', tags: [], status: 'published' })
  editorOpen.value = true
}

function chooseFiles() {
  fileInput.value?.click()
}

async function importFiles(event: Event) {
  const input = event.target as HTMLInputElement
  const files = Array.from(input.files || []).slice(0, 10)
  input.value = ''
  if (!files.length) return
  uploading.value = true
  let imported = 0
  const failures: string[] = []
  for (const file of files) {
    if (!/\.(md|markdown|txt)$/i.test(file.name)) {
      failures.push(`${file.name}：仅支持 Markdown/TXT`)
      continue
    }
    if (file.size > 2_000_000) {
      failures.push(`${file.name}：超过 2 MB`)
      continue
    }
    try {
      const content = (await file.text()).trim()
      if (!content) throw new Error('文件为空')
      const title = file.name.replace(/\.(md|markdown|txt)$/i, '').trim().slice(0, 300)
      const existing = documents.value.find((item) => item.title === title)
      if (existing) {
        await updateWikiDocument(existing.id, {
          content,
          tags: [...new Set([...existing.tags, 'uploaded'])],
          status: 'published',
        })
      } else {
        await createWikiDocument({
          title,
          content,
          tags: ['uploaded'],
          status: 'published',
        })
      }
      imported += 1
    } catch (error) {
      const detail = (error as { response?: { data?: { detail?: string } }; message?: string })
      failures.push(`${file.name}：${detail.response?.data?.detail || detail.message || '导入失败'}`)
    }
  }
  await load()
  uploading.value = false
  if (imported) ElMessage.success(`已导入并索引 ${imported} 个文件`)
  if (failures.length) ElMessage.warning(failures.slice(0, 3).join('；'))
}

function edit(item: WikiDocument) {
  editingId.value = item.id
  Object.assign(form, {
    title: item.title,
    content: item.content,
    tags: [...item.tags],
    status: item.status,
  })
  editorOpen.value = true
}

async function save() {
  if (!form.title.trim() || !form.content.trim()) {
    ElMessage.warning('标题和正文不能为空')
    return
  }
  saving.value = true
  try {
    const payload = {
      title: form.title.trim(),
      content: form.content.trim(),
      tags: form.tags,
      status: form.status,
    }
    if (editingId.value) await updateWikiDocument(editingId.value, payload)
    else await createWikiDocument(payload)
    editorOpen.value = false
    await load()
    ElMessage.success('Wiki 已保存并完成索引')
  } catch (error) {
    const detail = (error as { response?: { data?: { detail?: string } } }).response?.data
      ?.detail
    ElMessage.error(detail || 'Wiki 保存失败')
  } finally {
    saving.value = false
  }
}

async function remove(item: WikiDocument) {
  try {
    await ElMessageBox.confirm(`确定删除“${item.title}”及其检索索引吗？`, '删除 Wiki', {
      type: 'warning',
      confirmButtonText: '删除',
      cancelButtonText: '取消',
    })
  } catch {
    return
  }
  deletingId.value = item.id
  try {
    await deleteWikiDocument(item.id)
    documents.value = documents.value.filter((document) => document.id !== item.id)
    results.value = results.value.filter((result) => result.document_id !== item.id)
    ElMessage.success('Wiki 已删除')
  } catch (error) {
    const detail = (error as { response?: { data?: { detail?: string } } }).response?.data
      ?.detail
    ElMessage.error(detail || 'Wiki 删除失败')
  } finally {
    deletingId.value = ''
  }
}

async function reindex(item: WikiDocument) {
  await reindexWikiDocument(item.id)
  await load()
  ElMessage.success('索引已重建')
}

async function runSearch() {
  if (!searchText.value.trim()) {
    results.value = []
    return
  }
  results.value = await searchWiki(searchText.value.trim())
}
</script>

<template>
  <section>
    <header class="page-header">
      <div>
        <p class="eyebrow">LONG-TERM MEMORY</p>
        <h1>Wiki 记忆库</h1>
        <p class="page-subtitle">维护运行手册、架构知识和历史经验，发布内容会自动进入 Agent RAG。</p>
      </div>
      <div class="wiki-header-actions">
        <input
          ref="fileInput"
          class="wiki-file-input"
          type="file"
          accept=".md,.markdown,.txt,text/markdown,text/plain"
          multiple
          @change="importFiles"
        />
        <el-button :icon="UploadFilled" :loading="uploading" @click="chooseFiles">
          上传文档
        </el-button>
        <el-button type="primary" :icon="Plus" @click="createNew">新建 Wiki</el-button>
      </div>
    </header>

    <div class="panel wiki-search">
      <el-input
        v-model="searchText"
        clearable
        placeholder="测试 Agent 会检索到哪些知识"
        @keyup.enter="runSearch"
      >
        <template #append><el-button :icon="Search" @click="runSearch" /></template>
      </el-input>
      <div v-if="results.length" class="wiki-results">
        <article v-for="item in results" :key="`${item.document_id}-${item.heading}`">
          <strong>{{ item.title }}<span v-if="item.heading"> · {{ item.heading }}</span></strong>
          <small>相关度 {{ item.score.toFixed(3) }} · v{{ item.version }}</small>
          <p>{{ item.excerpt }}</p>
        </article>
      </div>
    </div>

    <div v-loading="loading" class="wiki-grid">
      <article v-for="item in documents" :key="item.id" class="panel wiki-card">
        <div class="wiki-card-head">
          <div>
            <h3>{{ item.title }}</h3>
            <small>v{{ item.version }} · {{ item.chunk_count }} 个分块</small>
          </div>
          <el-tag :type="item.status === 'published' ? 'success' : 'info'">
            {{ item.status === 'published' ? '已发布' : '草稿' }}
          </el-tag>
        </div>
        <p>{{ item.content.slice(0, 240) }}{{ item.content.length > 240 ? '…' : '' }}</p>
        <div class="wiki-tags"><el-tag v-for="tag in item.tags" :key="tag" size="small">{{ tag }}</el-tag></div>
        <div class="wiki-actions">
          <el-button :icon="Edit" @click="edit(item)">编辑</el-button>
          <el-button :icon="Refresh" @click="reindex(item)">重建索引</el-button>
          <el-button
            :icon="Delete"
            type="danger"
            plain
            :loading="deletingId === item.id"
            @click="remove(item)"
          >
            删除
          </el-button>
        </div>
      </article>
      <el-empty v-if="!loading && !documents.length" description="还没有 Wiki 文档" />
    </div>

    <el-drawer v-model="editorOpen" :title="editingId ? '编辑 Wiki' : '新建 Wiki'" size="620px">
      <el-form label-position="top">
        <el-form-item label="标题"><el-input v-model="form.title" /></el-form-item>
        <el-form-item label="标签">
          <el-select v-model="form.tags" multiple filterable allow-create default-first-option />
        </el-form-item>
        <el-form-item label="状态">
          <el-radio-group v-model="form.status">
            <el-radio-button value="published">发布</el-radio-button>
            <el-radio-button value="draft">草稿</el-radio-button>
          </el-radio-group>
        </el-form-item>
        <el-form-item label="Markdown 正文">
          <el-input v-model="form.content" type="textarea" :rows="24" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="editorOpen = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="save">保存并索引</el-button>
      </template>
    </el-drawer>
  </section>
</template>
