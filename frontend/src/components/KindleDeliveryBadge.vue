<script setup lang="ts">
import { computed } from 'vue'
import type { KindleDeliveryStatus } from '@/types'

const props = defineProps<{
  status: KindleDeliveryStatus | string | null
  compact?: boolean
}>()

const badgeConfig = computed(() => {
  switch (props.status) {
    case 'PENDING':
      return {
        label: 'Waiting for Kindle',
        colorClass: 'bg-kindle-100 text-kindle-800 border-kindle-200',
        dotClass: 'bg-kindle-500',
        showDot: true,
        animateDot: true
      }
    case 'IN_PROGRESS':
      return {
        label: 'Sending…',
        colorClass: 'bg-blue-100 text-blue-800 border-blue-200',
        dotClass: 'bg-blue-500',
        showDot: true,
        animateDot: true
      }
    case 'DELIVERED':
      return {
        label: 'On Kindle',
        colorClass: 'bg-success-100 text-success-800 border-success-200',
        dotClass: 'bg-success-500',
        showDot: false,
        animateDot: false
      }
    case 'SKIPPED':
      return {
        label: 'Delivery skipped',
        colorClass: 'bg-amber-100 text-amber-800 border-amber-200',
        dotClass: 'bg-amber-500',
        showDot: false,
        animateDot: false
      }
    default:
      return null
  }
})

// The compact corner dot only flags states that need attention; a "delivered"
// dot on every library card would be noise.
const showCompact = computed(
  () => props.status === 'PENDING' || props.status === 'IN_PROGRESS' || props.status === 'SKIPPED'
)
</script>

<template>
  <span
    v-if="compact && badgeConfig && showCompact"
    :title="badgeConfig.label"
    data-testid="kindle-delivery-dot"
    class="flex items-center justify-center w-6 h-6 rounded-full border shadow-warm-sm bg-white"
    :class="badgeConfig.colorClass"
  >
    <span
      class="w-2 h-2 rounded-full"
      :class="[badgeConfig.dotClass, badgeConfig.animateDot ? 'animate-pulse' : '']"
    ></span>
  </span>
  <span
    v-else-if="!compact && badgeConfig"
    class="inline-flex items-center gap-1.5 px-2 py-0.5 rounded-full text-xs font-medium border"
    :class="badgeConfig.colorClass"
    data-testid="kindle-delivery-badge"
  >
    <span
      v-if="badgeConfig.showDot"
      class="w-1.5 h-1.5 rounded-full"
      :class="[badgeConfig.dotClass, badgeConfig.animateDot ? 'animate-pulse' : '']"
    ></span>
    {{ badgeConfig.label }}
  </span>
</template>
