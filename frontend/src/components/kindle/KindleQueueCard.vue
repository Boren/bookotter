<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import KindleDeliveryBadge from '@/components/KindleDeliveryBadge.vue'
import { useLibraryStore } from '@/stores/library'
import { useSyncStore } from '@/stores/sync'
import type { Book } from '@/types'
import { formatRelativeTime } from '@/utils/format'

const libraryStore = useLibraryStore()
const syncStore = useSyncStore()

const queueBooks = ref<Book[]>([])
const isLoading = ref(false)
const requeueingId = ref<number | null>(null)

// Direct fetches with the delivery filter — deliberately not the shared
// library-store filters, which would clobber the Library view's state.
const fetchQueue = async () => {
  isLoading.value = true
  try {
    const statuses = ['IN_PROGRESS', 'PENDING', 'SKIPPED']
    const results = await Promise.all(
      statuses.map(async (s) => {
        const res = await fetch(`/api/library/books?kindle_delivery_status=${s}&sort_by=updated_at&sort_order=desc&limit=100`)
        if (!res.ok) return []
        const data = await res.json()
        return data.books as Book[]
      })
    )
    queueBooks.value = results.flat()
  } finally {
    isLoading.value = false
  }
}

// Kindle WS events refresh pipeline stats; piggyback on that to stay live
watch(() => syncStore.pipelineStats, fetchQueue)

const deliveryProgressFor = (book: Book) => {
  const p = syncStore.kindleDeliveryProgress
  return p && p.book_id === book.id ? p : null
}

const sendNow = async (book: Book) => {
  requeueingId.value = book.id
  try {
    await libraryStore.requeueKindle(book.id)
    await fetchQueue()
  } finally {
    requeueingId.value = null
  }
}

const pendingCount = computed(
  () => queueBooks.value.filter((b) => b.kindle_delivery_status === 'PENDING').length
)

onMounted(fetchQueue)
</script>

<template>
  <div class="card" data-testid="kindle-queue-card">
    <div class="flex items-center justify-between mb-4">
      <h2 class="text-lg font-display font-semibold text-stone-900">Delivery Queue</h2>
      <span v-if="pendingCount > 0" class="badge badge-warning">{{ pendingCount }} waiting</span>
    </div>

    <div v-if="isLoading && queueBooks.length === 0" class="py-8 text-center text-sm text-stone-400">
      Loading queue…
    </div>

    <div v-else-if="queueBooks.length === 0" class="empty-state py-8">
      <p class="text-sm text-stone-500">Nothing queued — every requested book is on the Kindle.</p>
    </div>

    <ul v-else class="divide-y divide-stone-100">
      <li v-for="book in queueBooks" :key="book.id" class="py-3 first:pt-0 last:pb-0">
        <div class="flex items-center gap-3">
          <RouterLink :to="`/library/${book.id}`" class="shrink-0">
            <img
              v-if="book.cover_url"
              :src="book.cover_url"
              :alt="book.title"
              class="w-9 h-13 rounded object-cover shadow-warm-sm"
            />
            <div v-else class="w-9 h-13 rounded bg-stone-100 flex items-center justify-center text-stone-300">
              <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M12 6.253v13m0-13C10.832 5.477 9.246 5 7.5 5S4.168 5.477 3 6.253v13C4.168 18.477 5.754 18 7.5 18s3.332.477 4.5 1.253m0-13C13.168 5.477 14.754 5 16.5 5c1.747 0 3.332.477 4.5 1.253v13C19.832 18.477 18.247 18 16.5 18c-1.746 0-3.332.477-4.5 1.253"/>
              </svg>
            </div>
          </RouterLink>

          <div class="min-w-0 flex-1">
            <RouterLink
              :to="`/library/${book.id}`"
              class="text-sm font-medium text-stone-900 hover:text-kindle-700 line-clamp-1"
            >
              {{ book.title }}
            </RouterLink>
            <p class="text-xs text-stone-500 line-clamp-1">
              {{ book.author?.name || 'Unknown author' }}
              <template v-if="book.kindle_delivery_status === 'PENDING' && book.kindle_first_pending_at">
                · waiting since {{ formatRelativeTime(book.kindle_first_pending_at) }}
              </template>
            </p>
          </div>

          <KindleDeliveryBadge :status="book.kindle_delivery_status" class="shrink-0" />

          <button
            v-if="book.kindle_delivery_status !== 'IN_PROGRESS'"
            class="btn btn-secondary btn-sm shrink-0"
            :disabled="requeueingId === book.id"
            @click="sendNow(book)"
          >
            {{ book.kindle_delivery_status === 'SKIPPED' ? 'Retry' : 'Send now' }}
          </button>
        </div>

        <div v-if="book.kindle_delivery_status === 'IN_PROGRESS'" class="mt-2 ml-12">
          <div class="progress-bar progress-bar-animated">
            <div
              class="progress-bar-fill"
              :style="{ width: `${deliveryProgressFor(book) ? Math.round(deliveryProgressFor(book)!.percentage) : 100}%` }"
            ></div>
          </div>
        </div>
      </li>
    </ul>
  </div>
</template>
