<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import type { SyncRun } from '../types'

const router = useRouter()
const runs = ref<SyncRun[]>([])
const total = ref(0)
const loading = ref(true)
const page = ref(1)
const limit = 10

const fetchRuns = async () => {
  loading.value = true
  try {
    const offset = (page.value - 1) * limit
    const response = await fetch(`/api/sync/runs?limit=${limit}&offset=${offset}`)
    const data = await response.json()
    runs.value = data.runs
    total.value = data.total
  } catch (e) {
    console.error('Failed to fetch runs:', e)
  } finally {
    loading.value = false
  }
}

const formatDate = (dateStr: string) => {
  return new Date(dateStr).toLocaleString()
}

const formatDuration = (startStr: string, endStr: string | null) => {
  if (!endStr) return 'Running...'
  const start = new Date(startStr).getTime()
  const end = new Date(endStr).getTime()
  const seconds = Math.floor((end - start) / 1000)
  if (seconds < 60) return `${seconds}s`
  const minutes = Math.floor(seconds / 60)
  const remainingSeconds = seconds % 60
  return `${minutes}m ${remainingSeconds}s`
}

const viewRun = (id: number) => {
  router.push(`/history/${id}`)
}

const deleteRun = async (id: number, event: Event) => {
  event.stopPropagation()
  if (!confirm('Delete this sync run?')) return

  try {
    await fetch(`/api/sync/runs/${id}`, { method: 'DELETE' })
    fetchRuns()
  } catch (e) {
    console.error('Failed to delete run:', e)
  }
}

const totalPages = () => Math.ceil(total.value / limit)

onMounted(fetchRuns)
</script>

<template>
  <div class="space-y-8">
    <!-- Page Header -->
    <div class="page-header">
      <h1 class="page-title">Sync History</h1>
      <p class="page-subtitle">View past sync operations and their results</p>
    </div>

    <!-- Loading State -->
    <div v-if="loading" class="flex justify-center py-16">
      <div class="flex items-center gap-3 text-stone-500">
        <svg class="animate-spin h-6 w-6 text-kindle-600" fill="none" viewBox="0 0 24 24">
          <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="3"></circle>
          <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
        </svg>
        <span class="text-sm font-medium">Loading history...</span>
      </div>
    </div>

    <!-- Runs List -->
    <div v-else-if="runs.length > 0" class="space-y-4">
      <div
        v-for="(run, index) in runs"
        :key="run.id"
        @click="viewRun(run.id)"
        class="card card-hover cursor-pointer animate-fade-in-up"
        :style="{ animationDelay: `${index * 50}ms` }"
      >
        <div class="flex items-center justify-between">
          <div class="flex items-center gap-4">
            <span
              class="badge"
              :class="{
                'badge-success': run.status === 'completed',
                'badge-error': run.status === 'failed',
                'badge-warning': run.status === 'cancelled',
                'badge-info': run.status === 'running',
              }"
            >
              {{ run.status }}
            </span>
            <div>
              <p class="font-medium text-stone-900">
                {{ formatDate(run.started_at) }}
              </p>
              <p class="text-sm text-stone-500">
                {{ run.trigger_type === 'scheduled' ? 'Scheduled' : 'Manual' }}
                <span v-if="run.dry_run" class="text-warning-600 font-medium">(Dry run)</span>
              </p>
            </div>
          </div>

          <div class="flex items-center gap-6">
            <div class="text-right hidden sm:block">
              <p class="text-xs font-medium uppercase tracking-wider text-stone-500">Duration</p>
              <p class="font-medium text-stone-800">{{ formatDuration(run.started_at, run.completed_at) }}</p>
            </div>
            <div class="text-right">
              <p class="text-xs font-medium uppercase tracking-wider text-stone-500">Transferred</p>
              <p class="font-medium">
                <span class="text-success-600">{{ run.transferred }}</span>
                <span class="text-stone-400"> / {{ run.total_books }}</span>
              </p>
            </div>
            <button
              @click="deleteRun(run.id, $event)"
              class="p-2 rounded-lg text-stone-400 hover:text-error-600 hover:bg-error-50 transition-colors"
            >
              <svg class="h-5 w-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
              </svg>
            </button>
          </div>
        </div>

        <!-- Stats Summary -->
        <div class="divider"></div>
        <div class="grid grid-cols-4 gap-4">
          <div>
            <p class="text-xs font-medium uppercase tracking-wider text-stone-500 mb-1">Matched</p>
            <p class="font-semibold text-stone-800">{{ run.matched }}</p>
          </div>
          <div>
            <p class="text-xs font-medium uppercase tracking-wider text-stone-500 mb-1">Skipped</p>
            <p class="font-semibold text-stone-800">{{ run.skipped }}</p>
          </div>
          <div>
            <p class="text-xs font-medium uppercase tracking-wider text-stone-500 mb-1">Not Found</p>
            <p class="font-semibold text-warning-600">{{ run.not_found }}</p>
          </div>
          <div>
            <p class="text-xs font-medium uppercase tracking-wider text-stone-500 mb-1">Failed</p>
            <p class="font-semibold text-error-600">{{ run.failed }}</p>
          </div>
        </div>
      </div>

      <!-- Pagination -->
      <div v-if="totalPages() > 1" class="flex items-center justify-center gap-3 pt-4">
        <button
          @click="page--; fetchRuns()"
          :disabled="page === 1"
          class="btn btn-secondary"
        >
          <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M15 19l-7-7 7-7"/>
          </svg>
          Previous
        </button>
        <span class="px-4 py-2 text-sm font-medium text-stone-600">
          Page {{ page }} of {{ totalPages() }}
        </span>
        <button
          @click="page++; fetchRuns()"
          :disabled="page === totalPages()"
          class="btn btn-secondary"
        >
          Next
          <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 5l7 7-7 7"/>
          </svg>
        </button>
      </div>
    </div>

    <!-- Empty State -->
    <div v-else class="card">
      <div class="empty-state">
        <div class="empty-state-icon">
          <svg fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z"/>
          </svg>
        </div>
        <p class="empty-state-title">No sync history yet</p>
        <p class="empty-state-description">
          Start your first sync to see results here
        </p>
        <router-link to="/" class="btn btn-primary">
          Start Syncing
          <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 5l7 7-7 7"/>
          </svg>
        </router-link>
      </div>
    </div>
  </div>
</template>
