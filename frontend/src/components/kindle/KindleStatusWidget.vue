<script setup lang="ts">
import { computed, onMounted } from 'vue'
import { useKindlesStore } from '@/stores/kindles'
import { useSyncStore } from '@/stores/sync'

const kindlesStore = useKindlesStore()
const syncStore = useSyncStore()

const status = computed(() => kindlesStore.selectedStatus)
const pendingCount = computed(
  () => syncStore.pipelineStats?.by_kindle_delivery_status?.PENDING || 0
)

const statusDot = computed(() => {
  if (!kindlesStore.selectedKindle) return { class: 'bg-stone-300', label: 'No device' }
  if (!status.value) return { class: 'bg-stone-300 animate-pulse', label: 'Checking…' }
  if (!status.value.configured) return { class: 'bg-stone-400', label: 'Not configured' }
  return status.value.reachable
    ? { class: 'bg-success-500', label: 'Online' }
    : { class: 'bg-error-500', label: 'Offline' }
})

const startSync = async (event: Event) => {
  event.preventDefault()
  event.stopPropagation()
  if (!kindlesStore.selectedKindleId) return
  try {
    await syncStore.triggerKindleSync(kindlesStore.selectedKindleId)
  } catch {
    // toast already shown by the store
  }
}

onMounted(async () => {
  if (kindlesStore.kindles.length === 0) {
    await kindlesStore.fetchKindles()
  }
  if (kindlesStore.selectedKindleId && !kindlesStore.selectedStatus) {
    kindlesStore.fetchStatus(kindlesStore.selectedKindleId)
  }
})
</script>

<template>
  <RouterLink
    to="/kindle"
    class="card block hover:shadow-warm-lg transition-shadow"
    data-testid="kindle-status-widget"
  >
    <div class="flex items-center justify-between gap-3">
      <div class="flex items-center gap-3 min-w-0">
        <div class="icon-container shrink-0">
          <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M12 18h.01M8 21h8a2 2 0 002-2V5a2 2 0 00-2-2H8a2 2 0 00-2 2v14a2 2 0 002 2z"/>
          </svg>
        </div>
        <div class="min-w-0">
          <div class="flex items-center gap-2">
            <h2 class="text-lg font-display font-semibold text-stone-900 truncate">
              {{ kindlesStore.selectedKindle?.name || 'Kindle' }}
            </h2>
            <span class="w-2.5 h-2.5 rounded-full shrink-0" :class="statusDot.class"></span>
          </div>
          <p class="text-xs text-stone-500">
            {{ statusDot.label }}
            <template v-if="pendingCount > 0"> · {{ pendingCount }} queued</template>
          </p>
        </div>
      </div>

      <button
        class="btn btn-secondary btn-sm shrink-0"
        :disabled="syncStore.kindleSyncing || !kindlesStore.selectedKindleId"
        @click="startSync"
      >
        <svg v-if="syncStore.kindleSyncing" class="w-4 h-4 animate-spin" fill="none" viewBox="0 0 24 24">
          <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="3"></circle>
          <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"></path>
        </svg>
        {{ syncStore.kindleSyncing ? 'Syncing…' : 'Sync' }}
      </button>
    </div>

    <div v-if="syncStore.kindleSyncing" class="mt-4 space-y-1.5">
      <div class="progress-bar progress-bar-animated">
        <div
          class="progress-bar-fill"
          :style="{ width: `${syncStore.kindleSyncProgress ? Math.round(syncStore.kindleSyncProgress.percentage) : 0}%` }"
        ></div>
      </div>
      <p class="text-xs text-stone-500 truncate tabular-nums">
        {{ syncStore.kindleSyncProgress?.book_title || 'Preparing…' }}
        <template v-if="syncStore.kindleSyncProgress">
          — {{ Math.round(syncStore.kindleSyncProgress.percentage) }}%
        </template>
      </p>
    </div>
  </RouterLink>
</template>
