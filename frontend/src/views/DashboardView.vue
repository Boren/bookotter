<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useSyncStore } from '../stores/sync'
import LatestChanges from '../components/LatestChanges.vue'
import type { Kindle } from '../types'

const syncStore = useSyncStore()
const kindles = ref<Kindle[]>([])
const selectedKindle = ref<string>('')
const dryRun = ref(false)

const fetchKindles = async () => {
  try {
    const response = await fetch('/api/kindles')
    kindles.value = await response.json()
    if (kindles.value.length > 0 && !selectedKindle.value) {
      selectedKindle.value = kindles.value[0].id
    }
  } catch (e) {
    console.error('Failed to fetch kindles:', e)
  }
}

const handleStartSync = async () => {
  syncStore.clearError()
  try {
    await syncStore.startSync({
      kindle_device: selectedKindle.value || undefined,
      dry_run: dryRun.value,
    })
  } catch (e) {
    // Error is already set in the store
  }
}

const handleStopSync = async () => {
  try {
    await syncStore.stopSync()
  } catch (e) {
    console.error('Failed to stop sync:', e)
  }
}

const formatDate = (dateStr: string | null) => {
  if (!dateStr) return 'Never'
  const date = new Date(dateStr)
  const now = new Date()
  const diff = now.getTime() - date.getTime()
  const hours = Math.floor(diff / (1000 * 60 * 60))
  const days = Math.floor(hours / 24)

  if (hours < 1) return 'Just now'
  if (hours < 24) return `${hours}h ago`
  if (days < 7) return `${days}d ago`
  return date.toLocaleDateString()
}

const formatBytes = (bytes: number) => {
  if (bytes >= 1_000_000) {
    return `${(bytes / 1_000_000).toFixed(1)} MB`
  }
  return `${Math.round(bytes / 1_000)} KB`
}

onMounted(() => {
  syncStore.fetchStatus()
  syncStore.fetchStats()
  syncStore.fetchLatestChanges()
  fetchKindles()
})
</script>

