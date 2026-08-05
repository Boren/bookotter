<script setup lang="ts">
import { ref, onMounted, computed, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useLibraryStore } from '../stores/library'
import { useSearchStore } from '../stores/search'
import { useSyncStore } from '../stores/sync'
import KindleDeliveryBadge from '../components/KindleDeliveryBadge.vue'
import StatusBadge from '../components/StatusBadge.vue'
import { formatRelativeTime } from '../utils/format'

const route = useRoute()
const router = useRouter()
const libraryStore = useLibraryStore()
const searchStore = useSearchStore()
const syncStore = useSyncStore()

const isEditing = ref(false)
const isSaving = ref(false)
const isDeleting = ref(false)
const showDeleteConfirm = ref(false)
const saveSuccess = ref(false)
const isSearching = ref(false)
const isRetrying = ref(false)
const isRequeueingKindle = ref(false)
const isUnpinningKindle = ref(false)

const editForm = ref({
  title: '',
  author_name: '',
  series_name: '',
  series_position: null as number | null,
  description: '',
  tags: '',
  rating: null as number | null,
  publisher: '',
  language: '',
  read_date: '',
})

const hoverRating = ref(0)

const bookId = computed(() => Number(route.params.id))

const book = computed(() => libraryStore.currentBook)

const formatDate = (dateStr: string | null) => {
  if (!dateStr) return '—'
  return new Date(dateStr).toLocaleDateString(undefined, {
    year: 'numeric',
    month: 'long',
    day: 'numeric',
  })
}

const formatFileSize = (bytes: number | null) => {
  if (!bytes) return '—'
  if (bytes >= 1_000_000) return `${(bytes / 1_000_000).toFixed(1)} MB`
  return `${Math.round(bytes / 1_000)} KB`
}

const humanizeReason = (reason: string | null): string => {
  if (!reason) return ''
  const spaced = reason.replace(/_/g, ' ')
  return spaced.charAt(0).toUpperCase() + spaced.slice(1)
}

const enterEditMode = () => {
  if (!book.value) return
  editForm.value = {
    title: book.value.title,
    author_name: book.value.author?.name ?? '',
    series_name: book.value.series_name ?? '',
    series_position: book.value.series_position,
    description: book.value.description ?? '',
    tags: book.value.tags?.join(', ') ?? '',
    rating: book.value.rating,
    publisher: book.value.publisher ?? '',
    language: book.value.language ?? '',
    read_date: book.value.read_date ? book.value.read_date.split('T')[0] : '',
  }
  isEditing.value = true
  saveSuccess.value = false
}

const cancelEdit = () => {
  isEditing.value = false
}

const handleSave = async () => {
  isSaving.value = true
  try {
    const tags = editForm.value.tags
      .split(',')
      .map((t) => t.trim())
      .filter(Boolean)

    await libraryStore.updateBook(bookId.value, {
      title: editForm.value.title,
      author_name: editForm.value.author_name || null,
      series_name: editForm.value.series_name || null,
      series_position: editForm.value.series_position,
      description: editForm.value.description || null,
      tags,
      rating: editForm.value.rating,
      publisher: editForm.value.publisher || null,
      language: editForm.value.language || null,
      read_date: editForm.value.read_date ? new Date(editForm.value.read_date).toISOString() : null,
    })
    isEditing.value = false
    saveSuccess.value = true
    setTimeout(() => {
      saveSuccess.value = false
    }, 3000)
  } catch {
    // Error is set in the store
  } finally {
    isSaving.value = false
  }
}

const handleDelete = async () => {
  isDeleting.value = true
  try {
    await libraryStore.deleteBook(bookId.value)
    router.push('/library')
  } catch {
    // Error is set in the store
  } finally {
    isDeleting.value = false
    showDeleteConfirm.value = false
  }
}

const setRating = (value: number) => {
  editForm.value.rating = editForm.value.rating === value ? null : value
}

const triggerSearch = async () => {
  if (!book.value) return
  isSearching.value = true
  try {
    await searchStore.autoSearchForBook(book.value.id)
  } finally {
    isSearching.value = false
  }
}

const goToInteractiveSearch = () => {
  if (!book.value) return
  router.push({
    path: '/search',
    query: {
      bookId: book.value.id,
      bookTitle: book.value.title,
      bookAuthor: book.value.author?.name || ''
    }
  })
}

const handleRetry = async () => {
  if (!book.value) return
  isRetrying.value = true
  try {
    await libraryStore.retryBook(book.value.id)
  } finally {
    isRetrying.value = false
  }
}

