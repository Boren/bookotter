<script setup lang="ts">
import { onMounted } from 'vue'
import { useRssStore } from '@/stores/rss'

const store = useRssStore()

onMounted(() => {
  store.fetchStatus()
})

const formatRelativeTime = (dateStr: string | null): string => {
  if (!dateStr) return 'Never'
  const then = new Date(dateStr).getTime()
  if (Number.isNaN(then)) return 'Unknown'
  
  const diffSeconds = Math.floor((Date.now() - then) / 1000)
  if (diffSeconds < 60) return 'Just now'
  
  const diffMinutes = Math.floor(diffSeconds / 60)
  if (diffMinutes < 60) return `${diffMinutes} min${diffMinutes !== 1 ? 's' : ''} ago`
  
  const diffHours = Math.floor(diffMinutes / 60)
  if (diffHours < 24) return `${diffHours} hr${diffHours !== 1 ? 's' : ''} ago`
  
  const diffDays = Math.floor(diffHours / 24)
  return `${diffDays} day${diffDays !== 1 ? 's' : ''} ago`
}

const getStatusColor = (status: string) => {
  switch (status) {
    case 'ok': return 'bg-success-500'
    case 'error': return 'bg-error-500'
    case 'rate_limited': return 'bg-warning-500'
    case 'no_book_search': return 'bg-stone-400'
    default: return 'bg-stone-400'
  }
}

const getStatusText = (status: string) => {
  switch (status) {
    case 'ok': return 'OK'
    case 'error': return 'Error'
    case 'rate_limited': return 'Rate Limited'
    case 'no_book_search': return 'No Book Search'
    default: return status
  }
}
</script>

<template>
  <section data-testid="rss-activity-card" class="card">
    <!-- Header -->
    <div class="flex items-center justify-between mb-6">
      <div class="flex items-center gap-3">
        <div class="icon-container shrink-0">
          <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 5c7.18 0 13 5.82 13 13M6 11a7 7 0 017 7m-6 0v.01M6 20h.01" />
          </svg>
        </div>
        <div>
          <h2 class="text-lg font-display font-semibold text-stone-900">RSS Sync</h2>
          <p class="text-sm text-stone-500">Auto-grab books from indexers</p>
        </div>
      </div>
      <button
        type="button"
        @click="store.triggerSync()"
        :disabled="store.syncInProgress"
        class="btn btn-secondary btn-sm shrink-0"
      >
        <svg
          v-if="store.syncInProgress"
          class="w-3.5 h-3.5 animate-spin"
          fill="none"
          viewBox="0 0 24 24"
        >
          <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="3"></circle>
          <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"></path>
        </svg>
        <svg
          v-else
          class="w-3.5 h-3.5"
          fill="none"
          stroke="currentColor"
          viewBox="0 0 24 24"
        >
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" />
        </svg>
        Trigger Sync
      </button>
    </div>

    <!-- Connect to store in T16 -->
    
    <!-- Indexer Table -->
    <div class="mb-6">
      <h3 class="text-sm font-medium text-stone-700 mb-3">Indexers</h3>
      <div class="overflow-x-auto -mx-6 px-6 sm:mx-0 sm:px-0">
        <table class="w-full min-w-[500px]">
          <thead>
            <tr>
              <th class="table-header text-left">Indexer</th>
              <th class="table-header text-left">Status</th>
              <th class="table-header text-right">Last Poll</th>
              <th class="table-header text-right">Seen</th>
              <th class="table-header text-right">Grabbed</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="indexer in store.indexers" :key="indexer.indexerId" class="table-row">
              <td class="table-cell font-medium text-stone-900">
                {{ indexer.indexerName }}
              </td>
              <td class="table-cell">
                <div class="flex items-center gap-2">
                  <span class="w-2 h-2 rounded-full" :class="getStatusColor(indexer.lastStatus || 'unknown')"></span>
                  <span class="text-stone-600">{{ getStatusText(indexer.lastStatus || 'unknown') }}</span>
                </div>
              </td>
              <td class="table-cell text-right text-stone-500 tabular-nums">
                {{ formatRelativeTime(indexer.lastPollAt) }}
              </td>
              <td class="table-cell text-right text-stone-600 tabular-nums">
                {{ indexer.itemsSeenCount }}
              </td>
              <td class="table-cell text-right text-stone-600 tabular-nums">
                {{ indexer.itemsGrabbedCount }}
              </td>
            </tr>
            <tr v-if="store.indexers.length === 0">
              <td colspan="5" class="table-cell text-center text-stone-500 py-4">
                No indexers configured for RSS sync.
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>

    <!-- Recent Matches -->
    <div>
      <h3 class="text-sm font-medium text-stone-700 mb-3">Recent Matches</h3>
      <div v-if="store.recentMatches.length > 0" class="space-y-2">
        <div 
          v-for="match in store.recentMatches.slice(0, 5)" 
          :key="match.guid"
          class="flex items-center justify-between p-3 rounded-xl bg-stone-50 border border-stone-100"
        >
          <div class="min-w-0 flex-1 pr-4">
            <p class="font-medium text-stone-900 truncate" :title="match.title">
              {{ match.title }}
            </p>
            <p class="text-xs text-stone-500 mt-0.5">
              via {{ match.indexer }}
            </p>
          </div>
          <div class="text-xs text-stone-500 tabular-nums shrink-0">
            {{ formatRelativeTime(match.matchedAt) }}
          </div>
        </div>
      </div>
      <div v-else class="text-sm text-stone-500 italic p-4 text-center bg-stone-50 rounded-xl border border-stone-100">
        No recent matches
      </div>
    </div>
  </section>
</template>
