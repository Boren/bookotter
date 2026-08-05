<script setup lang="ts">
import { computed } from 'vue'
import { useKindlesStore } from '@/stores/kindles'
import { useSyncStore } from '@/stores/sync'
import { formatEta, formatSize, formatSpeed } from '@/utils/format'

const kindlesStore = useKindlesStore()
const syncStore = useSyncStore()

const progress = computed(() => syncStore.kindleSyncProgress)

const startSync = async () => {
  if (!kindlesStore.selectedKindleId) return
  try {
    await syncStore.triggerKindleSync(kindlesStore.selectedKindleId)
  } catch {
    // triggerKindleSync already surfaces a toast
  }
}
</script>

<template>
  <div class="card" data-testid="kindle-sync-card">
    <div class="flex items-center justify-between mb-4">
      <h2 class="text-lg font-display font-semibold text-stone-900">Sync Library</h2>
      <span v-if="syncStore.kindleSyncInfo" class="text-xs text-stone-500 tabular-nums">
        {{ syncStore.kindleSyncInfo.total_books }} book{{ syncStore.kindleSyncInfo.total_books === 1 ? '' : 's' }}
      </span>
    </div>

    <p class="text-sm text-stone-500 mb-4">
      Copies every library book to the Kindle. Books already on the device are skipped.
    </p>

    <button
      class="btn btn-primary"
      :disabled="syncStore.kindleSyncing || !kindlesStore.selectedKindleId"
      data-testid="kindle-sync-button"
      @click="startSync"
    >
      <svg v-if="syncStore.kindleSyncing" class="w-4 h-4 animate-spin" fill="none" viewBox="0 0 24 24">
        <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="3"></circle>
        <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"></path>
      </svg>
      {{ syncStore.kindleSyncing ? 'Syncing…' : 'Sync All Books' }}
    </button>

    <div v-if="syncStore.kindleSyncing" class="mt-5 space-y-2" data-testid="kindle-sync-progress">
      <div class="flex items-baseline justify-between gap-3">
        <p class="text-sm font-medium text-stone-800 line-clamp-1">
          {{ progress?.book_title || 'Preparing transfer…' }}
        </p>
        <span v-if="progress" class="text-sm text-stone-600 tabular-nums shrink-0">
          {{ Math.round(progress.percentage) }}%
        </span>
      </div>
      <div class="progress-bar progress-bar-animated">
        <div class="progress-bar-fill" :style="{ width: `${progress ? Math.round(progress.percentage) : 0}%` }"></div>
      </div>
      <p v-if="progress" class="text-xs text-stone-500 tabular-nums">
        {{ formatSize(progress.bytes_transferred) }} / {{ formatSize(progress.bytes_total) }}
        · {{ formatSpeed(progress.speed_bytes_per_sec) }}
        · ETA {{ formatEta(progress.eta_seconds) }}
      </p>
    </div>
  </div>
</template>
