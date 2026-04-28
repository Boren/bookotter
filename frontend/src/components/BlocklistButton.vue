<script setup lang="ts">
import { ref } from 'vue';
import type { SearchResult } from '../types';
import { useBlocklistStore } from '../stores/blocklist';
import BlocklistConfirmModal from './BlocklistConfirmModal.vue';

const props = defineProps<{
  result: SearchResult;
}>();

const emit = defineEmits<{
  (e: 'blocklisted', result: SearchResult): void;
}>();

const blocklistStore = useBlocklistStore();
const showModal = ref(false);
const isBlocklisting = ref(false);

const handleConfirm = async (reason: string) => {
  isBlocklisting.value = true;
  try {
    await blocklistStore.add(props.result.indexer, props.result.guid, props.result.title, reason);
    emit('blocklisted', props.result);
  } catch (error) {
    console.error('Failed to blocklist:', error);
    // In a real app, we might want to show a toast notification here
  } finally {
    isBlocklisting.value = false;
  }
};
</script>

<template>
  <button
    @click="showModal = true"
    :disabled="isBlocklisting"
    class="btn btn-sm bg-stone-100 text-stone-600 hover:bg-error-50 hover:text-error-600 hover:border-error-200 transition-colors"
    title="Blocklist this release"
  >
    <svg v-if="isBlocklisting" class="w-3.5 h-3.5 animate-spin" fill="none" viewBox="0 0 24 24">
      <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="3"></circle>
      <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
    </svg>
    <svg v-else class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
      <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M18.364 18.364A9 9 0 005.636 5.636m12.728 12.728A9 9 0 015.636 5.636m12.728 12.728L5.636 5.636" />
    </svg>
  </button>

  <BlocklistConfirmModal
    v-model="showModal"
    :result="result"
    @confirm="handleConfirm"
  />
</template>
