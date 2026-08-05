<script setup lang="ts">
import { onMounted, watch } from 'vue'
import KindleDeviceBooksCard from '@/components/kindle/KindleDeviceBooksCard.vue'
import KindleDeviceCard from '@/components/kindle/KindleDeviceCard.vue'
import KindleQueueCard from '@/components/kindle/KindleQueueCard.vue'
import KindleSyncCard from '@/components/kindle/KindleSyncCard.vue'
import { useKindlesStore } from '@/stores/kindles'
import { useSyncStore } from '@/stores/sync'

const kindlesStore = useKindlesStore()
const syncStore = useSyncStore()

onMounted(async () => {
  syncStore.fetchPipelineStats()
  await kindlesStore.fetchKindles()
  if (kindlesStore.selectedKindleId) {
    kindlesStore.fetchStatus(kindlesStore.selectedKindleId)
    kindlesStore.fetchDeviceBooks(kindlesStore.selectedKindleId)
  }
})

// A completed sync means new files on the device — refresh the live listing
watch(
  () => syncStore.kindleSyncing,
  (syncing, wasSyncing) => {
    if (wasSyncing && !syncing && kindlesStore.selectedKindleId) {
      kindlesStore.fetchDeviceBooks(kindlesStore.selectedKindleId)
    }
  }
)
</script>

<template>
  <div class="space-y-8">
    <div class="page-header">
      <h1 class="page-title">Kindle</h1>
      <p class="page-subtitle">Device status, delivery queue, and what's on your Kindle</p>
    </div>

    <div class="grid grid-cols-1 lg:grid-cols-2 gap-6">
      <div class="space-y-6">
        <KindleDeviceCard class="animate-fade-in-up stagger-1" />
        <KindleSyncCard class="animate-fade-in-up stagger-2" />
        <KindleQueueCard class="animate-fade-in-up stagger-3" />
      </div>
      <KindleDeviceBooksCard class="animate-fade-in-up stagger-2" />
    </div>
  </div>
</template>
