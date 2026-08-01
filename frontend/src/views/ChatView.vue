<script setup lang="ts">
import { DataAnalysis, Lock, Search } from '@element-plus/icons-vue'

import ChatAssistant from '@/components/ChatAssistant.vue'
</script>

<template>
  <section class="chat-page">
    <header class="chat-page-intro">
      <div>
        <p class="eyebrow">READ-ONLY COPILOT</p>
        <h1>AI 运维助手</h1>
        <p>查询实时数据源、关联故障证据，并给出有边界的分析结论。</p>
      </div>
      <div class="chat-capabilities">
        <span><Search />实时查询</span>
        <span><DataAnalysis />交叉分析</span>
        <span><Lock />只读执行</span>
      </div>
    </header>
    <ChatAssistant :open="true" embedded />
  </section>
</template>
