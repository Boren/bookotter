<script setup lang="ts">
import { computed, onMounted, watch } from 'vue'
import { useSearchStore } from '../stores/search'
import type { SearchResult } from '../types'

const props = defineProps<{
  bookId: number
  bookTitle: string
  bookAuthor: string | null
}>()

const searchStore = useSearchStore()

const results = computed<SearchResult[]>(() => searchStore.previewResults[props.bookId] || [])
const isLoading = computed<boolean>(() => !!searchStore.previewLoading[props.bookId])
const errorMessage = computed<string | null>(() => searchStore.previewErrors[props.bookId] || null)
const hasLoaded = computed<boolean>(
  () => props.bookId in searchStore.previewResults && !isLoading.value,
)

const refresh = () => searchStore.previewForBook(props.bookId)

const handleGrab = (result: SearchResult) => searchStore.grabRelease(props.bookId, result)

const isGrabbing = (guid: string) => !!searchStore.grabbingIds[guid]

const formatSize = (bytes: number) => {
  if (bytes >= 1_073_741_824) return `${(bytes / 1_073_741_824).toFixed(1)} GB`
  if (bytes >= 1_048_576) return `${(bytes / 1_048_576).toFixed(1)} MB`
  if (bytes >= 1024) return `${(bytes / 1024).toFixed(0)} KB`
  return `${bytes} B`
}

const formatAge = (publishDate: string | null | undefined) => {
  if (!publishDate) return '—'
  const then = new Date(publishDate).getTime()
  if (Number.isNaN(then)) return '—'
  const diffDays = Math.floor((Date.now() - then) / (1000 * 60 * 60 * 24))
  if (diffDays < 1) return 'today'
  if (diffDays < 30) return `${diffDays}d ago`
  if (diffDays < 365) return `${Math.floor(diffDays / 30)}mo ago`
  return `${Math.floor(diffDays / 365)}y ago`
}

onMounted(() => {
  if (!hasLoaded.value && !isLoading.value) refresh()
})

watch(
  () => props.bookId,
  (_, prev) => {
    if (prev) searchStore.clearPreviewForBook(prev)
    refresh()
  },
)
</script>

<template>
  <section
    data-component="interactive-search-panel"
    class="card animate-fade-in-up"
  >
    <div class="flex items-center justify-between mb-4">
      <div class="flex items-center gap-3 min-w-0">
        <div class="icon-container shrink-0">
          <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
          </svg>
        </div>
        <div class="min-w-0">
          <h2 class="text-lg font-display font-semibold text-stone-900 truncate">
            Interactive Search
          </h2>
          <p class="text-sm text-stone-500 truncate">
            {{ bookTitle }}<span v-if="bookAuthor"> — {{ bookAuthor }}</span>
          </p>
        </div>
      </div>
      <button
        type="button"
        @click="refresh"
        :disabled="isLoading"
        class="btn btn-secondary btn-sm shrink-0"
      >
        <svg
          v-if="isLoading"
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
        Refresh
      </button>
    </div>

    <div v-if="isLoading && results.length === 0" class="space-y-3">
      <div v-for="i in 3" :key="i" class="skeleton h-12 w-full rounded-lg"></div>
    </div>

    <div
      v-else-if="errorMessage"
      class="bg-error-50 border border-error-100 rounded-xl p-4 flex items-start gap-3"
    >
      <svg class="w-5 h-5 text-error-500 shrink-0 mt-0.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 8v4m0 4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
      </svg>
      <div class="flex-1 min-w-0">
        <p class="text-sm font-medium text-error-700">Search failed</p>
        <p class="text-sm text-error-600 mt-0.5">{{ errorMessage }}</p>
      </div>
    </div>

    <div v-else-if="results.length === 0" class="empty-state">
      <div class="empty-state-icon">
        <svg fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M9.172 16.172a4 4 0 015.656 0M9 10h.01M15 10h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
        </svg>
      </div>
      <p class="empty-state-title">No results found</p>
      <p class="empty-state-description">
        Try refining the book metadata or use Quick Search for a different query.
      </p>
    </div>

    <div v-else class="overflow-x-auto -mx-6">
      <table class="w-full min-w-[640px]">
        <thead>
          <tr>
            <th class="table-header text-left whitespace-nowrap">Format</th>
            <th class="table-header text-left">Title</th>
            <th class="table-header text-left">Indexer</th>
            <th class="table-header text-right whitespace-nowrap">Age</th>
            <th class="table-header text-right whitespace-nowrap">Size</th>
            <th class="table-header text-right whitespace-nowrap">Seeders</th>
            <th class="table-header text-right">Action</th>
          </tr>
        </thead>
        <tbody>
          <tr
            v-for="(result, index) in results"
            :key="result.guid"
            :data-format-hint="result.format_hint || 'unknown'"
            class="table-row animate-fade-in"
            :style="{ animationDelay: `${Math.min(index, 10) * 30}ms` }"
          >
            <td class="table-cell whitespace-nowrap">
              <span
                class="badge"
                :class="result.format_hint === 'ebook' ? 'badge-success' : 'badge-neutral'"
                :title="result.format_reason || ''"
              >
                {{ result.format_hint === 'ebook' ? 'EPUB' : 'Uncertain' }}
              </span>
            </td>
            <td class="table-cell max-w-md">
              <p class="font-medium text-stone-900 truncate" :title="result.title">
                {{ result.title }}
              </p>
            </td>
            <td class="table-cell">
              <span class="badge badge-neutral">{{ result.indexer }}</span>
            </td>
            <td class="table-cell text-right text-stone-500 tabular-nums whitespace-nowrap">
              {{ formatAge(result.publish_date) }}
            </td>
            <td class="table-cell text-right text-stone-600 tabular-nums whitespace-nowrap">
              {{ formatSize(result.size) }}
            </td>
            <td class="table-cell text-right tabular-nums">
              <span
                class="inline-flex items-center gap-1"
                :class="result.seeders > 0 ? 'text-success-600' : 'text-stone-400'"
              >
                <svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 10l7-7m0 0l7 7m-7-7v18" />
                </svg>
                {{ result.seeders }}
              </span>
            </td>
            <td class="table-cell text-right">
              <button
                type="button"
                @click="handleGrab(result)"
                :disabled="isGrabbing(result.guid)"
                class="btn btn-sm btn-primary"
              >
                <svg
                  v-if="isGrabbing(result.guid)"
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
                  <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-4l-4 4m0 0l-4-4m4 4V4" />
                </svg>
                {{ isGrabbing(result.guid) ? 'Grabbing...' : 'Grab' }}
              </button>
            </td>
          </tr>
        </tbody>
      </table>
    </div>

    <div v-if="results.length > 0" class="mt-4 pt-4 border-t border-stone-100">
      <p class="text-sm text-stone-500">Showing {{ results.length }} result<span v-if="results.length !== 1">s</span>.</p>
    </div>
  </section>
</template>
