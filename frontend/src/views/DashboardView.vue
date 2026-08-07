<script setup lang="ts">
import { onMounted } from 'vue'
import { useSyncStore } from '../stores/sync'
import RssActivityCard from '../components/RssActivityCard.vue'
import EreaderStatusWidget from '../components/ereader/EreaderStatusWidget.vue'

const syncStore = useSyncStore()

const statusBadgeClass = (status: string): string => {
  const map: Record<string, string> = {
    wanted: 'badge-warning',
    searching: 'badge-info',
    downloading: 'badge-info',
    in_library: 'badge-success',
    failed: 'badge-error',
  }
  return map[status] || 'badge-info'
}

const statusLabel = (status: string): string => {
  const map: Record<string, string> = {
    wanted: 'Wanted',
    searching: 'Searching',
    downloading: 'Downloading',
    in_library: 'In Library',
    failed: 'Failed',
    grabbed: 'Grabbed',
    importing: 'Importing',
  }
  return map[status] || status
}

onMounted(() => {
  syncStore.fetchPipelineStats()
  syncStore.fetchRecentBooks()
})
</script>

<template>
  <div class="space-y-8">
    <!-- Page Header -->
    <div class="page-header">
      <h1 class="page-title">Dashboard</h1>
      <p class="page-subtitle">
        Sync your Hardcover reading list to your E-reader
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

    <!-- Pipeline Status Card -->
    <div class="card animate-fade-in-up stagger-1">
      <div class="flex items-center gap-3 mb-6">
        <div class="icon-container">
          <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 17V7m0 10a2 2 0 01-2 2H5a2 2 0 01-2-2V7a2 2 0 012-2h2a2 2 0 012 2m0 10a2 2 0 002 2h2a2 2 0 002-2M9 7a2 2 0 012-2h2a2 2 0 012 2m0 10V7m0 10a2 2 0 002 2h2a2 2 0 002-2V7a2 2 0 00-2-2h-2a2 2 0 00-2 2"/>
          </svg>
        </div>
        <h2 class="text-lg font-display font-semibold text-stone-900">Pipeline Status</h2>
      </div>

      <div v-if="syncStore.pipelineStats" class="grid grid-cols-2 md:grid-cols-6 gap-4">
        <div class="text-center p-3 rounded-lg bg-amber-50 border border-amber-200">
          <p class="text-2xl font-semibold text-amber-700">{{ syncStore.pipelineStats.by_status?.wanted || 0 }}</p>
          <p class="text-xs font-medium uppercase tracking-wider text-amber-600 mt-1">Wanted</p>
        </div>
        <div class="text-center p-3 rounded-lg bg-blue-50 border border-blue-200">
          <p class="text-2xl font-semibold text-blue-700">{{ syncStore.pipelineStats.by_status?.searching || 0 }}</p>
          <p class="text-xs font-medium uppercase tracking-wider text-blue-600 mt-1">Searching</p>
        </div>
        <div class="text-center p-3 rounded-lg bg-indigo-50 border border-indigo-200">
          <p class="text-2xl font-semibold text-indigo-700">{{ syncStore.pipelineStats.by_status?.downloading || 0 }}</p>
          <p class="text-xs font-medium uppercase tracking-wider text-indigo-600 mt-1">Downloading</p>
        </div>
        <div class="text-center p-3 rounded-lg bg-green-50 border border-green-200">
          <p class="text-2xl font-semibold text-green-700">{{ syncStore.pipelineStats.by_status?.in_library || 0 }}</p>
          <p class="text-xs font-medium uppercase tracking-wider text-green-600 mt-1">In Library</p>
        </div>
        <div class="text-center p-3 rounded-lg bg-red-50 border border-red-200">
          <p class="text-2xl font-semibold text-red-700">{{ syncStore.pipelineStats.by_status?.failed || 0 }}</p>
          <p class="text-xs font-medium uppercase tracking-wider text-red-600 mt-1">Failed</p>
        </div>
        <div class="text-center p-3 rounded-lg bg-ereader-50 border border-ereader-200">
          <p class="text-2xl font-semibold text-ereader-700">{{ syncStore.pipelineStats.by_ereader_delivery_status?.PENDING || 0 }}</p>
          <p class="text-xs font-medium uppercase tracking-wider text-ereader-600 mt-1">Awaiting E-reader</p>
          <p v-if="syncStore.pipelineStats.by_ereader_delivery_status?.SKIPPED" class="text-[10px] text-amber-600 mt-0.5">
            {{ syncStore.pipelineStats.by_ereader_delivery_status.SKIPPED }} skipped
          </p>
        </div>
      </div>

      <div v-else class="text-center py-6 text-stone-500">
        <p class="text-sm">Loading pipeline status...</p>
      </div>
    </div>

    <!-- Quick Actions Card -->
    <div class="card animate-fade-in-up stagger-2">
      <div class="flex items-center gap-3 mb-6">
        <div class="icon-container">
          <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13 10V3L4 14h7v7l9-11h-7z"/>
          </svg>
        </div>
        <h2 class="text-lg font-display font-semibold text-stone-900">Quick Actions</h2>
      </div>

      <div class="flex flex-wrap gap-3">
        <button
          @click="syncStore.triggerHardcoverSync()"
          :disabled="syncStore.hardcoverSyncing"
          class="btn btn-secondary"
        >
          <svg v-if="syncStore.hardcoverSyncing" class="w-4 h-4 animate-spin" fill="none" viewBox="0 0 24 24">
            <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="3"></circle>
            <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
          </svg>
          <svg v-else class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15"/>
          </svg>
          {{ syncStore.hardcoverSyncing ? 'Syncing...' : 'Sync Hardcover' }}
        </button>
      </div>
    </div>

    <!-- E-reader Status Widget -->
    <div class="animate-fade-in-up stagger-3">
      <EreaderStatusWidget />
    </div>

    <!-- RSS Activity Card -->
    <div class="animate-fade-in-up stagger-3">
      <RssActivityCard />
    </div>

    <!-- Recent Additions Card -->
    <div class="card animate-fade-in-up stagger-4">
      <div class="flex items-center gap-3 mb-4">
        <div class="icon-container">
          <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 6v6m0 0v6m0-6h6m-6 0H6"/>
          </svg>
        </div>
        <h2 class="text-lg font-display font-semibold text-stone-900">Recent Additions</h2>
      </div>

      <div v-if="syncStore.recentBooks.length > 0" class="space-y-3">
        <router-link
          v-for="book in syncStore.recentBooks"
          :key="book.id"
          :to="`/library/${book.id}`"
          class="flex items-center gap-3 p-2 -mx-2 rounded-lg hover:bg-stone-50 transition-colors group"
        >
          <img
            v-if="book.cover_url"
            :src="book.cover_url"
            :alt="book.title"
            class="w-8 h-12 object-cover rounded-sm shadow-xs shrink-0"
          />
          <div v-else class="w-8 h-12 rounded-sm bg-stone-100 flex items-center justify-center shrink-0">
            <svg class="w-4 h-4 text-stone-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M12 6.253v13m0-13C10.832 5.477 9.246 5 7.5 5S4.168 5.477 3 6.253v13C4.168 18.477 5.754 18 7.5 18s3.332.477 4.5 1.253m0-13C13.168 5.477 14.754 5 16.5 5c1.747 0 3.332.477 4.5 1.253v13C19.832 18.477 18.247 18 16.5 18c-1.746 0-3.332.477-4.5 1.253"/>
            </svg>
          </div>
          <div class="min-w-0 flex-1">
            <p class="text-sm font-medium text-stone-800 line-clamp-1 group-hover:text-ereader-600 transition-colors">{{ book.title }}</p>
            <p class="text-xs text-stone-500 line-clamp-1">{{ book.author?.name || 'Unknown author' }}</p>
          </div>
          <span class="badge shrink-0" :class="statusBadgeClass(book.status)">
            {{ statusLabel(book.status) }}
          </span>
        </router-link>
      </div>

      <div v-else class="empty-state">
        <div class="empty-state-icon">
          <svg fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M12 6.253v13m0-13C10.832 5.477 9.246 5 7.5 5S4.168 5.477 3 6.253v13C4.168 18.477 5.754 18 7.5 18s3.332.477 4.5 1.253m0-13C13.168 5.477 14.754 5 16.5 5c1.747 0 3.332.477 4.5 1.253v13C19.832 18.477 18.247 18 16.5 18c-1.746 0-3.332.477-4.5 1.253"/>
          </svg>
        </div>
        <p class="empty-state-title">No books in library yet</p>
        <p class="empty-state-description">
          Books will appear here as they are added to your library
        </p>
      </div>
    </div>
  </div>
</template>
