<script setup lang="ts">
import { onMounted } from 'vue'
import { useWantedStore } from '../stores/wanted'
import StatusBadge from '../components/StatusBadge.vue'

const store = useWantedStore()

onMounted(() => {
  store.fetchMissing()
})

const handleSearchAll = () => {
  store.searchAll()
}
</script>

<template>
  <div class="space-y-6">
    <!-- Page Header -->
    <div class="page-header">
      <div class="flex flex-col sm:flex-row sm:items-end sm:justify-between gap-2">
        <div>
          <h1 class="page-title">Wanted</h1>
          <p class="page-subtitle">Books missing from your library</p>
        </div>
        <button
          @click="handleSearchAll"
          :disabled="store.isSearchingAll || store.books.length === 0"
          class="btn btn-primary"
        >
          <svg v-if="store.isSearchingAll" class="animate-spin -ml-1 mr-2 h-4 w-4 text-white" fill="none" viewBox="0 0 24 24">
            <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="3"></circle>
            <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
          </svg>
          <svg v-else class="w-4 h-4 mr-2" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z"/>
          </svg>
          {{ store.isSearchingAll ? 'Searching...' : 'Search All' }}
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
          <p class="text-sm font-medium text-error-800">Failed to load wanted books</p>
          <p class="text-sm text-error-600 mt-0.5">{{ store.error }}</p>
        </div>
      </div>
    </Transition>

    <!-- Loading State -->
    <div v-if="store.isLoading" class="flex justify-center py-16">
      <div class="flex items-center gap-3 text-stone-500">
        <svg class="animate-spin h-6 w-6 text-kindle-600" fill="none" viewBox="0 0 24 24">
          <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="3"></circle>
          <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
        </svg>
        <span class="text-sm font-medium">Loading wanted books...</span>
      </div>
    </div>

    <!-- Book List -->
    <div v-else-if="store.books.length > 0" class="card overflow-hidden">
      <div class="overflow-x-auto">
        <table class="w-full text-left border-collapse">
          <thead>
            <tr class="border-b border-stone-200 bg-stone-50/50">
              <th class="px-4 py-3 text-xs font-medium text-stone-500 uppercase tracking-wider w-16">Cover</th>
              <th class="px-4 py-3 text-xs font-medium text-stone-500 uppercase tracking-wider">Title</th>
              <th class="px-4 py-3 text-xs font-medium text-stone-500 uppercase tracking-wider">Author</th>
              <th class="px-4 py-3 text-xs font-medium text-stone-500 uppercase tracking-wider">Status</th>
              <th class="px-4 py-3 text-xs font-medium text-stone-500 uppercase tracking-wider text-right">Actions</th>
            </tr>
          </thead>
          <tbody class="divide-y divide-stone-100">
            <tr v-for="book in store.books" :key="book.id" class="hover:bg-stone-50/50 transition-colors">
              <td class="px-4 py-3">
                <div class="w-10 h-14 rounded overflow-hidden bg-stone-100 shadow-sm">
                  <img
                    v-if="book.cover_url"
                    :src="book.cover_url"
                    :alt="book.title"
                    class="w-full h-full object-cover"
                    loading="lazy"
                  />
                  <div v-else class="w-full h-full flex items-center justify-center bg-stone-200/50">
                    <svg class="w-5 h-5 text-stone-300" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M12 6.253v13m0-13C10.832 5.477 9.246 5 7.5 5S4.168 5.477 3 6.253v13C4.168 18.477 5.754 18 7.5 18s3.332.477 4.5 1.253m0-13C13.168 5.477 14.754 5 16.5 5c1.747 0 3.332.477 4.5 1.253v13C19.832 18.477 18.247 18 16.5 18c-1.746 0-3.332.477-4.5 1.253"/>
                    </svg>
                  </div>
                </div>
              </td>
              <td class="px-4 py-3">
                <router-link
                  :to="{ name: 'book-detail', params: { id: book.id } }"
                  class="font-medium text-stone-900 hover:text-kindle-600 transition-colors"
                >
                  {{ book.title }}
                </router-link>
                <div v-if="book.series_name" class="text-xs text-stone-500 mt-0.5">
                  {{ book.series_name }}<span v-if="book.series_position"> #{{ book.series_position }}</span>
                </div>
              </td>
              <td class="px-4 py-3 text-sm text-stone-600">
                {{ book.author?.name || 'Unknown Author' }}
              </td>
              <td class="px-4 py-3">
                <StatusBadge :status="book.status" />
              </td>
              <td class="px-4 py-3 text-right">
                <router-link
                  :to="{ name: 'search', query: { q: book.title } }"
                  class="btn btn-secondary py-1.5 px-3 text-xs"
                >
                  Search
                </router-link>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>

    <!-- Empty State -->
    <div v-else class="card">
      <div class="empty-state">
        <div class="empty-state-icon">
          <svg fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z"/>
          </svg>
        </div>
        <p class="empty-state-title">No missing books</p>
        <p class="empty-state-description">
          All books in your library have been downloaded.
        </p>
      </div>
    </div>
  </div>
</template>
