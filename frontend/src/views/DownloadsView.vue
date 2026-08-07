<script setup lang="ts">
import { onMounted, onUnmounted, ref, watch } from 'vue'
import { useDownloadStore } from '../stores/download'
import type { DownloadStatus } from '../types'

const downloadStore = useDownloadStore()
const statusFilter = ref<string>('')
let refreshInterval: ReturnType<typeof setInterval> | null = null

const fetchData = () => {
  downloadStore.fetchDownloads(statusFilter.value || undefined)
}

watch(statusFilter, () => fetchData())

const handleCancel = async (downloadId: number) => {
  if (!confirm('Cancel this download?')) return
  await downloadStore.cancelDownload(downloadId)
}

const formatSpeed = (bytesPerSec: number | undefined) => {
  if (!bytesPerSec || bytesPerSec <= 0) return '—'
  if (bytesPerSec >= 1_000_000) return `${(bytesPerSec / 1_000_000).toFixed(1)} MB/s`
  return `${Math.round(bytesPerSec / 1_000)} KB/s`
}

const formatEta = (seconds: number | undefined) => {
  if (!seconds || seconds <= 0 || seconds >= 864000) return '—'
  if (seconds < 60) return `${seconds}s`
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m`
  const hours = Math.floor(seconds / 3600)
  const mins = Math.floor((seconds % 3600) / 60)
  return `${hours}h ${mins}m`
}

const formatSize = (bytes: number | undefined) => {
  if (!bytes) return '—'
  if (bytes >= 1_000_000_000) return `${(bytes / 1_000_000_000).toFixed(1)} GB`
  if (bytes >= 1_000_000) return `${(bytes / 1_000_000).toFixed(1)} MB`
  return `${Math.round(bytes / 1_000)} KB`
}

const statusBadgeClass = (status: DownloadStatus) => {
  const map: Record<DownloadStatus, string> = {
    queued: 'badge-neutral',
    downloading: 'badge-info',
    completed: 'badge-success',
    importing: 'badge-warning',
    imported: 'badge-success',
    failed: 'badge-error',
  }
  return map[status] || 'badge-neutral'
}

const canCancel = (status: DownloadStatus) => {
  return status === 'queued' || status === 'downloading'
}

const progressPercent = (progress: number | undefined) => {
  if (progress === undefined) return 0
  return Math.round(progress * 100)
}

const filterOptions: { label: string; value: string }[] = [
  { label: 'All', value: '' },
  { label: 'Active', value: 'downloading' },
  { label: 'Queued', value: 'queued' },
  { label: 'Completed', value: 'completed' },
  { label: 'Imported', value: 'imported' },
  { label: 'Failed', value: 'failed' },
]

onMounted(() => {
  fetchData()
  refreshInterval = setInterval(fetchData, 5000)
})

onUnmounted(() => {
  if (refreshInterval) clearInterval(refreshInterval)
})
</script>

<template>
  <div class="space-y-8">
    <!-- Page Header -->
    <div class="page-header">
      <div class="flex items-center justify-between">
        <div>
          <h1 class="page-title">Downloads</h1>
          <p class="page-subtitle">Active and recent download queue</p>
        </div>
        <div class="flex items-center gap-3">
          <div v-if="downloadStore.isDownloading" class="flex items-center gap-2 text-info-600">
            <svg class="w-4 h-4 animate-spin" fill="none" viewBox="0 0 24 24">
              <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="3"></circle>
              <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
            </svg>
            <span class="text-sm font-medium">Downloading</span>
          </div>
          <span class="text-xs text-stone-500">Auto-refreshes every 5s</span>
        </div>
      </div>
    </div>

    <!-- Error Banner -->
    <Transition
      enter-active-class="transition-all duration-300 ease-out"
      enter-from-class="opacity-0 -translate-y-2"
      enter-to-class="opacity-100 translate-y-0"
      leave-active-class="transition-all duration-200 ease-in"
      leave-from-class="opacity-100 translate-y-0"
      leave-to-class="opacity-0 -translate-y-2"
    >
      <div v-if="downloadStore.error" class="bg-error-50 border border-error-200 rounded-xl p-4 flex items-start gap-3">
        <div class="shrink-0 mt-0.5">
          <svg class="w-5 h-5 text-error-500" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 8v4m0 4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z"/>
          </svg>
        </div>
        <div class="flex-1 min-w-0">
          <p class="text-sm font-medium text-error-800">Download error</p>
          <p class="text-sm text-error-600 mt-0.5">{{ downloadStore.error }}</p>
        </div>
        <button
          @click="downloadStore.clearError()"
          class="shrink-0 p-1 rounded-lg text-error-400 hover:text-error-600 hover:bg-error-100 transition-colors"
        >
          <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"/>
          </svg>
        </button>
      </div>
    </Transition>

    <!-- Filter Tabs -->
    <div class="flex items-center gap-2 flex-wrap">
      <button
        v-for="opt in filterOptions"
        :key="opt.value"
        @click="statusFilter = opt.value"
        class="px-3 py-1.5 rounded-lg text-sm font-medium transition-all duration-200"
        :class="statusFilter === opt.value
          ? 'bg-ereader-100 text-ereader-800 border border-ereader-200'
          : 'text-stone-600 hover:text-stone-900 hover:bg-stone-100 border border-transparent'"
      >
        {{ opt.label }}
      </button>
    </div>

    <!-- Loading State -->
    <div v-if="downloadStore.loading && downloadStore.downloads.length === 0" class="flex justify-center py-16">
      <div class="flex items-center gap-3 text-stone-500">
        <svg class="animate-spin h-6 w-6 text-ereader-600" fill="none" viewBox="0 0 24 24">
          <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="3"></circle>
          <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
        </svg>
        <span class="text-sm font-medium">Loading downloads...</span>
      </div>
    </div>

    <!-- Downloads Table -->
    <div v-else-if="downloadStore.downloads.length > 0" class="card p-0 overflow-hidden animate-fade-in">
      <div class="overflow-x-auto">
        <table class="w-full">
          <thead>
            <tr>
              <th class="table-header text-left">Book</th>
              <th class="table-header text-left">Status</th>
              <th class="table-header text-left min-w-[180px]">Progress</th>
              <th class="table-header text-right">Speed</th>
              <th class="table-header text-right">ETA</th>
              <th class="table-header text-right">Size</th>
              <th class="table-header text-center w-16"></th>
            </tr>
          </thead>
          <tbody>
            <tr
              v-for="(download, index) in downloadStore.downloads"
              :key="download.id"
              class="table-row animate-fade-in"
              :style="{ animationDelay: `${index * 30}ms` }"
            >
              <!-- Book Info -->
              <td class="table-cell">
                <div class="flex items-center gap-3">
                  <div class="shrink-0">
                    <img
                      v-if="download.book?.cover_url"
                      :src="download.book.cover_url"
                      :alt="download.book?.title"
                      class="w-8 h-12 object-cover rounded-sm shadow-warm-sm"
                    />
                    <div v-else class="w-8 h-12 rounded-sm bg-stone-100 flex items-center justify-center">
                      <svg class="w-4 h-4 text-stone-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M12 6.253v13m0-13C10.832 5.477 9.246 5 7.5 5S4.168 5.477 3 6.253v13C4.168 18.477 5.754 18 7.5 18s3.332.477 4.5 1.253m0-13C13.168 5.477 14.754 5 16.5 5c1.747 0 3.332.477 4.5 1.253v13C19.832 18.477 18.247 18 16.5 18c-1.746 0-3.332.477-4.5 1.253"/>
                      </svg>
                    </div>
                  </div>
                  <div class="min-w-0">
                    <p class="text-sm font-medium text-stone-900 line-clamp-1">
                      {{ download.book?.title || download.torrent_name }}
                    </p>
                    <p v-if="download.book?.author" class="text-xs text-stone-500 line-clamp-1">
                      {{ download.book.author }}
                    </p>
                    <p v-else class="text-xs text-stone-400 line-clamp-1">
                      {{ download.indexer_name }}
                    </p>
                  </div>
                </div>
              </td>

              <!-- Status Badge -->
              <td class="table-cell">
                <span class="badge" :class="statusBadgeClass(download.status)">
                  {{ download.status }}
                </span>
              </td>

              <!-- Progress Bar -->
              <td class="table-cell">
                <div v-if="download.status === 'downloading' || download.status === 'queued'" class="space-y-1">
                  <div class="progress-bar" :class="{ 'progress-bar-animated': download.status === 'downloading' }">
                    <div
                      class="progress-bar-fill"
                      :style="{ width: `${progressPercent(download.progress)}%` }"
                    ></div>
                  </div>
                  <p class="text-xs text-stone-500 tabular-nums">{{ progressPercent(download.progress) }}%</p>
                </div>
                <div v-else-if="download.status === 'completed' || download.status === 'imported'" class="text-xs text-success-600 font-medium">
                  Complete
                </div>
                <div v-else-if="download.status === 'failed'" class="text-xs text-error-600 line-clamp-1" :title="download.error_message || ''">
                  {{ download.error_message || 'Failed' }}
                </div>
                <div v-else class="text-xs text-stone-400">
                  {{ download.status }}
                </div>
              </td>

              <!-- Speed -->
              <td class="table-cell text-right">
                <span class="text-sm tabular-nums" :class="download.download_speed ? 'text-stone-800' : 'text-stone-400'">
                  {{ formatSpeed(download.download_speed) }}
                </span>
              </td>

              <!-- ETA -->
              <td class="table-cell text-right">
                <span class="text-sm tabular-nums" :class="download.eta ? 'text-stone-800' : 'text-stone-400'">
                  {{ formatEta(download.eta) }}
                </span>
              </td>

              <!-- Size -->
              <td class="table-cell text-right">
                <span class="text-sm tabular-nums text-stone-600">
                  {{ formatSize(download.size) }}
                </span>
              </td>

              <!-- Cancel Button -->
              <td class="table-cell text-center">
                <button
                  v-if="canCancel(download.status)"
                  @click="handleCancel(download.id)"
                  class="p-1.5 rounded-lg text-stone-400 hover:text-error-600 hover:bg-error-50 transition-colors"
                  title="Cancel download"
                >
                  <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"/>
                  </svg>
                </button>
              </td>
            </tr>
          </tbody>
        </table>
      </div>

      <!-- Summary Footer -->
      <div class="px-4 py-3 border-t border-stone-100 bg-stone-50/50 flex items-center justify-between">
        <span class="text-xs text-stone-500">
          {{ downloadStore.total }} download{{ downloadStore.total !== 1 ? 's' : '' }} total
        </span>
        <span v-if="downloadStore.queueLength > 0" class="text-xs font-medium text-info-600">
          {{ downloadStore.queueLength }} active
        </span>
      </div>
    </div>

    <!-- Empty State -->
    <div v-else class="card">
      <div class="empty-state">
        <div class="empty-state-icon">
          <svg fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M7 16a4 4 0 01-.88-7.903A5 5 0 1115.9 6L16 6a5 5 0 011 9.9M9 19l3 3m0 0l3-3m-3 3V10"/>
          </svg>
        </div>
        <p class="empty-state-title">No downloads in queue</p>
        <p class="empty-state-description">
          Downloads will appear here when books are grabbed for download
        </p>
      </div>
    </div>
  </div>
</template>