<template>
  <div class="space-y-8">
    <!-- Page Header -->
    <div class="page-header">
      <h1 class="page-title">Dashboard</h1>
      <p class="page-subtitle">
        Sync your Hardcover reading list to your Kindle
      </p>
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
      <div v-if="syncStore.error" class="bg-error-50 border border-error-200 rounded-xl p-4 flex items-start gap-3 animate-fade-in">
        <div class="shrink-0 mt-0.5">
          <svg class="w-5 h-5 text-error-500" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 8v4m0 4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z"/>
          </svg>
        </div>
        <div class="flex-1 min-w-0">
          <p class="text-sm font-medium text-error-800">Something went wrong</p>
          <p class="text-sm text-error-600 mt-0.5">{{ syncStore.error }}</p>
        </div>
        <button
          @click="syncStore.clearError()"
          class="shrink-0 p-1 rounded-lg text-error-400 hover:text-error-600 hover:bg-error-100 transition-colors"
        >
          <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"/>
          </svg>
        </button>
      </div>
    </Transition>

    <!-- Main Sync Control Card -->
    <div class="card card-accent">
      <div class="flex items-center gap-4 mb-6">
        <div class="icon-container-primary">
          <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15"/>
          </svg>
        </div>
        <div>
          <h2 class="text-xl font-display font-semibold text-stone-900">Sync Control</h2>
          <p class="text-sm text-stone-500">Transfer books from Hardcover to your Kindle</p>
        </div>
      </div>

      <!-- Live Progress -->
      <div v-if="syncStore.isRunning" class="mb-8 animate-fade-in">
        <div class="bg-kindle-50 border border-kindle-200 rounded-xl p-5">
          <div class="flex items-center justify-between mb-3">
            <div class="flex items-center gap-3">
              <!-- Book Cover Thumbnail -->
              <div class="relative shrink-0">
                <img
                  v-if="syncStore.progress?.book?.cover_url"
                  :src="syncStore.progress.book.cover_url"
                  :alt="syncStore.progress.book.title"
                  class="w-10 h-14 object-cover rounded-sm shadow-xs"
                />
                <div v-else class="w-10 h-14 rounded-sm bg-kindle-100 flex items-center justify-center">
                  <svg class="w-5 h-5 text-kindle-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M12 6.253v13m0-13C10.832 5.477 9.246 5 7.5 5S4.168 5.477 3 6.253v13C4.168 18.477 5.754 18 7.5 18s3.332.477 4.5 1.253m0-13C13.168 5.477 14.754 5 16.5 5c1.747 0 3.332.477 4.5 1.253v13C19.832 18.477 18.247 18 16.5 18c-1.746 0-3.332.477-4.5 1.253"/>
                  </svg>
                </div>
                <!-- Spinner overlay -->
                <div class="absolute -bottom-1 -right-1 w-5 h-5 rounded-full bg-white shadow-sm flex items-center justify-center">
                  <svg class="w-3 h-3 text-kindle-600 animate-spin" fill="none" viewBox="0 0 24 24">
                    <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="3"></circle>
                    <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
                  </svg>
                </div>
              </div>
              <div class="min-w-0">
                <p class="font-medium text-stone-800 line-clamp-1">
                  {{ syncStore.progress?.book?.title || 'Starting sync...' }}
                </p>
                <p class="text-sm" :class="syncStore.progress?.book?.status === 'failed' ? 'text-error-600' : 'text-stone-600'">
                  {{ syncStore.progress?.book?.status === 'failed' && syncStore.progress?.book?.error_message
                    ? (syncStore.progress.book.error_message.startsWith('Local file not found') ? 'File not found'
                      : syncStore.progress.book.error_message.includes('size mismatch') ? 'Transfer incomplete'
                      : 'Transfer failed')
                    : syncStore.progress?.book?.status || 'Initializing' }}
                </p>
              </div>
            </div>
            <span class="text-sm font-medium text-kindle-700 tabular-nums">
              {{ syncStore.progress?.current || 0 }} / {{ syncStore.progress?.total || 0 }}
            </span>
          </div>
          <div class="progress-bar progress-bar-animated">
            <div
              class="progress-bar-fill"
              :style="{ width: `${syncStore.progressPercent}%` }"
            ></div>
          </div>

          <!-- Transfer Progress (when actively transferring a file) -->
          <Transition
            enter-active-class="transition-all duration-200 ease-out"
            enter-from-class="opacity-0 translate-y-1"
            enter-to-class="opacity-100 translate-y-0"
            leave-active-class="transition-all duration-150 ease-in"
            leave-from-class="opacity-100 translate-y-0"
            leave-to-class="opacity-0 translate-y-1"
          >
            <div v-if="syncStore.transferProgress" class="mt-4 pt-4 border-t border-kindle-200">
              <div class="flex items-center justify-between text-xs text-kindle-600 mb-2">
                <span class="flex items-center gap-1.5">
                  <svg class="w-3.5 h-3.5 animate-pulse" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M7 16V4m0 0L3 8m4-4l4 4m6 0v12m0 0l4-4m-4 4l-4-4"/>
                  </svg>
                  Transferring file...
                </span>
                <span class="tabular-nums">
                  {{ formatBytes(syncStore.transferProgress.bytes_transferred) }} / {{ formatBytes(syncStore.transferProgress.bytes_total) }}
                </span>
              </div>
              <div class="flex items-center gap-3">
                <div class="flex-1 h-1.5 bg-kindle-100 rounded-full overflow-hidden">
                  <div
                    class="h-full bg-kindle-500 rounded-full transition-all duration-200"
                    :style="{ width: `${syncStore.transferProgress.percentage}%` }"
                  ></div>
                </div>
                <div class="flex items-center gap-2 text-xs tabular-nums text-kindle-600">
                  <span class="font-medium">{{ syncStore.transferSpeedFormatted }}</span>
                  <span class="text-kindle-400">•</span>
                  <span>{{ syncStore.transferEtaFormatted }} left</span>
                </div>
              </div>
            </div>
          </Transition>
        </div>
      </div>

      <!-- Sync Options -->
      <div v-else class="space-y-6">
        <div class="grid gap-6 md:grid-cols-2">
          <!-- Kindle Selection -->
          <div>
            <label class="label">Target Device</label>
            <select v-model="selectedKindle" class="input">
              <option v-for="kindle in kindles" :key="kindle.id" :value="kindle.id">
                {{ kindle.name }}
              </option>
            </select>
          </div>

          <!-- Dry Run Toggle -->
          <div class="flex items-end">
            <label class="flex items-center gap-3 p-3 rounded-xl bg-stone-50 border border-stone-200 cursor-pointer hover:bg-stone-100 transition-colors w-full">
              <input
                type="checkbox"
                v-model="dryRun"
                class="sr-only peer"
              />
              <div class="toggle" :class="dryRun ? 'toggle-on' : 'toggle-off'">
                <span class="toggle-knob"></span>
              </div>
              <div>
                <span class="text-sm font-medium text-stone-700">Dry Run</span>
                <p class="text-xs text-stone-500">Simulate without transferring</p>
              </div>
            </label>
          </div>
        </div>

      </div>

      <!-- Action Buttons -->
      <div class="mt-8 flex flex-wrap gap-3">
        <button
          v-if="!syncStore.isRunning"
          @click="handleStartSync"
          class="btn btn-primary btn-lg"
        >
          <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M14.752 11.168l-3.197-2.132A1 1 0 0010 9.87v4.263a1 1 0 001.555.832l3.197-2.132a1 1 0 000-1.664z"/>
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M21 12a9 9 0 11-18 0 9 9 0 0118 0z"/>
          </svg>
          Start Sync
        </button>
        <button
          v-else
          @click="handleStopSync"
          class="btn btn-danger btn-lg"
        >
          <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M21 12a9 9 0 11-18 0 9 9 0 0118 0z"/>
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 10a1 1 0 011-1h4a1 1 0 011 1v4a1 1 0 01-1 1h-4a1 1 0 01-1-1v-4z"/>
          </svg>
          Stop Sync
        </button>
      </div>
    </div>

    <!-- Latest Changes Section -->
    <div class="card animate-fade-in-up stagger-1">
      <div class="flex items-center gap-3 mb-4">
        <div class="icon-container">
          <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M7 16V4m0 0L3 8m4-4l4 4m6 0v12m0 0l4-4m-4 4l-4-4"/>
          </svg>
        </div>
        <h2 class="text-lg font-display font-semibold text-stone-900">Latest Changes</h2>
      </div>

      <LatestChanges
        v-if="syncStore.latestChanges.length > 0"
        :books="syncStore.latestChanges"
      />

      <div v-else class="text-center py-8 text-stone-500">
        <svg class="w-12 h-12 mx-auto mb-3 text-stone-300" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M12 6.253v13m0-13C10.832 5.477 9.246 5 7.5 5S4.168 5.477 3 6.253v13C4.168 18.477 5.754 18 7.5 18s3.332.477 4.5 1.253m0-13C13.168 5.477 14.754 5 16.5 5c1.747 0 3.332.477 4.5 1.253v13C19.832 18.477 18.247 18 16.5 18c-1.746 0-3.332.477-4.5 1.253"/>
        </svg>
        <p class="text-sm">No recent transfers or removals</p>
      </div>
    </div>

    <!-- Latest Sync Card -->
    <div v-if="syncStore.latestRun" class="card animate-fade-in-up stagger-5">
      <div class="flex items-center justify-between mb-6">
        <div class="flex items-center gap-3">
          <div class="icon-container">
            <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z"/>
            </svg>
          </div>
          <h2 class="text-lg font-display font-semibold text-stone-900">Latest Sync</h2>
        </div>
        <span
          class="badge"
          :class="{
            'badge-success': syncStore.latestRun.status === 'completed',
            'badge-error': syncStore.latestRun.status === 'failed',
            'badge-warning': syncStore.latestRun.status === 'cancelled',
            'badge-info': syncStore.latestRun.status === 'running',
          }"
        >
          {{ syncStore.latestRun.status }}
        </span>
      </div>

      <div class="grid grid-cols-2 md:grid-cols-4 gap-6">
        <div>
          <p class="text-xs font-medium uppercase tracking-wider text-stone-500 mb-1">Started</p>
          <p class="text-sm font-medium text-stone-800">{{ formatDate(syncStore.latestRun.started_at) }}</p>
        </div>
        <div>
          <p class="text-xs font-medium uppercase tracking-wider text-stone-500 mb-1">Transferred</p>
          <p class="text-sm font-medium text-stone-800">
            <span class="text-success-600">{{ syncStore.latestRun.transferred }}</span>
            <span class="text-stone-400"> / {{ syncStore.latestRun.total_books }}</span>
          </p>
        </div>
        <div>
          <p class="text-xs font-medium uppercase tracking-wider text-stone-500 mb-1">Trigger</p>
          <p class="text-sm font-medium text-stone-800 capitalize">{{ syncStore.latestRun.trigger_type }}</p>
        </div>
        <div>
          <p class="text-xs font-medium uppercase tracking-wider text-stone-500 mb-1">Mode</p>
          <p class="text-sm font-medium text-stone-800">
            {{ syncStore.latestRun.dry_run ? 'Dry Run' : 'Live' }}
          </p>
        </div>
        <div v-if="syncStore.latestRun.cleaned_up > 0">
          <p class="text-xs font-medium uppercase tracking-wider text-stone-500 mb-1">Cleaned Up</p>
          <p class="text-sm font-medium text-purple-600">
            {{ syncStore.latestRun.cleaned_up }} removed
          </p>
        </div>
      </div>

      <div class="divider"></div>

      <router-link
        :to="`/history/${syncStore.latestRun.id}`"
        class="inline-flex items-center gap-2 text-sm font-medium text-kindle-600 hover:text-kindle-700 transition-colors group"
      >
        View full details
        <svg class="w-4 h-4 transition-transform group-hover:translate-x-1" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 5l7 7-7 7"/>
        </svg>
      </router-link>
    </div>

    <!-- Empty State for Latest Sync -->
    <div v-else class="card">
      <div class="empty-state">
        <div class="empty-state-icon">
          <svg fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M12 6.253v13m0-13C10.832 5.477 9.246 5 7.5 5S4.168 5.477 3 6.253v13C4.168 18.477 5.754 18 7.5 18s3.332.477 4.5 1.253m0-13C13.168 5.477 14.754 5 16.5 5c1.747 0 3.332.477 4.5 1.253v13C19.832 18.477 18.247 18 16.5 18c-1.746 0-3.332.477-4.5 1.253"/>
          </svg>
        </div>
        <p class="empty-state-title">No syncs yet</p>
        <p class="empty-state-description">
          Start your first sync to transfer books from your Hardcover list to your Kindle
        </p>
      </div>
    </div>
  </div>
</template>
