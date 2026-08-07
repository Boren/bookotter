<script setup lang="ts">
import { useEreadersStore } from '@/stores/ereaders'
import { formatRelativeTime, formatSize } from '@/utils/format'

const ereadersStore = useEreadersStore()

const refresh = () => {
  if (ereadersStore.selectedEreaderId) {
    ereadersStore.fetchDeviceBooks(ereadersStore.selectedEreaderId)
  }
}
</script>

<template>
  <div class="card" data-testid="ereader-device-books-card">
    <div class="flex items-center justify-between mb-4">
      <h2 class="text-lg font-display font-semibold text-stone-900">
        On Device
        <span v-if="ereadersStore.deviceBooks.length > 0" class="text-sm font-normal text-stone-500">
          ({{ ereadersStore.deviceBooks.length }})
        </span>
      </h2>
      <button
        class="btn btn-secondary btn-sm"
        :disabled="ereadersStore.deviceBooksLoading || !ereadersStore.selectedEreaderId"
        @click="refresh"
      >
        {{ ereadersStore.deviceBooksLoading ? 'Reading…' : 'Refresh' }}
      </button>
    </div>

    <div v-if="ereadersStore.deviceBooksLoading && ereadersStore.deviceBooks.length === 0" class="py-8 text-center text-sm text-stone-400">
      Reading the E-reader over SSH…
    </div>

    <div v-else-if="ereadersStore.deviceBooksError" class="empty-state py-8">
      <p class="text-sm text-stone-500">
        Couldn't read the device — it's probably off or asleep.
      </p>
      <p class="text-xs text-stone-400 mt-1">{{ ereadersStore.deviceBooksError }}</p>
    </div>

    <div v-else-if="ereadersStore.deviceBooks.length === 0" class="empty-state py-8">
      <p class="text-sm text-stone-500">No books on the device yet.</p>
    </div>

    <div v-else class="overflow-x-auto -mx-2">
      <table class="w-full text-sm">
        <thead>
          <tr class="text-left text-xs text-stone-500 uppercase tracking-wide">
            <th class="px-2 py-2 font-medium">File</th>
            <th class="px-2 py-2 font-medium text-right">Size</th>
            <th class="px-2 py-2 font-medium text-right whitespace-nowrap">Modified</th>
          </tr>
        </thead>
        <tbody class="divide-y divide-stone-100">
          <tr v-for="file in ereadersStore.deviceBooks" :key="file.name">
            <td class="px-2 py-2 break-all">
              <template v-if="file.book_id">
                <RouterLink
                  :to="`/library/${file.book_id}`"
                  class="font-medium text-stone-900 hover:text-ereader-700"
                >
                  {{ file.title }}
                </RouterLink>
                <div class="text-xs text-stone-400">{{ file.name }}</div>
              </template>
              <span v-else class="text-stone-800">{{ file.name }}</span>
            </td>
            <td class="px-2 py-2 text-right text-stone-500 tabular-nums whitespace-nowrap">
              {{ formatSize(file.size) }}
            </td>
            <td class="px-2 py-2 text-right text-stone-500 whitespace-nowrap">
              {{ formatRelativeTime(file.modified) }}
            </td>
          </tr>
        </tbody>
      </table>
      <p v-if="ereadersStore.deviceBooksFetchedAt" class="px-2 pt-3 text-xs text-stone-400">
        As read from the device {{ formatRelativeTime(ereadersStore.deviceBooksFetchedAt.toISOString()) }}
      </p>
    </div>
  </div>
</template>
