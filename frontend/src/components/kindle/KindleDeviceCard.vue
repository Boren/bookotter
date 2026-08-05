<script setup lang="ts">
import { computed, ref } from 'vue'
import { useKindlesStore } from '@/stores/kindles'
import { formatRelativeTime } from '@/utils/format'

const kindlesStore = useKindlesStore()
const isTesting = ref(false)

const status = computed(() => kindlesStore.selectedStatus)

const statusDot = computed(() => {
  if (!status.value) return { class: 'bg-stone-300', label: 'Checking…' }
  if (!status.value.configured) return { class: 'bg-stone-400', label: 'Not configured' }
  return status.value.reachable
    ? { class: 'bg-success-500', label: 'Online' }
    : { class: 'bg-error-500', label: 'Offline' }
})

const refreshStatus = () => {
  if (kindlesStore.selectedKindleId) {
    kindlesStore.fetchStatus(kindlesStore.selectedKindleId, true)
  }
}

const onDeviceChange = () => {
  if (kindlesStore.selectedKindleId) {
    kindlesStore.fetchStatus(kindlesStore.selectedKindleId)
    kindlesStore.fetchDeviceBooks(kindlesStore.selectedKindleId)
  }
}

const testConnection = async () => {
  if (!kindlesStore.selectedKindleId) return
  isTesting.value = true
  try {
    await kindlesStore.testConnection(kindlesStore.selectedKindleId)
  } finally {
    isTesting.value = false
  }
}
</script>

<template>
  <div class="card" data-testid="kindle-device-card">
    <div class="flex items-center justify-between mb-4">
      <h2 class="text-lg font-display font-semibold text-stone-900">Device</h2>
      <select
        v-if="kindlesStore.kindles.length > 1"
        v-model="kindlesStore.selectedKindleId"
        class="input text-sm py-1.5 w-auto"
        data-testid="kindle-device-select"
        @change="onDeviceChange"
      >
        <option v-for="k in kindlesStore.kindles" :key="k.id" :value="k.id">{{ k.name }}</option>
      </select>
    </div>

    <div v-if="!kindlesStore.selectedKindle" class="empty-state py-8">
      <p class="text-sm text-stone-500">
        No Kindle configured yet — add one in
        <RouterLink to="/settings" class="text-kindle-600 hover:underline">Settings</RouterLink>.
      </p>
    </div>

    <div v-else class="space-y-4">
      <div class="flex items-center gap-3">
        <span
          class="w-3 h-3 rounded-full shrink-0"
          :class="[statusDot.class, kindlesStore.statusLoading ? 'animate-pulse' : '']"
          data-testid="kindle-status-dot"
        ></span>
        <div class="min-w-0">
          <p class="text-sm font-medium text-stone-900">
            {{ kindlesStore.selectedKindle.name }}
            <span class="font-normal text-stone-500">— {{ statusDot.label }}</span>
          </p>
          <p class="text-xs text-stone-500 truncate">
            {{ kindlesStore.selectedKindle.hostname || 'no hostname' }}
            <template v-if="status?.checked_at"> · checked {{ formatRelativeTime(status.checked_at) }}</template>
          </p>
        </div>
      </div>

      <div class="flex flex-wrap gap-2">
        <button class="btn btn-secondary btn-sm" :disabled="kindlesStore.statusLoading" @click="refreshStatus">
          Refresh
        </button>
        <button
          class="btn btn-secondary btn-sm"
          :disabled="isTesting"
          data-testid="kindle-test-connection"
          @click="testConnection"
        >
          <svg v-if="isTesting" class="w-4 h-4 animate-spin" fill="none" viewBox="0 0 24 24">
            <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="3"></circle>
            <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"></path>
          </svg>
          {{ isTesting ? 'Testing…' : 'Test Connection' }}
        </button>
      </div>
    </div>
  </div>
</template>
