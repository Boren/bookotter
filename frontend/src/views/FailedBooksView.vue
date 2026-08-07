<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useFailedStore } from '../stores/failed'
import { useLibraryStore } from '../stores/library'
import StatusBadge from '../components/StatusBadge.vue'

const store = useFailedStore()
const libraryStore = useLibraryStore()
const retryingIds = ref<Set<number>>(new Set())

const humanizeReason = (reason: string | null) => {
  if (!reason) return 'Unknown error'
  const spaced = reason.replace(/_/g, ' ')
  return spaced.charAt(0).toUpperCase() + spaced.slice(1)
}

const handleRetry = async (bookId: number) => {
  retryingIds.value.add(bookId)
  try {
    await libraryStore.retryBook(bookId)
  } finally {
    retryingIds.value.delete(bookId)
  }
}

onMounted(() => {
  store.fetchFailed()
})
</script>

<template>
  <div class="space-y-6">
    <div class="page-header">
      <div class="flex flex-col sm:flex-row sm:items-end sm:justify-between gap-2">
        <div>
          <h1 class="page-title">Failed Books</h1>
          <p class="page-subtitle">Manage books that encountered errors during automation</p>
        </div>
      </div>
    </div>

    <div v-if="store.loading" class="flex justify-center py-16">
      <div class="flex items-center gap-3 text-stone-500">
        <svg class="animate-spin h-6 w-6 text-ereader-600" fill="none" viewBox="0 0 24 24">
          <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="3"></circle>
          <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
        </svg>
        <span class="text-sm font-medium">Loading failed books...</span>
      </div>
    </div>

    <div v-else-if="store.error" class="bg-error-50 border border-error-200 rounded-xl p-4 flex items-start gap-3">
      <svg class="w-5 h-5 text-error-500 shrink-0 mt-0.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 8v4m0 4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z"/>
      </svg>
      <div class="flex-1 min-w-0">
        <p class="text-sm font-medium text-error-800">Failed to load books</p>
        <p class="text-sm text-error-600 mt-0.5">{{ store.error }}</p>
      </div>
    </div>

    <div v-else-if="store.permanent_failed.length === 0 && store.recent_failures.length === 0" class="card" data-testid="dlq-empty">
      <div class="empty-state">
        <div class="empty-state-icon">
          <svg fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z"/>
          </svg>
        </div>
        <p class="empty-state-title">No failed books! All your automation is healthy.</p>
      </div>
    </div>

    <div v-else class="space-y-8">
      <div v-if="store.permanent_failed.length > 0" class="space-y-4">
        <h2 class="text-lg font-semibold text-stone-900">Permanent failures</h2>
        <div class="card overflow-hidden">
          <div class="divide-y divide-stone-100">
            <div v-for="book in store.permanent_failed" :key="book.id" :data-testid="'dlq-row-' + book.id" class="p-4 flex items-center gap-4 hover:bg-stone-50 transition-colors">
              <div class="w-12 h-16 shrink-0 rounded overflow-hidden bg-stone-100 shadow-sm">
                <img v-if="book.cover_url" :src="book.cover_url" :alt="book.title" class="w-full h-full object-cover" loading="lazy" />
                <div v-else class="w-full h-full flex items-center justify-center bg-stone-200">
                  <svg class="w-6 h-6 text-stone-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M12 6.253v13m0-13C10.832 5.477 9.246 5 7.5 5S4.168 5.477 3 6.253v13C4.168 18.477 5.754 18 7.5 18s3.332.477 4.5 1.253m0-13C13.168 5.477 14.754 5 16.5 5c1.747 0 3.332.477 4.5 1.253v13C19.832 18.477 18.247 18 16.5 18c-1.746 0-3.332.477-4.5 1.253"/>
                  </svg>
                </div>
              </div>
              <div class="flex-1 min-w-0">
                <div class="flex items-center gap-2 mb-1">
                  <h3 class="font-medium text-stone-900 truncate">{{ book.title }}</h3>
                  <StatusBadge :status="book.status" />
                </div>
                <p class="text-sm text-stone-500 truncate mb-1">{{ book.author?.name || 'Unknown Author' }}</p>
                <div class="flex items-center gap-3 text-xs">
                  <span class="text-error-600 font-medium">{{ humanizeReason(book.failure_reason) }}</span>
                  <span class="text-stone-400">Retries: {{ book.retry_count || 0 }}</span>
                </div>
              </div>
               <div class="shrink-0">
                 <button
                   :data-testid="retryingIds.has(book.id) ? 'retry-button-loading' : 'retry-button-' + book.id"
                   @click="handleRetry(book.id)"
                   :disabled="retryingIds.has(book.id)"
                   class="btn btn-secondary disabled:opacity-50 disabled:cursor-not-allowed"
                 >
                   <svg v-if="retryingIds.has(book.id)" class="w-4 h-4 animate-spin" fill="none" viewBox="0 0 24 24">
                     <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="3"></circle>
                     <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
                   </svg>
                   {{ retryingIds.has(book.id) ? 'Retrying...' : 'Retry' }}
                 </button>
               </div>
             </div>
           </div>
         </div>
       </div>

       <div v-if="store.recent_failures.length > 0" class="space-y-4">
        <h2 class="text-lg font-semibold text-stone-900">Recent failures</h2>
        <div class="card overflow-hidden">
          <div class="divide-y divide-stone-100">
            <div v-for="book in store.recent_failures" :key="book.id" :data-testid="'dlq-row-' + book.id" class="p-4 flex items-center gap-4 hover:bg-stone-50 transition-colors">
              <div class="w-12 h-16 shrink-0 rounded overflow-hidden bg-stone-100 shadow-sm">
                <img v-if="book.cover_url" :src="book.cover_url" :alt="book.title" class="w-full h-full object-cover" loading="lazy" />
                <div v-else class="w-full h-full flex items-center justify-center bg-stone-200">
                  <svg class="w-6 h-6 text-stone-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M12 6.253v13m0-13C10.832 5.477 9.246 5 7.5 5S4.168 5.477 3 6.253v13C4.168 18.477 5.754 18 7.5 18s3.332.477 4.5 1.253m0-13C13.168 5.477 14.754 5 16.5 5c1.747 0 3.332.477 4.5 1.253v13C19.832 18.477 18.247 18 16.5 18c-1.746 0-3.332.477-4.5 1.253"/>
                  </svg>
                </div>
              </div>
              <div class="flex-1 min-w-0">
                <div class="flex items-center gap-2 mb-1">
                  <h3 class="font-medium text-stone-900 truncate">{{ book.title }}</h3>
                  <StatusBadge :status="book.status" />
                </div>
                <p class="text-sm text-stone-500 truncate mb-1">{{ book.author?.name || 'Unknown Author' }}</p>
                <div class="flex items-center gap-3 text-xs">
                  <span class="text-error-600 font-medium">{{ humanizeReason(book.failure_reason) }}</span>
                  <span class="text-stone-400">Retries: {{ book.retry_count || 0 }}</span>
                </div>
              </div>
               <div class="shrink-0">
                 <button
                   :data-testid="retryingIds.has(book.id) ? 'retry-button-loading' : 'retry-button-' + book.id"
                   @click="handleRetry(book.id)"
                   :disabled="retryingIds.has(book.id)"
                   class="btn btn-secondary disabled:opacity-50 disabled:cursor-not-allowed"
                 >
                   <svg v-if="retryingIds.has(book.id)" class="w-4 h-4 animate-spin" fill="none" viewBox="0 0 24 24">
                     <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="3"></circle>
                     <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
                   </svg>
                   {{ retryingIds.has(book.id) ? 'Retrying...' : 'Retry' }}
                 </button>
               </div>
             </div>
           </div>
         </div>
       </div>
     </div>
   </div>
 </template>
