<script setup lang="ts">
import type { BookResult } from '../types'

defineProps<{
  books: BookResult[]
}>()

const getStatusBadge = (status: string, readingStatus: string | null) => {
  // If book was removed, show that prominently
  if (status === 'removed') {
    return {
      tooltip: 'Removed',
      class: 'badge-icon badge-error',
      icon: `<svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"/>
      </svg>`
    }
  }

  // Otherwise show reading status
  switch (readingStatus) {
    case 'currently_reading':
      return {
        tooltip: 'Currently Reading',
        class: 'badge-icon badge-info',
        icon: `<svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 6.253v13m0-13C10.832 5.477 9.246 5 7.5 5S4.168 5.477 3 6.253v13C4.168 18.477 5.754 18 7.5 18s3.332.477 4.5 1.253m0-13C13.168 5.477 14.754 5 16.5 5c1.747 0 3.332.477 4.5 1.253v13C19.832 18.477 18.247 18 16.5 18c-1.746 0-3.332.477-4.5 1.253"/>
        </svg>`
      }
    case 'read':
      return {
        tooltip: 'Read',
        class: 'badge-icon badge-success',
        icon: `<svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 13l4 4L19 7"/>
        </svg>`
      }
    case 'want_to_read':
    default:
      return {
        tooltip: 'Want to Read',
        class: 'badge-icon badge-warning',
        icon: `<svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 5a2 2 0 012-2h10a2 2 0 012 2v16l-7-3.5L5 21V5z"/>
        </svg>`
      }
  }
}
</script>

<template>
  <div class="overflow-x-auto scrollbar-hide -mx-6 px-6">
    <div class="flex gap-4 pb-2" style="min-width: max-content;">
      <div
        v-for="book in books"
        :key="book.id"
        class="shrink-0 w-32 group"
      >
        <!-- Book Cover -->
        <div class="relative mb-2">
          <img
            v-if="book.cover_url"
            :src="book.cover_url"
            :alt="book.title"
            class="w-32 h-48 object-cover rounded-lg shadow-warm transition-transform group-hover:scale-105"
          />
          <div
            v-else
            class="w-32 h-48 rounded-lg bg-stone-100 flex items-center justify-center shadow-warm"
          >
            <svg class="w-8 h-8 text-stone-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M12 6.253v13m0-13C10.832 5.477 9.246 5 7.5 5S4.168 5.477 3 6.253v13C4.168 18.477 5.754 18 7.5 18s3.332.477 4.5 1.253m0-13C13.168 5.477 14.754 5 16.5 5c1.747 0 3.332.477 4.5 1.253v13C19.832 18.477 18.247 18 16.5 18c-1.746 0-3.332.477-4.5 1.253"/>
            </svg>
          </div>

          <!-- Status Badge Overlay -->
          <span
            class="absolute top-2 right-2 shadow-xs"
            :class="getStatusBadge(book.status, book.reading_status).class"
            :title="getStatusBadge(book.status, book.reading_status).tooltip"
            v-html="getStatusBadge(book.status, book.reading_status).icon"
          />

          <!-- Removed indicator icon -->
          <div
            v-if="book.status === 'removed'"
            class="absolute inset-0 bg-stone-900/30 rounded-lg flex items-center justify-center"
          >
            <svg class="w-10 h-10 text-white/80" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16"/>
            </svg>
          </div>
        </div>

        <!-- Book Info -->
        <p class="text-sm font-medium text-stone-900 line-clamp-2 leading-tight">
          {{ book.title }}
        </p>
        <p class="text-xs text-stone-500 line-clamp-1 mt-0.5">
          {{ book.author || 'Unknown Author' }}
        </p>
      </div>
    </div>
  </div>
</template>
