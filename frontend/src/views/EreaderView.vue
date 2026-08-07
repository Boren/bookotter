<script setup lang="ts">
import { onMounted, watch } from 'vue'
import EreaderDeviceBooksCard from '@/components/ereader/EreaderDeviceBooksCard.vue'
import EreaderDeviceCard from '@/components/ereader/EreaderDeviceCard.vue'
import EreaderQueueCard from '@/components/ereader/EreaderQueueCard.vue'
import EreaderSyncCard from '@/components/ereader/EreaderSyncCard.vue'
import { useEreadersStore } from '@/stores/ereaders'
import { useSyncStore } from '@/stores/sync'

const ereadersStore = useEreadersStore()
const syncStore = useSyncStore()

onMounted(async () => {
  syncStore.fetchPipelineStats()
  await ereadersStore.fetchEreaders()
  if (ereadersStore.selectedEreaderId) {
    ereadersStore.fetchStatus(ereadersStore.selectedEreaderId)
    ereadersStore.fetchDeviceBooks(ereadersStore.selectedEreaderId)
  }
})

// A completed sync means new files on the device — refresh the live listing
watch(
  () => syncStore.ereaderSyncing,
  (syncing, wasSyncing) => {
    if (wasSyncing && !syncing && ereadersStore.selectedEreaderId) {
      ereadersStore.fetchDeviceBooks(ereadersStore.selectedEreaderId)
    }
  }
)
</script>

<template>
  <div class="space-y-8">
    <div class="page-header">
      <h1 class="page-title">E-reader</h1>
      <p class="page-subtitle">Device status, delivery queue, and what's on your E-reader</p>
    </div>

    <div class="grid grid-cols-1 lg:grid-cols-2 gap-6">
      <div class="space-y-6">
        <EreaderDeviceCard class="animate-fade-in-up stagger-1" />
        <EreaderSyncCard class="animate-fade-in-up stagger-2" />
        <EreaderQueueCard class="animate-fade-in-up stagger-3" />
      </div>
      <EreaderDeviceBooksCard class="animate-fade-in-up stagger-2" />
    </div>
  </div>
</template>