const handleKindleRequeue = async () => {
  if (!book.value) return
  isRequeueingKindle.value = true
  try {
    await libraryStore.requeueKindle(book.value.id)
  } finally {
    isRequeueingKindle.value = false
  }
}

const handleKindleUnpin = async () => {
  if (!book.value) return
  isUnpinningKindle.value = true
  try {
    await libraryStore.unpinKindle(book.value.id)
  } finally {
    isUnpinningKindle.value = false
  }
}

const canSendToKindle = computed(
  () =>
    book.value?.status === 'in_library' &&
    !!book.value?.file_path &&
    book.value?.kindle_delivery_status !== 'PENDING' &&
    book.value?.kindle_delivery_status !== 'IN_PROGRESS'
)

const showKindleCard = computed(
  () =>
    !!book.value?.kindle_delivery_status ||
    (book.value?.status === 'in_library' && !!book.value?.file_path)
)

const kindleDeliveryProgress = computed(() => {
  const p = syncStore.kindleDeliveryProgress
  return p && p.book_id === book.value?.id ? p : null
})

watch(
  () => route.params.id,
  (newId) => {
    if (newId) libraryStore.fetchBook(Number(newId))
  },
)

onMounted(() => {
  libraryStore.fetchBook(bookId.value)
})
</script>

