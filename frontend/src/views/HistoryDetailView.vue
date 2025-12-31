<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import type { SyncRun, BookResult } from '../types'

const route = useRoute()
const router = useRouter()
const run = ref<SyncRun | null>(null)
const books = ref<BookResult[]>([])
const loading = ref(true)
const statusFilter = ref<string>('')
const expandedErrors = ref<Set<number>>(new Set())

const toggleError = (bookId: number) => {
  if (expandedErrors.value.has(bookId)) {
    expandedErrors.value.delete(bookId)
  } else {
    expandedErrors.value.add(bookId)
  }
}

const getShortError = (errorMessage: string | null): string => {
  if (!errorMessage) return ''
  if (errorMessage.startsWith('Local file not found')) return 'File not found'
  if (errorMessage.includes('size mismatch')) return 'Transfer incomplete'
  if (errorMessage.includes('Transfer failed')) return 'Transfer failed'
  // Truncate long messages
  return errorMessage.length > 30 ? errorMessage.substring(0, 30) + '...' : errorMessage
}

const fetchRun = async () => {
  const id = route.params.id
  try {
    const response = await fetch(`/api/sync/runs/${id}`)
    if (!response.ok) {
      router.push('/history')
      return
    }
    run.value = await response.json()
  } catch (e) {
    console.error('Failed to fetch run:', e)
  }
}

const fetchBooks = async () => {
  const id = route.params.id
  let url = `/api/sync/runs/${id}/books?limit=200`
  if (statusFilter.value) {
    url += `&status=${statusFilter.value}`
  }

  try {
    const response = await fetch(url)
    const data = await response.json()
    books.value = data.books
  } catch (e) {
    console.error('Failed to fetch books:', e)
  }
}

const formatDate = (dateStr: string) => {
  return new Date(dateStr).toLocaleString()
}

const formatSize = (bytes: number | null) => {
  if (!bytes) return '-'
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}

const getStatusClass = (status: string) => {
  switch (status) {
    case 'transferred': return 'bg-success-50 text-success-700'
    case 'skipped': return 'bg-stone-100 text-stone-700'
    case 'not_found': return 'bg-warning-50 text-warning-700'
    case 'failed': return 'bg-error-50 text-error-700'
    case 'matched_no_files': return 'bg-info-50 text-info-700'
    default: return 'bg-stone-100 text-stone-700'
  }
}

onMounted(async () => {
  await fetchRun()
  await fetchBooks()
  loading.value = false
})
</script>

