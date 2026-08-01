<script setup lang="ts">
import { computed } from 'vue'

const props = defineProps<{ content: string }>()

function escapeHtml(value: string) {
  return value
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&#039;')
}

function inline(value: string) {
  return escapeHtml(value)
    .replace(/`([^`]+)`/g, '<code>$1</code>')
    .replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>')
}

function cells(line: string) {
  return line
    .trim()
    .replace(/^\|/, '')
    .replace(/\|$/, '')
    .split('|')
    .map((cell) => cell.trim())
}

function renderMarkdown(source: string) {
  const lines = source.replace(/\r\n/g, '\n').split('\n')
  const output: string[] = []
  let index = 0
  while (index < lines.length) {
    const line = lines[index] || ''
    const next = lines[index + 1] || ''
    if (line.includes('|') && /^\s*\|?\s*:?-{3,}/.test(next)) {
      const headers = cells(line)
      output.push('<div class="markdown-table-wrap"><table><thead><tr>')
      output.push(...headers.map((cell) => `<th>${inline(cell)}</th>`))
      output.push('</tr></thead><tbody>')
      index += 2
      while (index < lines.length && (lines[index] || '').includes('|')) {
        output.push('<tr>')
        output.push(...cells(lines[index] || '').map((cell) => `<td>${inline(cell)}</td>`))
        output.push('</tr>')
        index += 1
      }
      output.push('</tbody></table></div>')
      continue
    }
    if (/^#{1,3}\s/.test(line)) {
      const level = Math.min((line.match(/^#+/)?.[0].length || 1) + 2, 5)
      output.push(`<h${level}>${inline(line.replace(/^#+\s+/, ''))}</h${level}>`)
      index += 1
      continue
    }
    if (/^[-*]\s+/.test(line)) {
      output.push('<ul>')
      while (index < lines.length && /^[-*]\s+/.test(lines[index] || '')) {
        output.push(`<li>${inline((lines[index] || '').replace(/^[-*]\s+/, ''))}</li>`)
        index += 1
      }
      output.push('</ul>')
      continue
    }
    if (/^\d+\.\s+/.test(line)) {
      output.push('<ol>')
      while (index < lines.length && /^\d+\.\s+/.test(lines[index] || '')) {
        output.push(`<li>${inline((lines[index] || '').replace(/^\d+\.\s+/, ''))}</li>`)
        index += 1
      }
      output.push('</ol>')
      continue
    }
    if (!line.trim()) {
      output.push('<span class="markdown-gap"></span>')
    } else {
      output.push(`<div>${inline(line)}</div>`)
    }
    index += 1
  }
  return output.join('')
}

const html = computed(() => renderMarkdown(props.content))
</script>

<template>
  <div class="markdown-content" v-html="html"></div>
</template>