<template>
  <div class="space-y-8">
    <!-- Back Navigation -->
    <button
      @click="router.push('/library')"
      class="inline-flex items-center gap-1.5 text-sm font-medium text-stone-600 hover:text-stone-900 transition-colors group"
    >
      <svg
        class="w-4 h-4 transition-transform group-hover:-translate-x-0.5"
        fill="none"
        stroke="currentColor"
        viewBox="0 0 24 24"
      >
        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M15 19l-7-7 7-7" />
      </svg>
      Back to Library
    </button>

    <!-- Loading -->
    <div v-if="libraryStore.isLoading" class="space-y-6">
      <div class="card">
        <div class="flex gap-8">
          <div class="skeleton w-48 h-72 shrink-0 rounded-xl"></div>
          <div class="flex-1 space-y-4">
            <div class="skeleton h-8 w-3/4"></div>
            <div class="skeleton h-5 w-1/2"></div>
            <div class="skeleton h-5 w-1/3"></div>
            <div class="skeleton h-20 w-full mt-6"></div>
          </div>
        </div>
      </div>
    </div>

    <!-- Error -->
    <div v-else-if="libraryStore.error && !book" class="card">
      <div class="empty-state">
        <div class="empty-state-icon">
          <svg fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path
              stroke-linecap="round"
              stroke-linejoin="round"
              stroke-width="1.5"
              d="M12 8v4m0 4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z"
            />
          </svg>
        </div>
        <p class="empty-state-title">{{ libraryStore.error }}</p>
        <p class="empty-state-description">The book could not be loaded.</p>
        <button @click="router.push('/library')" class="btn btn-secondary">
          Return to Library
        </button>
      </div>
    </div>

    <!-- Book Detail -->
    <template v-else-if="book">
      <!-- Success Banner -->
      <Transition
        enter-active-class="transition-all duration-300 ease-out"
        enter-from-class="opacity-0 -translate-y-2"
        enter-to-class="opacity-100 translate-y-0"
        leave-active-class="transition-all duration-200 ease-in"
        leave-from-class="opacity-100 translate-y-0"
        leave-to-class="opacity-0 -translate-y-2"
      >
        <div
          v-if="saveSuccess"
          class="bg-success-50 border border-success-100 rounded-xl p-4 flex items-center gap-3"
        >
          <svg class="w-5 h-5 text-success-600 shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 13l4 4L19 7" />
          </svg>
          <p class="text-sm font-medium text-success-700">Book updated successfully</p>
        </div>
      </Transition>

      <!-- Error Banner -->
      <Transition
        enter-active-class="transition-all duration-300 ease-out"
        enter-from-class="opacity-0 -translate-y-2"
        enter-to-class="opacity-100 translate-y-0"
        leave-active-class="transition-all duration-200 ease-in"
        leave-from-class="opacity-100 translate-y-0"
        leave-to-class="opacity-0 -translate-y-2"
      >
        <div
          v-if="libraryStore.error && book"
          class="bg-error-50 border border-error-200 rounded-xl p-4 flex items-start gap-3"
        >
          <svg class="w-5 h-5 text-error-500 shrink-0 mt-0.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path
              stroke-linecap="round"
              stroke-linejoin="round"
              stroke-width="2"
              d="M12 8v4m0 4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z"
            />
          </svg>
          <div class="flex-1 min-w-0">
            <p class="text-sm font-medium text-error-800">Update failed</p>
            <p class="text-sm text-error-600 mt-0.5">{{ libraryStore.error }}</p>
          </div>
          <button
            @click="libraryStore.clearError()"
            class="shrink-0 p-1 rounded-lg text-error-400 hover:text-error-600 hover:bg-error-100 transition-colors"
          >
            <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12" />
            </svg>
          </button>
        </div>
      </Transition>

      <!-- Search Message Banner -->
      <Transition
        enter-active-class="transition-all duration-300 ease-out"
        enter-from-class="opacity-0 -translate-y-2"
        enter-to-class="opacity-100 translate-y-0"
        leave-active-class="transition-all duration-200 ease-in"
        leave-from-class="opacity-100 translate-y-0"
        leave-to-class="opacity-0 -translate-y-2"
      >
        <div
          v-if="searchStore.autoSearchMessage"
          class="rounded-xl p-4 flex items-start gap-3"
          :class="searchStore.autoSearchMessage.type === 'success'
            ? 'bg-success-50 border border-success-100'
            : 'bg-error-50 border border-error-100'"
        >
          <div class="shrink-0 mt-0.5">
            <svg
              v-if="searchStore.autoSearchMessage.type === 'success'"
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
              :class="searchStore.autoSearchMessage.type === 'success' ? 'text-success-700' : 'text-error-700'"
            >
              {{ searchStore.autoSearchMessage.type === 'success' ? 'Search successful' : 'Search failed' }}
            </p>
            <p
              class="text-sm mt-0.5"
              :class="searchStore.autoSearchMessage.type === 'success' ? 'text-success-600' : 'text-error-600'"
            >
              {{ searchStore.autoSearchMessage.text }}
            </p>
          </div>
          <button
            @click="searchStore.clearAutoSearchMessage()"
            class="shrink-0 p-1 rounded-lg transition-colors"
            :class="searchStore.autoSearchMessage.type === 'success'
              ? 'text-success-500 hover:text-success-700 hover:bg-success-100'
              : 'text-error-500 hover:text-error-700 hover:bg-error-100'"
          >
            <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"/>
            </svg>
          </button>
        </div>
      </Transition>

      <!-- Failure Card -->
      <div
        v-if="book.status === 'failed' || book.status === 'PERMANENT_FAILED'"
        data-testid="failure-card"
        class="bg-red-50 border border-red-200 rounded-lg p-4 mb-4"
      >
        <div class="flex justify-between items-start">
          <div>
            <h3 class="text-red-900 font-semibold">This book failed to process</h3>
            <p class="text-red-800 mt-1">
              Reason: <span data-testid="failure-reason" :title="book.failure_reason || undefined">{{ humanizeReason(book.failure_reason) }}</span>
            </p>
            <p class="text-red-700 text-sm mt-1">Attempt {{ book.retry_count }} of 3</p>
            
            <details v-if="book.failure_history?.length" class="mt-3">
              <summary class="text-sm text-red-700 cursor-pointer hover:text-red-900 font-medium">Show previous attempts</summary>
              <ul class="mt-2 space-y-1 text-sm text-red-600 pl-4 list-disc">
                <li v-for="(entry, index) in book.failure_history" :key="index" :data-testid="'failure-history-item-' + index">
                  {{ entry.timestamp }} - {{ humanizeReason(entry.reason) }} (attempt {{ entry.attempt }})
                </li>
              </ul>
            </details>
          </div>
           <button
             :data-testid="isRetrying ? 'retry-button-loading' : 'retry-button-' + book.id"
             @click="handleRetry"
             :disabled="isRetrying"
             class="btn btn-secondary bg-white text-red-700 border-red-200 hover:bg-red-50 disabled:opacity-50 disabled:cursor-not-allowed"
           >
             <svg v-if="isRetrying" class="w-4 h-4 animate-spin" fill="none" viewBox="0 0 24 24">
               <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="3"></circle>
               <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
             </svg>
             {{ isRetrying ? 'Retrying...' : 'Retry' }}
           </button>
        </div>
      </div>

      <!-- Main Content Card -->
      <div class="card card-accent animate-fade-in">
        <div class="flex flex-col md:flex-row gap-8">
          <!-- Cover Image -->
          <div class="shrink-0">
            <div class="relative w-48 mx-auto md:mx-0">
              <img
                v-if="book.cover_url"
                :src="book.cover_url"
                :alt="book.title"
                class="w-48 h-72 object-cover rounded-xl shadow-warm-md"
              />
              <div
                v-else
                class="w-48 h-72 rounded-xl bg-stone-100 border border-stone-200 flex items-center justify-center"
              >
                <svg class="w-16 h-16 text-stone-300" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path
                    stroke-linecap="round"
                    stroke-linejoin="round"
                    stroke-width="1.5"
                    d="M12 6.253v13m0-13C10.832 5.477 9.246 5 7.5 5S4.168 5.477 3 6.253v13C4.168 18.477 5.754 18 7.5 18s3.332.477 4.5 1.253m0-13C13.168 5.477 14.754 5 16.5 5c1.747 0 3.332.477 4.5 1.253v13C19.832 18.477 18.247 18 16.5 18c-1.746 0-3.332.477-4.5 1.253"
                  />
                </svg>
              </div>

              <!-- Status Badge -->
              <div class="absolute -top-2 -right-2 shadow-warm-sm rounded-full bg-white">
                <StatusBadge :status="book.status" />
              </div>

              <!-- Kindle Delivery Badge -->
              <div
                v-if="book.kindle_delivery_status"
                class="absolute -bottom-2 -right-2 shadow-warm-sm rounded-full bg-white"
              >
                <KindleDeliveryBadge :status="book.kindle_delivery_status" />
              </div>
            </div>
          </div>

          <!-- Book Info / Edit Form -->
          <div class="flex-1 min-w-0">
            <!-- VIEW MODE -->
            <template v-if="!isEditing">
              <h1 class="text-2xl font-display font-bold text-stone-900 mb-1">{{ book.title }}</h1>
              <p class="text-lg text-stone-600 mb-4">{{ book.author?.name ?? 'Unknown author' }}</p>

              <!-- Series -->
              <div
                v-if="book.series_name"
                class="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-kindle-50 border border-kindle-200 text-sm text-kindle-800 mb-4"
              >
                <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path
                    stroke-linecap="round"
                    stroke-linejoin="round"
                    stroke-width="2"
                    d="M19 11H5m14 0a2 2 0 012 2v6a2 2 0 01-2 2H5a2 2 0 01-2-2v-6a2 2 0 012-2m14 0V9a2 2 0 00-2-2M5 11V9a2 2 0 012-2m0 0V5a2 2 0 012-2h6a2 2 0 012 2v2M7 7h10"
                  />
                </svg>
                {{ book.series_name }}
                <span v-if="book.series_position != null" class="font-medium">#{{ book.series_position }}</span>
              </div>

              <!-- Rating -->
              <div v-if="book.rating != null" class="flex items-center gap-1 mb-4">
                <svg
                  v-for="star in 5"
                  :key="star"
                  class="w-5 h-5"
                  :class="star <= (book.rating ?? 0) ? 'text-kindle-500' : 'text-stone-300'"
                  fill="currentColor"
                  viewBox="0 0 20 20"
                >
                  <path
                    d="M9.049 2.927c.3-.921 1.603-.921 1.902 0l1.07 3.292a1 1 0 00.95.69h3.462c.969 0 1.371 1.24.588 1.81l-2.8 2.034a1 1 0 00-.364 1.118l1.07 3.292c.3.921-.755 1.688-1.54 1.118l-2.8-2.034a1 1 0 00-1.175 0l-2.8 2.034c-.784.57-1.838-.197-1.539-1.118l1.07-3.292a1 1 0 00-.364-1.118L2.98 8.72c-.783-.57-.38-1.81.588-1.81h3.461a1 1 0 00.951-.69l1.07-3.292z"
                  />
                </svg>
                <span class="text-sm text-stone-500 ml-1">{{ book.rating }}/5</span>
              </div>

              <!-- Description -->
              <p v-if="book.description" class="text-stone-700 leading-relaxed mb-6">
                {{ book.description }}
              </p>
              <p v-else class="text-stone-500 italic mb-6">No description available.</p>

              <!-- Tags -->
              <div v-if="book.tags && book.tags.length > 0" class="flex flex-wrap gap-2 mb-6">
                <span
                  v-for="tag in book.tags"
                  :key="tag"
                  class="px-2.5 py-1 rounded-lg text-xs font-medium bg-stone-100 text-stone-600 border border-stone-200"
                >
                  {{ tag }}
                </span>
              </div>

              <!-- Action Buttons -->
              <div class="flex flex-wrap gap-3">
                <button @click="triggerSearch" :disabled="isSearching" class="btn btn-secondary">
                  <svg v-if="isSearching" class="w-4 h-4 animate-spin" fill="none" viewBox="0 0 24 24">
                    <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="3"></circle>
                    <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
                  </svg>
                  <svg v-else class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z"/>
                  </svg>
                  Search
                </button>
                <button @click="goToInteractiveSearch" class="btn btn-secondary">
                  <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 6h16M4 10h16M4 14h16M4 18h16"/>
                  </svg>
                  Interactive Search
                </button>
                <button
                  v-if="canSendToKindle"
                  @click="handleKindleRequeue"
                  :disabled="isRequeueingKindle"
                  class="btn btn-secondary"
                  data-testid="send-to-kindle-button"
                >
                  <svg v-if="isRequeueingKindle" class="w-4 h-4 animate-spin" fill="none" viewBox="0 0 24 24">
                    <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="3"></circle>
                    <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
                  </svg>
                  <svg v-else class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 19l9 2-9-18-9 18 9-2zm0 0v-8"/>
                  </svg>
                  {{ book.kindle_delivery_status === 'DELIVERED' ? 'Send Again' : 'Send to Kindle' }}
                </button>
                <button @click="enterEditMode" class="btn btn-primary">
                  <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path
                      stroke-linecap="round"
                      stroke-linejoin="round"
                      stroke-width="2"
                      d="M11 5H6a2 2 0 00-2 2v11a2 2 0 002 2h11a2 2 0 002-2v-5m-1.414-9.414a2 2 0 112.828 2.828L11.828 15H9v-2.828l8.586-8.586z"
                    />
                  </svg>
                  Edit
                </button>
                <button @click="showDeleteConfirm = true" class="btn btn-ghost text-error-600 hover:text-error-700 hover:bg-error-50">
                  <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path
                      stroke-linecap="round"
                      stroke-linejoin="round"
                      stroke-width="2"
                      d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16"
                    />
                  </svg>
                  Delete
                </button>
              </div>
            </template>

            <!-- EDIT MODE -->
            <template v-else>
              <form @submit.prevent="handleSave" class="space-y-5">
                <div>
                  <label class="label">Title</label>
                  <input v-model="editForm.title" type="text" class="input" required />
                </div>

                <div>
                  <label class="label">Author</label>
                  <input v-model="editForm.author_name" type="text" class="input" placeholder="Author name" />
                </div>

                <div class="grid grid-cols-1 md:grid-cols-2 gap-5">
                  <div>
                    <label class="label">Series</label>
                    <input
                      v-model="editForm.series_name"
                      type="text"
                      class="input"
                      placeholder="Series name"
                    />
                  </div>
                  <div>
                    <label class="label">Position in Series</label>
                    <input
                      v-model.number="editForm.series_position"
                      type="number"
                      step="0.1"
                      min="0"
                      class="input"
                      placeholder="#"
                    />
                  </div>
                </div>

                <div class="grid grid-cols-1 md:grid-cols-2 gap-5">
                  <div>
                    <label class="label">Publisher</label>
                    <input
                      v-model="editForm.publisher"
                      type="text"
                      class="input"
                      placeholder="Publisher name"
                    />
                  </div>
                  <div>
                    <label class="label">Language</label>
                    <select v-model="editForm.language" class="input">
                      <option value="">Unknown</option>
                      <option value="en">English</option>
                      <option value="es">Spanish</option>
                      <option value="fr">French</option>
                      <option value="de">German</option>
                      <option value="pt">Portuguese</option>
                      <option value="it">Italian</option>
                      <option value="nl">Dutch</option>
                      <option value="ru">Russian</option>
                      <option value="zh">Chinese</option>
                      <option value="ja">Japanese</option>
                      <option value="ko">Korean</option>
                    </select>
                  </div>
                </div>

                <div>
                  <label class="label">Read Date</label>
                  <input
                    v-model="editForm.read_date"
                    type="date"
                    class="input"
                  />
                </div>

                <div>
                  <label class="label">Description</label>
                  <textarea
                    v-model="editForm.description"
                    rows="4"
                    class="input resize-y"
                    placeholder="Book description..."
                  ></textarea>
                </div>

                <div>
                  <label class="label">Tags</label>
                  <input
                    v-model="editForm.tags"
                    type="text"
                    class="input"
                    placeholder="fiction, sci-fi, adventure"
                  />
                  <p class="text-xs text-stone-500 mt-1">Separate tags with commas</p>
                </div>

                <!-- Star Rating -->
                <div>
                  <label class="label">Rating</label>
                  <div class="flex items-center gap-1">
                    <button
                      v-for="star in 5"
                      :key="star"
                      type="button"
                      @click="setRating(star)"
                      @mouseenter="hoverRating = star"
                      @mouseleave="hoverRating = 0"
                      class="p-0.5 rounded transition-transform hover:scale-110 focus:outline-hidden"
                    >
                      <svg
                        class="w-7 h-7 transition-colors"
                        :class="
                          star <= (hoverRating || editForm.rating || 0)
                            ? 'text-kindle-500'
                            : 'text-stone-300'
                        "
                        fill="currentColor"
                        viewBox="0 0 20 20"
                      >
                        <path
                          d="M9.049 2.927c.3-.921 1.603-.921 1.902 0l1.07 3.292a1 1 0 00.95.69h3.462c.969 0 1.371 1.24.588 1.81l-2.8 2.034a1 1 0 00-.364 1.118l1.07 3.292c.3.921-.755 1.688-1.54 1.118l-2.8-2.034a1 1 0 00-1.175 0l-2.8 2.034c-.784.57-1.838-.197-1.539-1.118l1.07-3.292a1 1 0 00-.364-1.118L2.98 8.72c-.783-.57-.38-1.81.588-1.81h3.461a1 1 0 00.951-.69l1.07-3.292z"
                        />
                      </svg>
                    </button>
                    <button
                      v-if="editForm.rating"
                      type="button"
                      @click="editForm.rating = null"
                      class="ml-2 text-xs text-stone-500 hover:text-stone-700 transition-colors"
                    >
                      Clear
                    </button>
                  </div>
                </div>

                <!-- Form Actions -->
                <div class="flex gap-3 pt-2">
                  <button type="submit" class="btn btn-primary" :disabled="isSaving || !editForm.title">
                    <svg
                      v-if="isSaving"
                      class="w-4 h-4 animate-spin"
                      fill="none"
                      viewBox="0 0 24 24"
                    >
                      <circle
                        class="opacity-25"
                        cx="12"
                        cy="12"
                        r="10"
                        stroke="currentColor"
                        stroke-width="3"
                      ></circle>
                      <path
                        class="opacity-75"
                        fill="currentColor"
                        d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"
                      ></path>
                    </svg>
                    <template v-else>
                      <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path
                          stroke-linecap="round"
                          stroke-linejoin="round"
                          stroke-width="2"
                          d="M5 13l4 4L19 7"
                        />
                      </svg>
                    </template>
                    {{ isSaving ? 'Saving...' : 'Save Changes' }}
                  </button>
                  <button type="button" @click="cancelEdit" class="btn btn-secondary" :disabled="isSaving">
                    Cancel
                  </button>
                </div>
              </form>
            </template>
          </div>
        </div>
      </div>

      <!-- Metadata Card -->
      <div class="card animate-fade-in-up stagger-1">
        <div class="flex items-center gap-3 mb-6">
          <div class="icon-container">
            <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path
                stroke-linecap="round"
                stroke-linejoin="round"
                stroke-width="2"
                d="M13 16h-1v-4h-1m1-4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z"
              />
            </svg>
          </div>
          <h2 class="text-lg font-display font-semibold text-stone-900">Details</h2>
        </div>

        <div class="grid grid-cols-2 md:grid-cols-3 gap-6">
          <div>
            <p class="text-xs font-medium uppercase tracking-wider text-stone-500 mb-1">ISBN</p>
            <p class="text-sm text-stone-800">{{ book.isbn ?? '—' }}</p>
          </div>
          <div>
            <p class="text-xs font-medium uppercase tracking-wider text-stone-500 mb-1">Publisher</p>
            <p class="text-sm text-stone-800">{{ book.publisher ?? '—' }}</p>
          </div>
          <div>
            <p class="text-xs font-medium uppercase tracking-wider text-stone-500 mb-1">Language</p>
            <p class="text-sm text-stone-800">{{ book.language ?? '—' }}</p>
          </div>
          <div>
            <p class="text-xs font-medium uppercase tracking-wider text-stone-500 mb-1">Added</p>
            <p class="text-sm text-stone-800">{{ formatDate(book.created_at) }}</p>
          </div>
          <div>
            <p class="text-xs font-medium uppercase tracking-wider text-stone-500 mb-1">Updated</p>
            <p class="text-sm text-stone-800">{{ formatDate(book.updated_at) }}</p>
          </div>
          <div v-if="book.hardcover_id">
            <p class="text-xs font-medium uppercase tracking-wider text-stone-500 mb-1">Hardcover ID</p>
            <p class="text-sm text-stone-800 font-mono">{{ book.hardcover_id }}</p>
          </div>
          <div v-if="book.read_date">
            <p class="text-xs font-medium uppercase tracking-wider text-stone-500 mb-1">Read Date</p>
            <p class="text-sm text-stone-800">{{ formatDate(book.read_date) }}</p>
          </div>
        </div>
      </div>

      <!-- File Info Card -->
      <div class="card animate-fade-in-up stagger-2">
        <div class="flex items-center gap-3 mb-6">
          <div class="icon-container">
            <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
            </svg>
          </div>
          <h2 class="text-lg font-display font-semibold text-stone-900">File Info</h2>
        </div>

        <div class="grid grid-cols-1 md:grid-cols-2 gap-6">
          <div>
            <p class="text-xs font-medium uppercase tracking-wider text-stone-500 mb-1">File Path</p>
            <p class="text-sm text-stone-800 font-mono break-all">{{ book.file_path ?? '—' }}</p>
          </div>
          <div>
            <p class="text-xs font-medium uppercase tracking-wider text-stone-500 mb-1">File Size</p>
            <p class="text-sm text-stone-800">{{ formatFileSize(book.file_size) }}</p>
          </div>
          <div>
            <p class="text-xs font-medium uppercase tracking-wider text-stone-500 mb-1">Root Folder ID</p>
            <p class="text-sm text-stone-800">{{ book.root_folder_id ?? '—' }}</p>
          </div>
        </div>
      </div>

      <!-- Kindle Delivery Card -->
      <div v-if="showKindleCard" class="card animate-fade-in-up stagger-3">
        <div class="flex items-center gap-3 mb-6">
          <div class="icon-container">
            <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 18h.01M8 21h8a2 2 0 002-2V5a2 2 0 00-2-2H8a2 2 0 00-2 2v14a2 2 0 002 2z" />
            </svg>
          </div>
          <h2 class="text-lg font-display font-semibold text-stone-900">Kindle Delivery</h2>
        </div>

        <div class="flex flex-wrap items-center gap-x-8 gap-y-4">
          <div>
            <p class="text-xs font-medium uppercase tracking-wider text-stone-500 mb-1.5">Status</p>
            <KindleDeliveryBadge v-if="book.kindle_delivery_status" :status="book.kindle_delivery_status" />
            <p v-else class="text-sm text-stone-500">Not sent to Kindle yet</p>
          </div>
          <div v-if="book.kindle_delivery_status">
            <p class="text-xs font-medium uppercase tracking-wider text-stone-500 mb-1">Attempts</p>
            <p class="text-sm text-stone-800">{{ book.kindle_delivery_attempts ?? 0 }}</p>
          </div>
          <div v-if="book.kindle_delivery_status === 'DELIVERED' && book.kindle_delivered_at">
            <p class="text-xs font-medium uppercase tracking-wider text-stone-500 mb-1">Delivered</p>
            <p class="text-sm text-stone-800" :title="formatDate(book.kindle_delivered_at)">
              {{ formatRelativeTime(book.kindle_delivered_at) }}
            </p>
          </div>
          <div v-if="(book.kindle_delivery_status === 'PENDING' || book.kindle_delivery_status === 'SKIPPED') && book.kindle_first_pending_at">
            <p class="text-xs font-medium uppercase tracking-wider text-stone-500 mb-1">Waiting Since</p>
            <p class="text-sm text-stone-800">{{ formatDate(book.kindle_first_pending_at) }}</p>
          </div>
          <div v-if="book.kindle_pinned" data-testid="kindle-pinned-indicator">
            <p class="text-xs font-medium uppercase tracking-wider text-stone-500 mb-1.5">Pinned to Kindle</p>
            <div class="flex items-center gap-3">
              <span class="text-sm text-stone-800">Kept on the device between syncs</span>
              <button
                @click="handleKindleUnpin"
                :disabled="isUnpinningKindle"
                class="btn btn-secondary btn-sm"
                data-testid="kindle-unpin-button"
              >
                <svg v-if="isUnpinningKindle" class="w-4 h-4 animate-spin" fill="none" viewBox="0 0 24 24">
                  <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="3"></circle>
                  <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"></path>
                </svg>
                Unpin
              </button>
            </div>
            <p class="mt-1.5 text-xs text-stone-500">Unpinning removes it from the device on the next sync.</p>
          </div>
          <div v-if="canSendToKindle" class="ml-auto">
            <button
              @click="handleKindleRequeue"
              :disabled="isRequeueingKindle"
              class="btn btn-secondary"
              data-testid="kindle-requeue-button"
            >
              <svg v-if="isRequeueingKindle" class="w-4 h-4 animate-spin" fill="none" viewBox="0 0 24 24">
                <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="3"></circle>
                <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
              </svg>
              <svg v-else class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 19l9 2-9-18-9 18 9-2zm0 0v-8"/>
              </svg>
              {{ book.kindle_delivery_status === 'DELIVERED' ? 'Send Again' : 'Send to Kindle' }}
            </button>
          </div>
        </div>

        <div v-if="book.kindle_delivery_status === 'IN_PROGRESS'" class="mt-4 space-y-1.5" data-testid="kindle-delivery-progress">
          <div class="progress-bar progress-bar-animated">
            <div
              class="progress-bar-fill"
              :style="{ width: `${kindleDeliveryProgress ? Math.round(kindleDeliveryProgress.percentage) : 100}%` }"
            ></div>
          </div>
          <p v-if="kindleDeliveryProgress" class="text-xs text-stone-500 tabular-nums">
            {{ Math.round(kindleDeliveryProgress.percentage) }}% transferred
          </p>
          <p v-else class="text-xs text-stone-500">Transferring to the Kindle…</p>
        </div>

        <p v-if="book.kindle_delivery_status === 'SKIPPED'" class="text-sm text-amber-700 mt-4">
          Delivery gave up after the waiting period. It re-queues automatically the next time the
          Kindle is reachable, or press "Send to Kindle" to re-queue now.
        </p>
        <p v-else-if="book.kindle_delivery_status === 'PENDING'" class="text-sm text-stone-500 mt-4">
          Will be sent automatically once the Kindle is turned on and connected.
        </p>
        <p v-else-if="!book.kindle_delivery_status" class="text-sm text-stone-500 mt-4">
          Press "Send to Kindle" to queue it — it transfers right away when the Kindle is on.
        </p>
      </div>
    </template>

    <!-- Delete Confirmation Modal -->
    <Teleport to="body">
      <Transition
        enter-active-class="transition-opacity duration-200 ease-out"
        enter-from-class="opacity-0"
        enter-to-class="opacity-100"
        leave-active-class="transition-opacity duration-150 ease-in"
        leave-from-class="opacity-100"
        leave-to-class="opacity-0"
      >
        <div v-if="showDeleteConfirm" class="modal-overlay" @click.self="showDeleteConfirm = false">
          <div class="modal-content">
            <div class="flex items-center gap-3 mb-4">
              <div
                class="flex items-center justify-center w-10 h-10 rounded-full bg-error-50 text-error-600"
              >
                <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path
                    stroke-linecap="round"
                    stroke-linejoin="round"
                    stroke-width="2"
                    d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-2.5L13.732 4c-.77-.833-1.964-.833-2.732 0L4.082 16.5c-.77.833.192 2.5 1.732 2.5z"
                  />
                </svg>
              </div>
              <h3 class="text-lg font-display font-semibold text-stone-900">Delete Book</h3>
            </div>
            <p class="text-stone-600 mb-6">
              Are you sure you want to delete <strong class="text-stone-900">{{ book?.title }}</strong>? This action cannot be undone.
            </p>
            <div class="flex justify-end gap-3">
              <button
                @click="showDeleteConfirm = false"
                class="btn btn-secondary"
                :disabled="isDeleting"
              >
                Cancel
              </button>
              <button @click="handleDelete" class="btn btn-danger" :disabled="isDeleting">
                <svg
                  v-if="isDeleting"
                  class="w-4 h-4 animate-spin"
                  fill="none"
                  viewBox="0 0 24 24"
                >
                  <circle
                    class="opacity-25"
                    cx="12"
                    cy="12"
                    r="10"
                    stroke="currentColor"
                    stroke-width="3"
                  ></circle>
                  <path
                    class="opacity-75"
                    fill="currentColor"
                    d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"
                  ></path>
                </svg>
                {{ isDeleting ? 'Deleting...' : 'Delete Book' }}
              </button>
            </div>
          </div>
        </div>
      </Transition>
    </Teleport>
  </div>
</template>
