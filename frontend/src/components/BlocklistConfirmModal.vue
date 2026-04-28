<script setup lang="ts">
import { ref } from 'vue';
import type { SearchResult } from '../types';

const props = defineProps<{
  result: SearchResult;
  modelValue: boolean;
}>();

const emit = defineEmits<{
  (e: 'update:modelValue', value: boolean): void;
  (e: 'confirm', reason: string): void;
}>();

const reason = ref('');

const close = () => {
  emit('update:modelValue', false);
  reason.value = '';
};

const confirm = () => {
  emit('confirm', reason.value);
  close();
};
</script>

<template>
  <Teleport to="body">
    <div v-if="modelValue" class="modal-overlay" @click="close">
      <div class="modal-content max-w-md" @click.stop>
        <div class="flex justify-between items-start mb-4">
          <h3 class="text-lg font-semibold text-stone-900">Blocklist Release</h3>
          <button @click="close" class="text-stone-400 hover:text-stone-600 transition-colors">
            <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12" />
            </svg>
          </button>
        </div>

        <div class="mb-6">
          <p class="text-stone-600 mb-4">
            Are you sure you want to blocklist this release? It will be permanently rejected in future searches.
          </p>
          
          <div class="bg-stone-50 p-3 rounded-md border border-stone-200 mb-4">
            <p class="font-medium text-stone-900 truncate" :title="result.title">{{ result.title }}</p>
            <p class="text-sm text-stone-500 mt-1">{{ result.indexer }}</p>
          </div>

          <div class="space-y-1">
            <label for="reason" class="label">Reason (Optional)</label>
            <input
              id="reason"
              v-model="reason"
              type="text"
              class="input"
              placeholder="e.g., Wrong language, bad quality..."
              @keyup.enter="confirm"
            />
          </div>
        </div>

        <div class="flex justify-end gap-3">
          <button @click="close" class="btn btn-secondary">Cancel</button>
          <button @click="confirm" class="btn btn-primary bg-error-600 hover:bg-error-700 border-error-600 hover:border-error-700 text-white">
            Blocklist
          </button>
        </div>
      </div>
    </div>
  </Teleport>
</template>
