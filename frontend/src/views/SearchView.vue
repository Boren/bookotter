<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { useRoute } from 'vue-router'
import { useSearchStore } from '../stores/search'
import type { SearchResult } from '../types'
import SearchResultRow from '../components/SearchResultRow.vue'

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

const bookAuthor = computed(() => {
  return (route.query.bookAuthor as string) || null
})

onMounted(() => {
  if (bookTitle.value) {
    titleQuery.value = bookTitle.value
    if (bookAuthor.value) {
      authorQuery.value = bookAuthor.value
    }
    handleSearch()
  }
})

const handleSearch = async () => {
  if (!titleQuery.value.trim()) return
  await searchStore.search(titleQuery.value, authorQuery.value)
}

const showGrabModal = ref(false)
const grabTitle = ref('')
const grabAuthor = ref('')
const pendingResult = ref<SearchResult | null>(null)
const grabLoading = ref(false)
const grabError = ref('')

const handleGrab = async (result: SearchResult) => {
  if (bookId.value) {
    // Already have a book context — grab directly
    await searchStore.grabRelease(bookId.value, result)
    return
  }
  // No book context — show modal to create/select book
  pendingResult.value = result
  grabTitle.value = bookTitle.value || titleQuery.value
  grabAuthor.value = authorQuery.value
  showGrabModal.value = true
}

const confirmGrab = async () => {
  if (!pendingResult.value || !grabTitle.value.trim()) {
    grabError.value = 'Title is required'
    return
  }
  grabLoading.value = true
  grabError.value = ''
  try {
    // Create a new WANTED book first, then grab
    const bookResp = await fetch('/api/library/books', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ title: grabTitle.value.trim(), author_name: grabAuthor.value.trim() || undefined }),
    })
    if (!bookResp.ok) throw new Error('Failed to create book')
    const book = await bookResp.json()
    await searchStore.grabRelease(book.id, pendingResult.value)
    showGrabModal.value = false
    pendingResult.value = null
  } catch (e) {
    grabError.value = e instanceof Error ? e.message : 'Failed to grab'
  } finally {
    grabLoading.value = false
  }
}

const isGrabbing = (guid: string) => {
  return !!searchStore.grabbingIds[guid]
}

const hasSearched = computed(() => searchStore.query.length > 0)

// Filtering and Sorting
const hideRejected = ref(false)
const hideAudiobooks = ref(false)

type SortColumn = 'age' | 'title' | 'indexer' | 'size' | 'peers' | 'rejections'
const sortBy = ref<SortColumn>('peers')
const sortDir = ref<'asc' | 'desc'>('desc')

const toggleSort = (col: SortColumn) => {
  if (sortBy.value === col) {
    sortDir.value = sortDir.value === 'asc' ? 'desc' : 'asc'
  } else {
    sortBy.value = col
    sortDir.value = col === 'title' || col === 'indexer' ? 'asc' : 'desc'
  }
}

const filteredAndSortedResults = computed(() => {
  let results = [...searchStore.results]

  if (hideRejected.value) {
    results = results.filter(r => r.approved)
  }

  if (hideAudiobooks.value) {
    results = results.filter(r => {
      if (!r.rejections) return true
      return !r.rejections.some(rej => rej.toLowerCase().includes('audiobook'))
    })
  }

  results.sort((a, b) => {
    let cmp = 0
    switch (sortBy.value) {
      case 'age':
        cmp = (a.age_days || 0) - (b.age_days || 0)
        break
      case 'title':
        cmp = a.title.localeCompare(b.title)
        break
      case 'indexer':
        cmp = a.indexer.localeCompare(b.indexer)
        break
      case 'size':
        cmp = a.size - b.size
        break
      case 'peers':
        cmp = (a.seeders || 0) - (b.seeders || 0)
        break
      case 'rejections':
        cmp = (a.rejections?.length || 0) - (b.rejections?.length || 0)
        break
    }
    return sortDir.value === 'asc' ? cmp : -cmp
  })

  return results
})
</script>

