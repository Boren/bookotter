<script setup lang="ts">
import { ref, computed } from 'vue'
import { useRoute } from 'vue-router'
import { useSearchStore } from '../stores/search'
import type { SearchResult } from '../types'

const route = useRoute()
const searchStore = useSearchStore()

const titleQuery = ref('')
const authorQuery = ref('')

const bookId = computed(() => {
  const id = route.query.bookId
  return id ? Number(id) : null
})

const bookTitle = computed(() => {
  return (route.query.bookTitle as string) || null
})

const handleSearch = async () => {
  if (!titleQuery.value.trim()) return
  await searchStore.search(titleQuery.value, authorQuery.value)
}

const handleGrab = async (result: SearchResult) => {
  if (!bookId.value) return
  await searchStore.grabRelease(bookId.value, result)
}

const formatSize = (bytes: number) => {
  if (bytes >= 1_073_741_824) {
    return `${(bytes / 1_073_741_824).toFixed(1)} GB`
  }
  if (bytes >= 1_048_576) {
    return `${(bytes / 1_048_576).toFixed(1)} MB`
  }
  if (bytes >= 1024) {
    return `${(bytes / 1024).toFixed(0)} KB`
  }
  return `${bytes} B`
}

const isGrabbing = (guid: string) => {
  return !!searchStore.grabbingIds[guid]
}

const hasSearched = computed(() => searchStore.query.length > 0)
</script>