<template>
  <div class="space-y-6">
    <!-- Back Button -->
    <button @click="router.push('/history')" class="flex items-center text-stone-600 hover:text-stone-900">
      <svg class="h-5 w-5 mr-1" fill="none" stroke="currentColor" viewBox="0 0 24 24">
        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M15 19l-7-7 7-7" />
      </svg>
      Back to History
    </button>

    <!-- Loading -->
    <div v-if="loading" class="flex justify-center py-12">
      <svg class="animate-spin h-8 w-8 text-kindle-600" fill="none" viewBox="0 0 24 24">
        <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
        <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"></path>
      </svg>
    </div>

    <template v-else-if="run">
      <!-- Run Summary -->
      <div class="card">
        <div class="flex items-center justify-between mb-4">
          <h1 class="text-2xl font-bold text-stone-900">
            Sync Run #{{ run.id }}
          </h1>
          <span
            class="px-3 py-1 text-sm font-medium rounded-full"
            :class="getStatusClass(run.status)"
          >
            {{ run.status }}
          </span>
        </div>

        <div class="grid grid-cols-2 md:grid-cols-4 gap-6">
          <div>
            <p class="text-sm text-stone-600">Started</p>
            <p class="font-medium text-stone-800">{{ formatDate(run.started_at) }}</p>
          </div>
          <div>
            <p class="text-sm text-stone-600">Completed</p>
            <p class="font-medium text-stone-800">{{ run.completed_at ? formatDate(run.completed_at) : 'Running...' }}</p>
          </div>
          <div>
            <p class="text-sm text-stone-600">Trigger</p>
            <p class="font-medium text-stone-800 capitalize">{{ run.trigger_type }}</p>
          </div>
          <div>
            <p class="text-sm text-stone-600">Mode</p>
            <p class="font-medium text-stone-800">{{ run.dry_run ? 'Dry Run' : 'Normal' }}</p>
          </div>
        </div>

        <!-- Stats -->
        <div class="mt-6 grid grid-cols-3 md:grid-cols-6 gap-4 pt-6 border-t border-stone-200">
          <div class="text-center">
            <p class="text-2xl font-bold text-stone-900">{{ run.total_books }}</p>
            <p class="text-xs text-stone-600">Total</p>
          </div>
          <div class="text-center">
            <p class="text-2xl font-bold text-success-600">{{ run.transferred }}</p>
            <p class="text-xs text-stone-600">Transferred</p>
          </div>
          <div class="text-center">
            <p class="text-2xl font-bold text-info-600">{{ run.matched }}</p>
            <p class="text-xs text-stone-600">Matched</p>
          </div>
          <div class="text-center">
            <p class="text-2xl font-bold text-stone-600">{{ run.skipped }}</p>
            <p class="text-xs text-stone-600">Skipped</p>
          </div>
          <div class="text-center">
            <p class="text-2xl font-bold text-warning-600">{{ run.not_found }}</p>
            <p class="text-xs text-stone-600">Not Found</p>
          </div>
          <div class="text-center">
            <p class="text-2xl font-bold text-error-600">{{ run.failed }}</p>
            <p class="text-xs text-stone-600">Failed</p>
          </div>
          <div v-if="run.cleaned_up > 0" class="text-center">
            <p class="text-2xl font-bold text-purple-600">{{ run.cleaned_up }}</p>
            <p class="text-xs text-stone-600">Cleaned Up</p>
          </div>
        </div>

        <div v-if="run.error_message" class="mt-4 p-3 bg-error-50 border border-error-200 rounded-lg">
          <p class="text-sm text-error-600">{{ run.error_message }}</p>
        </div>
      </div>

      <!-- Books List -->
      <div class="card">
        <div class="flex items-center justify-between mb-4">
          <h2 class="text-lg font-semibold text-stone-900">Books</h2>
          <select v-model="statusFilter" @change="fetchBooks" class="input w-48">
            <option value="">All statuses</option>
            <option value="transferred">Transferred</option>
            <option value="skipped">Skipped</option>
            <option value="not_found">Not Found</option>
            <option value="failed">Failed</option>
            <option value="matched_no_files">Matched (No Files)</option>
          </select>
        </div>

        <div class="overflow-x-auto">
          <table class="min-w-full divide-y divide-stone-200">
            <thead>
              <tr>
                <th class="px-4 py-3 text-left text-xs font-medium text-stone-600 uppercase tracking-wider">Book</th>
                <th class="px-4 py-3 text-left text-xs font-medium text-stone-600 uppercase tracking-wider">Status</th>
                <th class="px-4 py-3 text-left text-xs font-medium text-stone-600 uppercase tracking-wider hidden md:table-cell">Size</th>
              </tr>
            </thead>
            <tbody class="divide-y divide-stone-100">
              <tr v-for="book in books" :key="book.id">
                <td class="px-4 py-3">
                  <div class="flex items-center gap-3">
                    <!-- Book Cover -->
                    <img
                      v-if="book.cover_url"
                      :src="book.cover_url"
                      :alt="book.title"
                      class="w-10 h-14 object-cover rounded-sm shadow-xs shrink-0"
                    />
                    <div v-else class="w-10 h-14 rounded-sm bg-stone-100 flex items-center justify-center shrink-0">
                      <svg class="w-5 h-5 text-stone-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M12 6.253v13m0-13C10.832 5.477 9.246 5 7.5 5S4.168 5.477 3 6.253v13C4.168 18.477 5.754 18 7.5 18s3.332.477 4.5 1.253m0-13C13.168 5.477 14.754 5 16.5 5c1.747 0 3.332.477 4.5 1.253v13C19.832 18.477 18.247 18 16.5 18c-1.746 0-3.332.477-4.5 1.253"/>
                      </svg>
                    </div>
                    <div class="min-w-0">
                      <p class="font-medium text-stone-900 line-clamp-1">{{ book.title }}</p>
                      <p class="text-sm text-stone-600 line-clamp-1">{{ book.author || 'Unknown author' }}</p>
                    </div>
                  </div>
                </td>
                <td class="px-4 py-3">
                  <div>
                    <span
                      class="px-2 py-1 text-xs font-medium rounded-full"
                      :class="getStatusClass(book.status)"
                    >
                      {{ book.status.replace('_', ' ') }}
                    </span>
                    <div v-if="book.error_message" class="mt-1">
                      <button
                        @click="toggleError(book.id)"
                        class="text-xs text-error-600 hover:text-error-700 flex items-center gap-1"
                      >
                        <span>{{ getShortError(book.error_message) }}</span>
                        <svg
                          class="w-3 h-3 transition-transform"
                          :class="expandedErrors.has(book.id) ? 'rotate-180' : ''"
                          fill="none"
                          stroke="currentColor"
                          viewBox="0 0 24 24"
                        >
                          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 9l-7 7-7-7" />
                        </svg>
                      </button>
                      <p
                        v-if="expandedErrors.has(book.id)"
                        class="mt-1 text-xs text-stone-500 bg-stone-50 p-2 rounded-sm break-all"
                      >
                        {{ book.error_message }}
                      </p>
                    </div>
                  </div>
                </td>
                <td class="px-4 py-3 hidden md:table-cell text-sm text-stone-600">
                  {{ formatSize(book.file_size) }}
                </td>
              </tr>
            </tbody>
          </table>
        </div>

        <div v-if="books.length === 0" class="text-center py-8 text-stone-600">
          No books match the selected filter
        </div>
      </div>
    </template>
  </div>
</template>
