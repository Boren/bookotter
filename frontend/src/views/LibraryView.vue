<script setup lang="ts">
import { onMounted, onUnmounted, ref } from 'vue'
import { useLibraryStore } from '../stores/library'
import type { BookStatus } from '../types'
import KindleDeliveryBadge from '../components/KindleDeliveryBadge.vue'
import StatusBadge from '../components/StatusBadge.vue'

const store = useLibraryStore()

const showAddModal = ref(false)
const addTitle = ref('')
const addAuthor = ref('')
const addError = ref('')
const addLoading = ref(false)

const openAddModal = () => {
  addTitle.value = ''
  addAuthor.value = ''
  addError.value = ''
  showAddModal.value = true
}

const closeAddModal = () => {
  showAddModal.value = false
}

const handleAddBook = async () => {
  if (!addTitle.value.trim()) {
    addError.value = 'Title is required'
    return
  }
  addLoading.value = true
  addError.value = ''
  try {
    await store.createBook(addTitle.value.trim(), addAuthor.value.trim() || undefined)
    closeAddModal()
  } catch (e) {
    addError.value = e instanceof Error ? e.message : 'Failed to add book'
  } finally {
    addLoading.value = false
  }
}

const searchInput = ref('')
let searchTimeout: ReturnType<typeof setTimeout> | null = null

const statusOptions: { value: BookStatus; label: string }[] = [
  { value: 'missing', label: 'Missing' },
  { value: 'wanted', label: 'Wanted' },
  { value: 'searching', label: 'Searching' },
  { value: 'grabbed', label: 'Grabbed' },
  { value: 'downloading', label: 'Downloading' },
  { value: 'importing', label: 'Importing' },
  { value: 'in_library', label: 'In Library' },
  { value: 'failed', label: 'Failed' },
]

const kindleStatusOptions = [
  { value: 'DELIVERED', label: 'On Kindle' },
  { value: 'PENDING', label: 'Queued for Kindle' },
  { value: 'IN_PROGRESS', label: 'Sending to Kindle' },
  { value: 'SKIPPED', label: 'Delivery skipped' },
  { value: 'NONE', label: 'Not sent to Kindle' },
]

const sortOptions = [
  { value: 'title', label: 'Title' },
  { value: 'created_at', label: 'Date Added' },
  { value: 'updated_at', label: 'Last Updated' },
]

const handleSearch = () => {
  if (searchTimeout) clearTimeout(searchTimeout)
  searchTimeout = setTimeout(() => {
    store.searchQuery = searchInput.value
    store.offset = 0
    store.fetchBooks()
  }, 300)
}

const handleStatusFilter = () => {
  store.offset = 0
  store.fetchBooks()
}

const handleAuthorFilter = () => {
  store.offset = 0
  store.fetchBooks()
}

const handleSort = (field: string) => {
  if (store.sortBy === field) {
    store.sortOrder = store.sortOrder === 'asc' ? 'desc' : 'asc'
  } else {
    store.sortBy = field
    store.sortOrder = field === 'title' ? 'asc' : 'desc'
  }
  store.offset = 0
  store.fetchBooks()
}

const handlePageChange = (newPage: number) => {
  store.offset = (newPage - 1) * store.limit
  store.fetchBooks()
  window.scrollTo({ top: 0, behavior: 'smooth' })
}

const clearFilters = () => {
  searchInput.value = ''
  store.searchQuery = ''
  store.filterStatus = null
  store.filterKindleStatus = null
  store.filterAuthor = null
  store.offset = 0
  store.fetchBooks()
}

const hasActiveFilters = () => {
  return !!(store.searchQuery || store.filterStatus || store.filterKindleStatus || store.filterAuthor)
}

const formatFileSize = (bytes: number | null) => {
  if (!bytes) return null
  if (bytes >= 1_000_000) return `${(bytes / 1_000_000).toFixed(1)} MB`
  return `${Math.round(bytes / 1_000)} KB`
}

onMounted(() => {
  store.fetchBooks()
})

onUnmounted(() => {
  if (searchTimeout) clearTimeout(searchTimeout)
})
</script>