<template>
  <div class="space-y-8">
    <!-- Page Header -->
    <div class="page-header">
      <h1 class="page-title">Search</h1>
      <p class="page-subtitle">
        <template v-if="bookTitle">
          Find releases for <span class="text-kindle-600 font-medium">{{ bookTitle }}</span>
        </template>
        <template v-else>
          Search Prowlarr indexers for books
        </template>
      </p>
    </div>

    <!-- Search Form Card -->
    <div class="card card-accent">
      <div class="flex items-center gap-4 mb-6">
        <div class="icon-container-primary">
          <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z"/>
          </svg>
        </div>
        <div>
          <h2 class="text-xl font-display font-semibold text-stone-900">Search Prowlarr</h2>
          <p class="text-sm text-stone-500">Find books across your configured indexers</p>
        </div>
      </div>

      <form @submit.prevent="handleSearch" class="space-y-4">
        <div class="grid gap-4 md:grid-cols-2">
          <div>
            <label class="label">Title</label>
            <input
              v-model="titleQuery"
              type="text"
              class="input"
              placeholder="Book title..."
              :disabled="searchStore.isSearching"
            />
          </div>
          <div>
            <label class="label">Author <span class="text-stone-400 font-normal">(optional)</span></label>
            <input
              v-model="authorQuery"
              type="text"
              class="input"
              placeholder="Author name..."
              :disabled="searchStore.isSearching"
            />
          </div>
        </div>

        <div class="flex items-center gap-3">
          <button
            type="submit"
            class="btn btn-primary"
            :disabled="!titleQuery.trim() || searchStore.isSearching"
          >
            <svg v-if="searchStore.isSearching" class="w-4 h-4 animate-spin" fill="none" viewBox="0 0 24 24">
              <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="3"></circle>
              <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
            </svg>
            <svg v-else class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z"/>
            </svg>
            {{ searchStore.isSearching ? 'Searching...' : 'Search' }}
          </button>
          <button
            v-if="searchStore.hasResults || searchStore.error"
            type="button"
            @click="searchStore.clearSearch(); titleQuery = ''; authorQuery = ''"
            class="btn btn-secondary"
          >
            Clear
          </button>
        </div>
      </form>
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
      <div v-if="searchStore.error" class="bg-error-50 border border-error-100 rounded-xl p-4 flex items-start gap-3">
        <div class="shrink-0 mt-0.5">
          <svg class="w-5 h-5 text-error-500" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 8v4m0 4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z"/>
          </svg>
        </div>
        <div class="flex-1 min-w-0">
          <p class="text-sm font-medium text-error-700">Search failed</p>
          <p class="text-sm text-error-600 mt-0.5">{{ searchStore.error }}</p>
        </div>
        <button
          @click="searchStore.clearError()"
          class="shrink-0 p-1 rounded-lg text-error-500 hover:text-error-700 hover:bg-error-100 transition-colors"
        >
          <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"/>
          </svg>
        </button>
      </div>
    </Transition>

    <!-- Grab Message -->
    <Transition
      enter-active-class="transition-all duration-300 ease-out"
      enter-from-class="opacity-0 -translate-y-2"
      enter-to-class="opacity-100 translate-y-0"
      leave-active-class="transition-all duration-200 ease-in"
      leave-from-class="opacity-100 translate-y-0"
      leave-to-class="opacity-0 -translate-y-2"
    >
      <div
        v-if="searchStore.grabMessage"
        class="rounded-xl p-4 flex items-start gap-3"
        :class="searchStore.grabMessage.type === 'success'
          ? 'bg-success-50 border border-success-100'
          : 'bg-error-50 border border-error-100'"
      >
        <div class="shrink-0 mt-0.5">
          <svg
            v-if="searchStore.grabMessage.type === 'success'"
            class="w-5 h-5 text-success-500"
            fill="none" stroke="currentColor" viewBox="0 0 24 24"
          >
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z"/>
          </svg>
          <svg
            v-else
            class="w-5 h-5 text-error-500"
            fill="none" stroke="currentColor" viewBox="0 0 24 24"
          >
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 8v4m0 4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z"/>
          </svg>
        </div>
        <div class="flex-1 min-w-0">
          <p
            class="text-sm font-medium"
            :class="searchStore.grabMessage.type === 'success' ? 'text-success-700' : 'text-error-700'"
          >
            {{ searchStore.grabMessage.type === 'success' ? 'Grabbed successfully' : 'Grab failed' }}
          </p>
          <p
            class="text-sm mt-0.5"
            :class="searchStore.grabMessage.type === 'success' ? 'text-success-600' : 'text-error-600'"
          >
            {{ searchStore.grabMessage.text }}
          </p>
        </div>
        <button
          @click="searchStore.clearGrabMessage()"
          class="shrink-0 p-1 rounded-lg transition-colors"
          :class="searchStore.grabMessage.type === 'success'
            ? 'text-success-500 hover:text-success-700 hover:bg-success-100'
            : 'text-error-500 hover:text-error-700 hover:bg-error-100'"
        >
          <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"/>
          </svg>
        </button>
      </div>
    </Transition>

    <!-- Loading State -->
    <div v-if="searchStore.isSearching" class="flex justify-center py-16">
      <div class="flex items-center gap-3 text-stone-500">
        <svg class="animate-spin h-6 w-6 text-kindle-600" fill="none" viewBox="0 0 24 24">
          <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="3"></circle>
          <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
        </svg>
        <span class="text-sm font-medium">Searching indexers...</span>
      </div>
    </div>

    <!-- Results Table -->
    <div v-else-if="searchStore.hasResults" class="card animate-fade-in-up">
      <div class="flex items-center justify-between mb-4">
        <div class="flex items-center gap-3">
          <div class="icon-container">
            <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z"/>
            </svg>
          </div>
          <h2 class="text-lg font-display font-semibold text-stone-900">Results</h2>
        </div>
        <span class="badge badge-neutral">{{ searchStore.resultCount }} found</span>
      </div>

      <div class="overflow-x-auto -mx-6">
        <table class="w-full min-w-[640px]">
          <thead>
            <tr>
              <th class="table-header text-left">Title</th>
              <th class="table-header text-right whitespace-nowrap">Size</th>
              <th class="table-header text-right whitespace-nowrap">Seeders</th>
              <th class="table-header text-left">Indexer</th>
              <th v-if="bookId" class="table-header text-right">Action</th>
            </tr>
          </thead>
          <tbody>
            <tr
              v-for="(result, index) in searchStore.results"
              :key="result.guid"
              class="table-row animate-fade-in"
              :style="{ animationDelay: `${index * 30}ms` }"
            >
              <td class="table-cell max-w-md">
                <p class="font-medium text-stone-900 truncate" :title="result.title">
                  {{ result.title }}
                </p>
                <p class="text-xs text-stone-500 mt-0.5">{{ result.publish_date ? new Date(result.publish_date).toLocaleDateString() : '' }}</p>
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
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 10l7-7m0 0l7 7m-7-7v18"/>
                  </svg>
                  {{ result.seeders }}
                </span>
              </td>
              <td class="table-cell">
                <span class="badge badge-neutral">{{ result.indexer }}</span>
              </td>
              <td v-if="bookId" class="table-cell text-right">
                <button
                  @click="handleGrab(result)"
                  :disabled="isGrabbing(result.guid)"
                  class="btn btn-sm btn-primary"
                >
                  <svg v-if="isGrabbing(result.guid)" class="w-3.5 h-3.5 animate-spin" fill="none" viewBox="0 0 24 24">
                    <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="3"></circle>
                    <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
                  </svg>
                  <svg v-else class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-4l-4 4m0 0l-4-4m4 4V4"/>
                  </svg>
                  {{ isGrabbing(result.guid) ? 'Grabbing...' : 'Grab' }}
                </button>
              </td>
            </tr>
          </tbody>
        </table>
      </div>

      <!-- No book context info -->
      <div v-if="!bookId" class="mt-4 pt-4 border-t border-stone-100">
        <p class="text-sm text-stone-500 flex items-center gap-2">
          <svg class="w-4 h-4 text-stone-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13 16h-1v-4h-1m1-4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z"/>
          </svg>
          Navigate from a book to grab releases. Search results are for preview only.
        </p>
      </div>
    </div>

    <!-- No Results State -->
    <div v-else-if="hasSearched && !searchStore.error" class="card">
      <div class="empty-state">
        <div class="empty-state-icon">
          <svg fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M9.172 16.172a4 4 0 015.656 0M9 10h.01M15 10h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z"/>
          </svg>
        </div>
        <p class="empty-state-title">No results found</p>
        <p class="empty-state-description">
          Try different search terms or check your Prowlarr configuration
        </p>
      </div>
    </div>

    <!-- Initial Empty State -->
    <div v-else-if="!searchStore.isSearching" class="card">
      <div class="empty-state">
        <div class="empty-state-icon">
          <svg fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z"/>
          </svg>
        </div>
        <p class="empty-state-title">Search for books</p>
        <p class="empty-state-description">
          Enter a title to search across your Prowlarr indexers
        </p>
      </div>
    </div>
  </div>
</template>
