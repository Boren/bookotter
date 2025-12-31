<script setup lang="ts">
import { ref, onMounted, onUnmounted, watch } from 'vue'

const logs = ref<string[]>([])
const loading = ref(true)
const autoRefresh = ref(true)
const selectedLevel = ref<string>('')
const lineCount = ref(100)

let refreshInterval: number | null = null

const levelColors: Record<string, string> = {
  DEBUG: 'text-stone-600',
  INFO: 'text-info-600',
  WARNING: 'text-warning-600',
  ERROR: 'text-error-600',
  CRITICAL: 'text-error-700 font-semibold',
}

const fetchLogs = async () => {
  try {
    let url = `/api/logs?lines=${lineCount.value}`
    if (selectedLevel.value) {
      url += `&level=${selectedLevel.value}`
    }

    const response = await fetch(url)
    const data = await response.json()
    logs.value = data.lines
  } catch (e) {
    console.error('Failed to fetch logs:', e)
  } finally {
    loading.value = false
  }
}

const clearLogs = async () => {
  if (!confirm('Clear all logs?')) return

  try {
    await fetch('/api/logs', { method: 'DELETE' })
    fetchLogs()
  } catch (e) {
    console.error('Failed to clear logs:', e)
  }
}

const getLogLevel = (line: string): string => {
  for (const level of Object.keys(levelColors)) {
    if (line.includes(` - ${level} - `)) {
      return level
    }
  }
  return ''
}

const startAutoRefresh = () => {
  if (refreshInterval) return
  refreshInterval = window.setInterval(fetchLogs, 5000)
}

const stopAutoRefresh = () => {
  if (refreshInterval) {
    clearInterval(refreshInterval)
    refreshInterval = null
  }
}

watch(autoRefresh, (newValue) => {
  if (newValue) {
    startAutoRefresh()
  } else {
    stopAutoRefresh()
  }
})

onMounted(() => {
  fetchLogs()
  if (autoRefresh.value) {
    startAutoRefresh()
  }
})

onUnmounted(() => {
  stopAutoRefresh()
})
</script>

<template>
  <div class="space-y-6">
    <!-- Page Header -->
    <div class="flex flex-wrap items-start justify-between gap-4">
      <div class="page-header mb-0">
        <h1 class="page-title">Logs</h1>
        <p class="page-subtitle">View application logs and debug information</p>
      </div>

      <div class="flex items-center gap-3">
        <label class="flex items-center gap-2 px-3 py-2 rounded-lg bg-white border border-stone-200 cursor-pointer hover:bg-stone-50 transition-colors">
          <input
            type="checkbox"
            v-model="autoRefresh"
            class="sr-only peer"
          />
          <div class="toggle toggle-sm" :class="autoRefresh ? 'toggle-on' : 'toggle-off'">
            <span class="toggle-knob"></span>
          </div>
          <span class="text-sm font-medium text-stone-600">Auto-refresh</span>
        </label>

        <button @click="fetchLogs" class="btn btn-secondary">
          <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15"/>
          </svg>
          Refresh
        </button>

        <button @click="clearLogs" class="btn btn-danger">
          <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16"/>
          </svg>
          Clear
        </button>
      </div>
    </div>

    <!-- Filters -->
    <div class="flex flex-wrap items-center gap-4">
      <div>
        <select v-model="selectedLevel" @change="fetchLogs" class="input">
          <option value="">All levels</option>
          <option value="DEBUG">DEBUG</option>
          <option value="INFO">INFO</option>
          <option value="WARNING">WARNING</option>
          <option value="ERROR">ERROR</option>
        </select>
      </div>

      <div>
        <select v-model.number="lineCount" @change="fetchLogs" class="input">
          <option :value="50">Last 50 lines</option>
          <option :value="100">Last 100 lines</option>
          <option :value="250">Last 250 lines</option>
          <option :value="500">Last 500 lines</option>
          <option :value="1000">Last 1000 lines</option>
        </select>
      </div>
    </div>

    <!-- Loading -->
    <div v-if="loading" class="flex justify-center py-16">
      <div class="flex items-center gap-3 text-stone-500">
        <svg class="animate-spin h-6 w-6 text-kindle-600" fill="none" viewBox="0 0 24 24">
          <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="3"></circle>
          <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
        </svg>
        <span class="text-sm font-medium">Loading logs...</span>
      </div>
    </div>

    <!-- Log Content -->
    <div v-else class="card p-0 overflow-hidden">
      <div v-if="logs.length === 0" class="empty-state py-12">
        <div class="empty-state-icon">
          <svg fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z"/>
          </svg>
        </div>
        <p class="empty-state-title">No log entries found</p>
        <p class="empty-state-description">
          Logs will appear here when the sync runs
        </p>
      </div>

      <div v-else class="font-mono text-xs overflow-x-auto max-h-[600px] overflow-y-auto scrollbar-hide">
        <div
          v-for="(line, index) in logs"
          :key="index"
          class="px-4 py-1.5 border-b border-stone-100 hover:bg-stone-50 transition-colors"
          :class="levelColors[getLogLevel(line)] || 'text-stone-700'"
        >
          {{ line }}
        </div>
      </div>
    </div>

    <!-- Status Bar -->
    <div class="flex items-center justify-between text-sm">
      <span class="text-stone-500 font-medium">{{ logs.length }} lines</span>
      <Transition
        enter-active-class="transition-opacity duration-200"
        enter-from-class="opacity-0"
        leave-active-class="transition-opacity duration-200"
        leave-to-class="opacity-0"
      >
        <span v-if="autoRefresh" class="flex items-center gap-2 text-stone-500">
          <span class="status-dot bg-success-500 animate-pulse"></span>
          <span>Auto-refreshing every 5s</span>
        </span>
      </Transition>
    </div>
  </div>
</template>
