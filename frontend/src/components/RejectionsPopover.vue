<script setup lang="ts">
import { ref } from 'vue'

defineProps<{
  rejections: string[]
}>()

const show = ref(false)
</script>

<template>
  <div class="relative inline-flex items-center" @mouseenter="show = true" @mouseleave="show = false">
    <slot></slot>
    
    <Transition
      enter-active-class="transition ease-out duration-200"
      enter-from-class="opacity-0 translate-y-1"
      enter-to-class="opacity-100 translate-y-0"
      leave-active-class="transition ease-in duration-150"
      leave-from-class="opacity-100 translate-y-0"
      leave-to-class="opacity-0 translate-y-1"
    >
      <div
        v-if="show && rejections.length > 0"
        class="absolute bottom-full left-1/2 -translate-x-1/2 mb-2 w-64 z-50"
      >
        <div class="bg-stone-900 text-white text-sm rounded-lg shadow-xl p-3">
          <div class="font-medium mb-1.5 text-stone-200">Rejections</div>
          <ul class="space-y-1">
            <li v-for="(rejection, idx) in rejections" :key="idx" class="flex items-start gap-2">
              <svg class="w-4 h-4 text-error-400 shrink-0 mt-0.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"/>
              </svg>
              <span class="text-stone-300 leading-tight">{{ rejection }}</span>
            </li>
          </ul>
          <!-- Arrow -->
          <div class="absolute -bottom-1 left-1/2 -translate-x-1/2 w-2 h-2 bg-stone-900 rotate-45"></div>
        </div>
      </div>
    </Transition>
  </div>
</template>