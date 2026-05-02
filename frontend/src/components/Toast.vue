<script setup lang="ts">
import { useToast } from '../composables/useToast'

const { toasts } = useToast()
</script>

<template>
  <div class="fixed bottom-4 right-4 z-50 flex flex-col gap-2">
    <Transition
      v-for="toast in toasts"
      :key="toast.id"
      enter-active-class="transition-all duration-300 ease-out"
      enter-from-class="opacity-0 translate-y-2"
      enter-to-class="opacity-100 translate-y-0"
      leave-active-class="transition-all duration-200 ease-in"
      leave-from-class="opacity-100 translate-y-0"
      leave-to-class="opacity-0 translate-y-2"
    >
      <div
        :data-testid="`toast-${toast.kind}`"
        :class="[
          'px-4 py-3 rounded-lg shadow-lg flex items-center gap-3 max-w-sm',
          toast.kind === 'success'
            ? 'bg-green-50 border border-green-200 text-green-900'
            : toast.kind === 'error'
              ? 'bg-red-50 border border-red-200 text-red-900'
              : 'bg-blue-50 border border-blue-200 text-blue-900'
        ]"
      >
        <svg
          v-if="toast.kind === 'success'"
          class="w-5 h-5 text-green-600 shrink-0"
          fill="none"
          stroke="currentColor"
          viewBox="0 0 24 24"
        >
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 13l4 4L19 7" />
        </svg>
        <svg
          v-else-if="toast.kind === 'error'"
          class="w-5 h-5 text-red-600 shrink-0"
          fill="none"
          stroke="currentColor"
          viewBox="0 0 24 24"
        >
          <path
            stroke-linecap="round"
            stroke-linejoin="round"
            stroke-width="2"
            d="M12 8v4m0 4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z"
          />
        </svg>
        <svg
          v-else
          class="w-5 h-5 text-blue-600 shrink-0"
          fill="none"
          stroke="currentColor"
          viewBox="0 0 24 24"
        >
          <path
            stroke-linecap="round"
            stroke-linejoin="round"
            stroke-width="2"
            d="M13 16h-1v-4h-1m1-4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z"
          />
        </svg>
        <p class="text-sm font-medium">{{ toast.message }}</p>
      </div>
    </Transition>
  </div>
</template>
