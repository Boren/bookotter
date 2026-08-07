<script setup lang="ts">
import { computed, ref } from 'vue'
import { useEreadersStore } from '@/stores/ereaders'
import { useSyncStore } from '@/stores/sync'
import { formatEta, formatSize, formatSpeed } from '@/utils/format'

const ereadersStore = useEreadersStore()
const syncStore = useSyncStore()

const progress = computed(() => syncStore.ereaderSyncProgress)
const preview = computed(() => syncStore.ereaderSyncPreview)

const previewing = ref(false)
const showWouldSend = ref(false)
const showWouldDelete = ref(false)

const busy = computed(() => syncStore.ereaderSyncing || previewing.value)

const startSync = async () => {
  if (!ereadersStore.selectedEreaderId) return
  try {
    await syncStore.triggerEreaderSync(ereadersStore.selectedEreaderId)
  } catch {
    // triggerEreaderSync already surfaces a toast
  }
}

const startPreview = async () => {
  if (!ereadersStore.selectedEreaderId) return
  previewing.value = true
  showWouldSend.value = false
  showWouldDelete.value = false
  try {
    await syncStore.triggerEreaderSync(ereadersStore.selectedEreaderId, true)
  } catch {
    // triggerEreaderSync already surfaces a toast
  } finally {
    previewing.value = false
  }
}

const basename = (path: string) => path.split('/').pop() || path
</script>

<template>
  <div class="card" data-testid="ereader-sync-card">
    <div class="flex items-center justify-between mb-4">
      <h2 class="text-lg font-display font-semibold text-stone-900">Sync Shelves</h2>
      <span v-if="syncStore.ereaderSyncInfo" class="text-xs text-stone-500 tabular-nums">
        {{ syncStore.ereaderSyncInfo.total_books }} book{{ syncStore.ereaderSyncInfo.total_books === 1 ? '' : 's' }}
      </span>
    </div>

    <p class="text-sm text-stone-500 mb-4">
      Sends books on your synced shelves that aren't on the device yet, then removes everything else. Pinned books are kept.
    </p>

    <div class="flex items-center gap-3">
      <button
        class="btn btn-primary"
        :disabled="busy || !ereadersStore.selectedEreaderId"
        data-testid="ereader-sync-button"
        @click="startSync"
      >
        <svg v-if="syncStore.ereaderSyncing" class="w-4 h-4 animate-spin" fill="none" viewBox="0 0 24 24">
          <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="3"></circle>
          <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"></path>
        </svg>
        {{ syncStore.ereaderSyncing ? 'Syncing…' : 'Sync Now' }}
      </button>
      <button
        class="btn btn-secondary"
        :disabled="busy || !ereadersStore.selectedEreaderId"
        data-testid="ereader-preview-button"
        @click="startPreview"
      >
        <svg v-if="previewing" class="w-4 h-4 animate-spin" fill="none" viewBox="0 0 24 24">
          <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="3"></circle>
          <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"></path>
        </svg>
        {{ previewing ? 'Previewing…' : 'Preview' }}
      </button>
    </div>

    <div v-if="preview" class="mt-5 space-y-3" data-testid="ereader-sync-preview">
      <p class="text-sm font-medium text-stone-800 tabular-nums">
        Would send {{ preview.would_send.length }} · Would delete {{ preview.would_delete.length }}
      </p>

      <div v-if="preview.would_send.length > 0">
        <button
          class="text-sm font-medium text-ereader-600 hover:text-ereader-700 transition-colors"
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
          class="text-sm font-medium text-ereader-600 hover:text-ereader-700 transition-colors"
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

    <div v-if="syncStore.ereaderSyncing" class="mt-5 space-y-2" data-testid="ereader-sync-progress">
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
