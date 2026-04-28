<script setup lang="ts">
import { computed } from 'vue'
import type { BookStatus } from '@/types'

const props = defineProps<{
  status: BookStatus | string
  progress?: number
}>()

const badgeConfig = computed(() => {
  switch (props.status) {
    case 'missing':
      return {
        label: 'Missing',
        colorClass: 'bg-error-100 text-error-800 border-error-200',
        dotClass: 'bg-error-500',
        showDot: false,
        animateDot: false
      }
    case 'wanted':
      return {
        label: 'Wanted',
        colorClass: 'bg-amber-100 text-amber-800 border-amber-200',
        dotClass: 'bg-amber-500',
        showDot: false,
        animateDot: false
      }
    case 'searching':
      return {
        label: 'Searching…',
        colorClass: 'bg-blue-100 text-blue-800 border-blue-200',
        dotClass: 'bg-blue-500',
        showDot: true,
        animateDot: true
      }
    case 'grabbed':
      return {
        label: 'Grabbed',
        colorClass: 'bg-blue-100 text-blue-800 border-blue-200',
        dotClass: 'bg-blue-500',
        showDot: false,
        animateDot: false
      }
    case 'downloading':
      return {
        label: props.progress !== undefined ? `Downloading (${Math.round(props.progress)}%)` : 'Downloading',
        colorClass: 'bg-blue-100 text-blue-800 border-blue-200',
        dotClass: 'bg-blue-500',
        showDot: false,
        animateDot: false
      }
    case 'importing':
      return {
        label: 'Importing…',
        colorClass: 'bg-blue-100 text-blue-800 border-blue-200',
        dotClass: 'bg-blue-500',
        showDot: true,
        animateDot: true
      }
    case 'in_library':
      return {
        label: 'Downloaded',
        colorClass: 'bg-success-100 text-success-800 border-success-200',
        dotClass: 'bg-success-500',
        showDot: false,
        animateDot: false
      }
    case 'failed':
      return {
        label: 'Failed',
        colorClass: 'bg-error-100 text-error-800 border-error-200',
        dotClass: 'bg-error-500',
        showDot: false,
        animateDot: false
      }
    default:
      return {
        label: props.status,
        colorClass: 'bg-stone-100 text-stone-800 border-stone-200',
        dotClass: 'bg-stone-500',
        showDot: false,
        animateDot: false
      }
  }
})
</script>

<template>
  <span
    class="inline-flex items-center gap-1.5 px-2 py-0.5 rounded-full text-xs font-medium border"
    :class="badgeConfig.colorClass"
  >
    <span
      v-if="badgeConfig.showDot"
      class="w-1.5 h-1.5 rounded-full"
      :class="[badgeConfig.dotClass, badgeConfig.animateDot ? 'animate-pulse' : '']"
    ></span>
    {{ badgeConfig.label }}
  </span>
</template>
