<script setup lang="ts">
import { computed, ref } from 'vue'
import { useKindlesStore } from '@/stores/kindles'
import { useSyncStore } from '@/stores/sync'
import { formatEta, formatSize, formatSpeed } from '@/utils/format'

const kindlesStore = useKindlesStore()
const syncStore = useSyncStore()

const progress = computed(() => syncStore.kindleSyncProgress)
const preview = computed(() => syncStore.kindleSyncPreview)

const previewing = ref(false)
const showWouldSend = ref(false)
const showWouldDelete = ref(false)

const busy = computed(() => syncStore.kindleSyncing || previewing.value)

const startSync = async () => {
  if (!kindlesStore.selectedKindleId) return
  try {
    await syncStore.triggerKindleSync(kindlesStore.selectedKindleId)
  } catch {
    // triggerKindleSync already surfaces a toast
  }
}

const startPreview = async () => {
  if (!kindlesStore.selectedKindleId) return
  previewing.value = true
  showWouldSend.value = false
  showWouldDelete.value = false
  try {
    await syncStore.triggerKindleSync(kindlesStore.selectedKindleId, true)
  } catch {
    // triggerKindleSync already surfaces a toast
  } finally {
    previewing.value = false
  }
}

const basename = (path: string) => path.split('/').pop() || path
</script>

<template>
  <div class="card" data-testid="kindle-sync-card">
    <div class="flex items-center justify-between mb-4">
      <h2 class="text-lg font-display font-semibold text-stone-900">Sync Shelves</h2>
      <span v-if="syncStore.kindleSyncInfo" class="text-xs text-stone-500 tabular-nums">
        {{ syncStore.kindleSyncInfo.total_books }} book{{ syncStore.kindleSyncInfo.total_books === 1 ? '' : 's' }}
      </span>
    </div>

    <p class="text-sm text-stone-500 mb-4">
      Sends books on your synced shelves that aren't on the device yet, then removes everything else. Pinned books are kept.
    </p>

    <div class="flex items-center gap-3">
      <button
        class="btn btn-primary"
        :disabled="busy || !kindlesStore.selectedKindleId"
        data-testid="kindle-sync-button"
        @click="startSync"
      >
        <svg v-if="syncStore.kindleSyncing" class="w-4 h-4 animate-spin" fill="none" viewBox="0 0 24 24">
          <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="3"></circle>
          <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"></path>
        </svg>
        {{ syncStore.kindleSyncing ? 'Syncing…' : 'Sync Now' }}
      </button>
      <button
        class="btn btn-secondary"
        :disabled="busy || !kindlesStore.selectedKindleId"
        data-testid="kindle-preview-button"
        @click="startPreview"
      >
        <svg v-if="previewing" class="w-4 h-4 animate-spin" fill="none" viewBox="0 0 24 24">
          <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="3"></circle>
          <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"></path>
        </svg>
        {{ previewing ? 'Previewing…' : 'Preview' }}
      </button>
    </div>

    <div v-if="preview" class="mt-5 space-y-3" data-testid="kindle-sync-preview">
      <p class="text-sm font-medium text-stone-800 tabular-nums">
        Would send {{ preview.would_send.length }} · Would delete {{ preview.would_delete.length }}
      </p>

      <div v-if="preview.would_send.length > 0">
        <button
          class="text-sm font-medium text-kindle-600 hover:text-kindle-700 transition-colors"
          @click="showWouldSend = !showWouldSend"
        >
          {{ showWouldSend ? 'Hide' : 'Show' }} books to send
        </button>
        <ul v-if="showWouldSend" class="mt-2 space-y-1">
          <li
            v-for="item in preview.would_send"
            :key="item.book_id"
            class="text-sm text-stone-600 truncate"
          >
            {{ item.title }}
          </li>
        </ul>
      </div>

      <div v-if="preview.would_delete.length > 0">
        <button
          class="text-sm font-medium text-kindle-600 hover:text-kindle-700 transition-colors"
          @click="showWouldDelete = !showWouldDelete"
        >
          {{ showWouldDelete ? 'Hide' : 'Show' }} files to delete
        </button>
        <ul v-if="showWouldDelete" class="mt-2 space-y-1">
          <li
            v-for="path in preview.would_delete"
            :key="path"
            class="text-sm text-stone-600 font-mono truncate"
            :title="path"
          >
            {{ basename(path) }}
          </li>
        </ul>
      </div>
    </div>

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
