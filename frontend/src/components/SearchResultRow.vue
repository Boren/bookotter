<script setup lang="ts">
import type { SearchResult } from '../types'
import RejectionsPopover from './RejectionsPopover.vue'
import BlocklistButton from './BlocklistButton.vue'

const props = defineProps<{
  result: SearchResult
  isGrabbing: boolean
}>()

const emit = defineEmits<{
  (e: 'grab', result: SearchResult): void
  (e: 'blocklisted', result: SearchResult): void
}>()

const formatSize = (bytes: number) => {
  if (bytes >= 1_073_741_824) {
    return `${(bytes / 1_073_741_824).toFixed(1)} GB`
  }
  if (bytes >= 1_048_576) {
    return `${(bytes / 1_048_576).toFixed(1)} MB`
  }
  if (bytes >= 1024) {
    return `${(bytes / 1024).toFixed(0)} KB`
  }
  return `${bytes} B`
}

const formatAge = (days: number) => {
  if (days === 0) return 'Today'
  return `${days} ${days === 1 ? 'day' : 'days'}`
}
</script>

<template>
  <tr class="table-row hover:bg-stone-50/50 transition-colors">
    <!-- Age -->
    <td class="table-cell whitespace-nowrap text-stone-600">
      {{ formatAge(result.age_days) }}
    </td>
    
    <!-- Title -->
    <td class="table-cell max-w-md">
      <p class="font-medium text-stone-900 truncate" :title="result.title">
        {{ result.title }}
      </p>
    </td>
    
    <!-- Indexer -->
    <td class="table-cell">
      <span class="badge badge-neutral">{{ result.indexer }}</span>
    </td>
    
    <!-- Size -->
    <td class="table-cell text-right text-stone-600 tabular-nums whitespace-nowrap">
      {{ formatSize(result.size) }}
    </td>
    
    <!-- Peers -->
    <td class="table-cell text-right tabular-nums whitespace-nowrap">
      <template v-if="result.seeders !== undefined && result.leechers !== undefined">
        <span class="text-success-600">{{ result.seeders }}</span>
        <span class="text-stone-400 mx-1">/</span>
        <span class="text-error-600">{{ result.leechers }}</span>
      </template>
      <span v-else class="text-stone-400">—</span>
    </td>
    
    <!-- Rejections -->
    <td class="table-cell text-center">
      <div class="flex justify-center">
        <template v-if="result.approved">
          <svg class="w-5 h-5 text-success-500" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 13l4 4L19 7"/>
          </svg>
        </template>
        <template v-else-if="result.rejections && result.rejections.length > 0">
          <RejectionsPopover :rejections="result.rejections">
            <div class="cursor-help p-1 rounded hover:bg-error-50 text-error-500 transition-colors">
              <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z"/>
              </svg>
            </div>
          </RejectionsPopover>
        </template>
      </div>
    </td>
    
    <!-- Action -->
    <td class="table-cell text-right">
      <div class="flex justify-end gap-2">
        <BlocklistButton :result="result" @blocklisted="emit('blocklisted', result)" />
        <button
          @click="emit('grab', result)"
          :disabled="isGrabbing || !result.approved"
          class="btn btn-sm"
          :class="result.approved ? 'btn-primary' : 'bg-stone-100 text-stone-400 cursor-not-allowed'"
        >
          <svg v-if="isGrabbing" class="w-3.5 h-3.5 animate-spin" fill="none" viewBox="0 0 24 24">
            <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="3"></circle>
            <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
          </svg>
          <svg v-else class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-4l-4 4m0 0l-4-4m4 4V4"/>
          </svg>
          {{ isGrabbing ? 'Grabbing...' : 'Grab' }}
        </button>
      </div>
    </td>
  </tr>
</template>