<template>
  <div class="space-y-6">
    <!-- Page Header -->
    <div class="page-header">
      <div class="flex flex-col sm:flex-row sm:items-end sm:justify-between gap-2">
        <div>
          <h1 class="page-title">Library</h1>
          <p class="page-subtitle">Browse and manage your book collection</p>
        </div>
        <p v-if="!store.isLoading && store.total > 0" class="text-sm text-stone-500 tabular-nums">
          {{ store.total }} {{ store.total === 1 ? 'book' : 'books' }}
        </p>
        <button @click="openAddModal" class="btn btn-primary">
          <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 4v16m8-8H4"/>
          </svg>
          Add Book
        </button>
      </div>
    </div>

    <!-- Filters Toolbar -->
    <div class="card">
      <div class="flex flex-col sm:flex-row gap-3">
        <!-- Search -->
        <div class="flex-1 relative">
          <svg class="absolute left-3.5 top-1/2 -translate-y-1/2 w-4 h-4 text-stone-400 pointer-events-none" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z"/>
          </svg>
          <input
            v-model="searchInput"
            @input="handleSearch"
            type="text"
            placeholder="Search titles and authors..."
            class="input pl-10"
          />
        </div>

        <!-- Status Filter -->
        <select v-model="store.filterStatus" @change="handleStatusFilter" class="input sm:w-44">
          <option :value="null">All Statuses</option>
          <option v-for="s in statusOptions" :key="s.value" :value="s.value">{{ s.label }}</option>
        </select>

        <!-- Kindle Delivery Filter -->
        <select
          v-model="store.filterKindleStatus"
          @change="handleStatusFilter"
          class="input sm:w-48"
          data-testid="kindle-filter"
        >
          <option :value="null">Kindle: All</option>
          <option v-for="k in kindleStatusOptions" :key="k.value" :value="k.value">{{ k.label }}</option>
        </select>

        <!-- Author Filter -->
        <select
          v-if="store.knownAuthors.length > 0"
          v-model="store.filterAuthor"
          @change="handleAuthorFilter"
          class="input sm:w-48"
        >
          <option :value="null">All Authors</option>
          <option v-for="a in store.knownAuthors" :key="a" :value="a">{{ a }}</option>
        </select>
      </div>

      <!-- Sort Controls -->
      <div class="flex items-center justify-between mt-4 pt-4 border-t border-stone-100">
        <div class="flex items-center gap-2">
          <span class="text-xs font-medium uppercase tracking-wider text-stone-500 mr-1">Sort</span>
          <button
            v-for="option in sortOptions"
            :key="option.value"
            @click="handleSort(option.value)"
            class="inline-flex items-center gap-1 px-3 py-1.5 rounded-lg text-xs font-medium transition-all duration-200"
            :class="store.sortBy === option.value
              ? 'bg-kindle-100 text-kindle-800'
              : 'text-stone-600 hover:bg-stone-100 hover:text-stone-800'"
          >
            {{ option.label }}
            <svg
              v-if="store.sortBy === option.value"
              class="w-3.5 h-3.5 transition-transform duration-200"
              :class="store.sortOrder === 'asc' ? '' : 'rotate-180'"
              fill="none"
              stroke="currentColor"
              viewBox="0 0 24 24"
            >
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 15l7-7 7 7"/>
            </svg>
          </button>
        </div>

        <button
          v-if="hasActiveFilters()"
          @click="clearFilters"
          class="text-xs text-stone-500 hover:text-stone-700 transition-colors"
        >
          Clear filters
        </button>
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
      <div v-if="store.error" class="bg-error-50 border border-error-200 rounded-xl p-4 flex items-start gap-3">
        <svg class="w-5 h-5 text-error-500 shrink-0 mt-0.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 8v4m0 4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z"/>
        </svg>
        <div class="flex-1 min-w-0">
          <p class="text-sm font-medium text-error-800">Failed to load books</p>
          <p class="text-sm text-error-600 mt-0.5">{{ store.error }}</p>
        </div>
        <button
          @click="store.clearError()"
          class="shrink-0 p-1 rounded-lg text-error-400 hover:text-error-600 hover:bg-error-100 transition-colors"
        >
          <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"/>
          </svg>
        </button>
      </div>
    </Transition>

    <!-- Loading State -->
    <div v-if="store.isLoading" class="flex justify-center py-16">
      <div class="flex items-center gap-3 text-stone-500">
        <svg class="animate-spin h-6 w-6 text-kindle-600" fill="none" viewBox="0 0 24 24">
          <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="3"></circle>
          <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
        </svg>
        <span class="text-sm font-medium">Loading library...</span>
      </div>
    </div>

    <!-- Book Grid -->
    <div
      v-else-if="store.books.length > 0"
      class="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 xl:grid-cols-5 gap-5"
    >
      <router-link
        v-for="(book, index) in store.books"
        :key="book.id"
        :to="{ name: 'book-detail', params: { id: book.id } }"
        class="group animate-fade-in-up block relative"
        :style="{ animationDelay: `${Math.min(index, 15) * 30}ms` }"
      >
        <!-- Failure Badge -->
        <div
          v-if="book.status === 'failed' || book.status === 'PERMANENT_FAILED'"
          data-testid="failure-badge"
          :title="book.failure_reason || 'Unknown error'"
          class="absolute -top-2 -right-2 bg-error-500 text-white rounded-full w-6 h-6 flex items-center justify-center text-xs font-bold z-10 shadow-sm"
        >
          !
        </div>

        <!-- Kindle Delivery Indicator -->
        <div class="absolute -top-2 -left-2 z-10">
          <KindleDeliveryBadge :status="book.kindle_delivery_status" compact />
        </div>

        <!-- Cover -->
        <div class="relative aspect-[2/3] rounded-xl overflow-hidden bg-stone-100 shadow-warm transition-all duration-300 group-hover:shadow-warm-lg group-hover:-translate-y-1">
          <img
            v-if="book.cover_url"
            :src="book.cover_url"
            :alt="book.title"
            class="w-full h-full object-cover"
            loading="lazy"
          />
          <div v-else class="w-full h-full flex flex-col items-center justify-center bg-stone-200/50 p-4">
            <svg class="w-10 h-10 text-stone-300 mb-2" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M12 6.253v13m0-13C10.832 5.477 9.246 5 7.5 5S4.168 5.477 3 6.253v13C4.168 18.477 5.754 18 7.5 18s3.332.477 4.5 1.253m0-13C13.168 5.477 14.754 5 16.5 5c1.747 0 3.332.477 4.5 1.253v13C19.832 18.477 18.247 18 16.5 18c-1.746 0-3.332.477-4.5 1.253"/>
            </svg>
            <p class="text-xs text-stone-400 text-center line-clamp-2">{{ book.title }}</p>
          </div>

          <!-- Status Badge -->
          <div class="absolute top-2 right-2">
            <StatusBadge :status="book.status" />
          </div>

          <!-- File Size -->
          <span
            v-if="book.file_size"
            class="absolute bottom-2 left-2 px-1.5 py-0.5 rounded text-[10px] leading-tight font-medium bg-stone-900/60 text-white"
          >
            {{ formatFileSize(book.file_size) }}
          </span>
        </div>

        <!-- Book Info -->
        <div class="mt-2.5 px-0.5">
          <h3 class="font-medium text-sm text-stone-900 line-clamp-2 group-hover:text-kindle-700 transition-colors">
            {{ book.title }}
          </h3>
          <p class="text-xs text-stone-500 mt-0.5 truncate">
            {{ book.author?.name || 'Unknown Author' }}
          </p>
          <p v-if="book.series_name" class="text-xs text-kindle-600 mt-0.5 truncate">
            {{ book.series_name }}<span v-if="book.series_position"> #{{ book.series_position }}</span>
          </p>
        </div>
      </router-link>
    </div>

    <!-- Empty State -->
    <div v-else class="card">
      <div class="empty-state">
        <div class="empty-state-icon">
          <svg fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M12 6.253v13m0-13C10.832 5.477 9.246 5 7.5 5S4.168 5.477 3 6.253v13C4.168 18.477 5.754 18 7.5 18s3.332.477 4.5 1.253m0-13C13.168 5.477 14.754 5 16.5 5c1.747 0 3.332.477 4.5 1.253v13C19.832 18.477 18.247 18 16.5 18c-1.746 0-3.332.477-4.5 1.253"/>
          </svg>
        </div>
        <p class="empty-state-title">
          {{ hasActiveFilters() ? 'No books match your filters' : 'Your library is empty' }}
        </p>
        <p class="empty-state-description">
          {{ hasActiveFilters()
            ? 'Try adjusting your search or filters'
            : 'Books will appear here as they are added to your collection'
          }}
        </p>
        <button
          v-if="hasActiveFilters()"
          @click="clearFilters"
          class="btn btn-secondary"
        >
          Clear Filters
        </button>
      </div>
    </div>

    <!-- Pagination -->
    <div v-if="!store.isLoading && store.totalPages > 1" class="flex items-center justify-center gap-3 pt-4">
      <button
        @click="handlePageChange(store.currentPage - 1)"
        :disabled="store.currentPage === 1"
        class="btn btn-secondary"
      >
        <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M15 19l-7-7 7-7"/>
        </svg>
        Previous
      </button>
      <span class="px-4 py-2 text-sm font-medium text-stone-600 tabular-nums">
        Page {{ store.currentPage }} of {{ store.totalPages }}
      </span>
      <button
        @click="handlePageChange(store.currentPage + 1)"
        :disabled="store.currentPage === store.totalPages"
        class="btn btn-secondary"
      >
        Next
        <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 5l7 7-7 7"/>
        </svg>
      </button>
    </div>

    <!-- Add Book Modal -->
    <Teleport to="body">
      <div v-if="showAddModal" class="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/50" @click.self="closeAddModal">
        <div class="bg-white rounded-2xl shadow-xl w-full max-w-md p-6">
          <h2 class="text-lg font-semibold text-stone-900 mb-4">Add Book</h2>
          <div class="space-y-4">
            <div>
              <label class="block text-sm font-medium text-stone-700 mb-1">Title <span class="text-error-500">*</span></label>
              <input v-model="addTitle" type="text" placeholder="Book title" class="input w-full" @keyup.enter="handleAddBook" />
            </div>
            <div>
              <label class="block text-sm font-medium text-stone-700 mb-1">Author</label>
              <input v-model="addAuthor" type="text" placeholder="Author name (optional)" class="input w-full" @keyup.enter="handleAddBook" />
            </div>
            <p v-if="addError" class="text-sm text-error-600">{{ addError }}</p>
          </div>
          <div class="flex justify-end gap-3 mt-6">
            <button @click="closeAddModal" class="btn btn-secondary">Cancel</button>
            <button @click="handleAddBook" :disabled="addLoading" class="btn btn-primary">
              {{ addLoading ? 'Adding...' : 'Add Book' }}
            </button>
          </div>
        </div>
      </div>
    </Teleport>
  </div>
</template>