<template>
  <div class="space-y-8">
    <!-- Page Header -->
    <div class="page-header">
      <h1 class="page-title">Search</h1>
      <p class="page-subtitle">
        <template v-if="bookTitle">
          Find releases for <span class="text-ereader-600 font-medium">{{ bookTitle }}</span>
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
        <svg class="animate-spin h-6 w-6 text-ereader-600" fill="none" viewBox="0 0 24 24">
          <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="3"></circle>
          <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
        </svg>
        <span class="text-sm font-medium">Searching indexers...</span>
      </div>
    </div>

    <!-- Results Table -->
    <div v-else-if="searchStore.hasResults" class="card animate-fade-in-up">
      <div class="flex flex-col sm:flex-row sm:items-center justify-between gap-4 mb-6">
        <div class="flex items-center gap-3">
          <div class="icon-container">
            <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z"/>
            </svg>
          </div>
          <h2 class="text-lg font-display font-semibold text-stone-900">Results</h2>
          <span class="badge badge-neutral">{{ filteredAndSortedResults.length }} found</span>
        </div>
        
        <div class="flex items-center gap-4 text-sm">
          <label class="flex items-center gap-2 cursor-pointer">
            <input type="checkbox" v-model="hideRejected" class="rounded border-stone-300 text-ereader-600 focus:ring-ereader-500" />
            <span class="text-stone-700">Hide rejected</span>
          </label>
          <label class="flex items-center gap-2 cursor-pointer">
            <input type="checkbox" v-model="hideAudiobooks" class="rounded border-stone-300 text-ereader-600 focus:ring-ereader-500" />
            <span class="text-stone-700">Hide audiobooks</span>
          </label>
        </div>
      </div>

      <div class="overflow-x-auto -mx-6">
        <table class="w-full min-w-[800px]">
          <thead>
            <tr>
              <th class="table-header text-left cursor-pointer hover:bg-stone-100 transition-colors" @click="toggleSort('age')">
                <div class="flex items-center gap-1">
                  Age
                  <svg v-if="sortBy === 'age'" class="w-4 h-4" :class="sortDir === 'desc' ? 'rotate-180' : ''" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 15l7-7 7 7"/></svg>
                </div>
              </th>
              <th class="table-header text-left cursor-pointer hover:bg-stone-100 transition-colors" @click="toggleSort('title')">
                <div class="flex items-center gap-1">
                  Title
                  <svg v-if="sortBy === 'title'" class="w-4 h-4" :class="sortDir === 'desc' ? 'rotate-180' : ''" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 15l7-7 7 7"/></svg>
                </div>
              </th>
              <th class="table-header text-left cursor-pointer hover:bg-stone-100 transition-colors" @click="toggleSort('indexer')">
                <div class="flex items-center gap-1">
                  Indexer
                  <svg v-if="sortBy === 'indexer'" class="w-4 h-4" :class="sortDir === 'desc' ? 'rotate-180' : ''" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 15l7-7 7 7"/></svg>
                </div>
              </th>
              <th class="table-header text-right cursor-pointer hover:bg-stone-100 transition-colors" @click="toggleSort('size')">
                <div class="flex items-center justify-end gap-1">
                  Size
                  <svg v-if="sortBy === 'size'" class="w-4 h-4" :class="sortDir === 'desc' ? 'rotate-180' : ''" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 15l7-7 7 7"/></svg>
                </div>
              </th>
              <th class="table-header text-right cursor-pointer hover:bg-stone-100 transition-colors" @click="toggleSort('peers')">
                <div class="flex items-center justify-end gap-1">
                  Peers (S/L)
                  <svg v-if="sortBy === 'peers'" class="w-4 h-4" :class="sortDir === 'desc' ? 'rotate-180' : ''" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 15l7-7 7 7"/></svg>
                </div>
              </th>
              <th class="table-header text-center cursor-pointer hover:bg-stone-100 transition-colors" @click="toggleSort('rejections')">
                <div class="flex items-center justify-center gap-1">
                  Rejections
                  <svg v-if="sortBy === 'rejections'" class="w-4 h-4" :class="sortDir === 'desc' ? 'rotate-180' : ''" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 15l7-7 7 7"/></svg>
                </div>
              </th>
              <th class="table-header text-right">Action</th>
            </tr>
          </thead>
          <tbody>
            <SearchResultRow
              v-for="(result, index) in filteredAndSortedResults"
              :key="result.guid"
              :result="result"
              :is-grabbing="isGrabbing(result.guid)"
              @grab="handleGrab"
              class="animate-fade-in"
              :style="{ animationDelay: `${index * 30}ms` }"
            />
          </tbody>
        </table>
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

    <!-- Grab Modal -->
    <Teleport to="body">
      <div v-if="showGrabModal" class="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/50" @click.self="showGrabModal = false">
        <div class="bg-white rounded-2xl shadow-xl w-full max-w-md p-6">
          <h2 class="text-lg font-semibold text-stone-900 mb-4">Create Book & Grab</h2>
          <p class="text-sm text-stone-600 mb-4">
            This release will be added to a new book in your library.
          </p>
          <div class="space-y-4">
            <div>
              <label class="block text-sm font-medium text-stone-700 mb-1">Title <span class="text-error-500">*</span></label>
              <input v-model="grabTitle" type="text" placeholder="Book title" class="input w-full" @keyup.enter="confirmGrab" />
            </div>
            <div>
              <label class="block text-sm font-medium text-stone-700 mb-1">Author</label>
              <input v-model="grabAuthor" type="text" placeholder="Author name (optional)" class="input w-full" @keyup.enter="confirmGrab" />
            </div>
            <p v-if="grabError" class="text-sm text-error-600">{{ grabError }}</p>
          </div>
          <div class="flex justify-end gap-3 mt-6">
            <button @click="showGrabModal = false" class="btn btn-secondary">Cancel</button>
            <button @click="confirmGrab" :disabled="grabLoading" class="btn btn-primary">
              {{ grabLoading ? 'Grabbing...' : 'Grab Release' }}
            </button>
          </div>
        </div>
      </div>
    </Teleport>
  </div>
</template>