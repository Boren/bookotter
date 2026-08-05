<script setup lang="ts">
import { computed, ref, watch } from 'vue';
import type { RenameApplyResult, RenamePreviewItem } from '@/types';
import { useLibraryStore } from '../stores/library';
import { useToast } from '../composables/useToast';

const props = defineProps<{
  modelValue: boolean;
}>();

const emit = defineEmits<{
  (e: 'update:modelValue', value: boolean): void;
}>();

const store = useLibraryStore();
const toast = useToast();

const isLoading = ref(false);
const isApplying = ref(false);
const loadError = ref<string | null>(null);
const items = ref<RenamePreviewItem[]>([]);
const showUnchanged = ref(false);
const applyResult = ref<RenameApplyResult | null>(null);

const changedItems = computed(() => items.value.filter((i) => i.changed && !i.error));
const unchangedItems = computed(() => items.value.filter((i) => !i.changed && !i.error));
const errorItems = computed(() => items.value.filter((i) => i.error));
const failedResults = computed(() => applyResult.value?.items.filter((i) => i.status === 'failed') ?? []);

const loadPreview = async () => {
  isLoading.value = true;
  loadError.value = null;
  applyResult.value = null;
  items.value = [];
  try {
    const result = await store.fetchRenamePreview();
    items.value = result.items;
  } catch (e) {
    loadError.value = e instanceof Error ? e.message : 'Failed to load rename preview';
  } finally {
    isLoading.value = false;
  }
};

watch(
  () => props.modelValue,
  (open) => {
    if (open) {
      showUnchanged.value = false;
      loadPreview();
    }
  }
);

const close = () => emit('update:modelValue', false);

const apply = async () => {
  if (isApplying.value || changedItems.value.length === 0) return;
  isApplying.value = true;
  loadError.value = null;
  try {
    const result = await store.applyRename();
    applyResult.value = result;
    if (result.failed === 0) {
      toast.success(`Renamed ${result.renamed} file${result.renamed === 1 ? '' : 's'}`);
    } else {
      toast.error(`Renamed ${result.renamed}, ${result.failed} failed`);
    }
    items.value = [];
  } catch (e) {
    loadError.value = e instanceof Error ? e.message : 'Rename failed';
  } finally {
    isApplying.value = false;
  }
};
</script>

<template>
  <Teleport to="body">
    <div v-if="modelValue" class="modal-overlay" @click="close">
      <div class="modal-content max-w-3xl" @click.stop>
        <div class="flex justify-between items-start mb-4">
          <div>
            <h3 class="text-lg font-semibold text-stone-900">Rename Library Files</h3>
            <p class="text-sm text-stone-500">
              Preview of every file rename the current naming template would make.
            </p>
          </div>
          <button @click="close" class="text-stone-400 hover:text-stone-600 transition-colors shrink-0 ml-3">
            <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12" />
            </svg>
          </button>
        </div>

        <div v-if="loadError" class="bg-error-50 border border-error-200 rounded-lg p-3 mb-4">
          <p class="text-sm text-error-700">{{ loadError }}</p>
        </div>

        <div v-if="isLoading" class="text-center py-10 text-sm text-stone-500">Loading preview...</div>

        <!-- Apply results -->
        <div v-else-if="applyResult" class="space-y-4">
          <p class="text-sm text-stone-700">
            Renamed <span class="font-semibold">{{ applyResult.renamed }}</span> of
            {{ applyResult.total }} files
            <span v-if="applyResult.failed > 0" class="text-error-600">
              — {{ applyResult.failed }} failed</span
            >.
          </p>
          <div v-if="failedResults.length > 0" class="max-h-60 overflow-y-auto space-y-2">
            <div
              v-for="item in failedResults"
              :key="item.book_id"
              class="p-3 rounded-lg border border-error-200 bg-error-50"
            >
              <p class="text-sm font-medium text-stone-900 truncate">{{ item.title }}</p>
              <p class="text-xs text-error-700">{{ item.error }}</p>
            </div>
          </div>
          <div class="flex justify-end">
            <button @click="close" class="btn btn-primary">Done</button>
          </div>
        </div>

        <!-- Preview -->
        <div v-else class="space-y-4">
          <p class="text-sm text-stone-700">
            <span class="font-semibold">{{ changedItems.length }}</span> of {{ items.length }} files
            would be renamed.
            <span v-if="errorItems.length > 0" class="text-amber-600">
              {{ errorItems.length }} missing on disk (skipped).</span
            >
          </p>

          <div class="max-h-96 overflow-y-auto space-y-2">
            <div
              v-for="item in changedItems"
              :key="item.book_id"
              class="p-3 rounded-lg border border-stone-200"
            >
              <p class="text-xs text-stone-500 font-mono truncate line-through" :title="item.old_path">
                {{ item.old_path }}
              </p>
              <p class="text-sm text-stone-900 font-mono truncate" :title="item.new_path">
                {{ item.new_path }}
              </p>
            </div>
            <div
              v-if="!isLoading && changedItems.length === 0"
              class="text-center py-8 text-sm text-stone-500"
            >
              Everything already matches the naming template.
            </div>
          </div>

          <div v-if="unchangedItems.length > 0">
            <button
              @click="showUnchanged = !showUnchanged"
              class="text-sm text-stone-500 hover:text-stone-700 transition-colors"
            >
              {{ showUnchanged ? 'Hide' : 'Show' }} {{ unchangedItems.length }} unchanged files
            </button>
            <div v-if="showUnchanged" class="mt-2 max-h-40 overflow-y-auto space-y-1">
              <p
                v-for="item in unchangedItems"
                :key="item.book_id"
                class="text-xs text-stone-500 font-mono truncate px-3"
                :title="item.old_path"
              >
                {{ item.old_path }}
              </p>
            </div>
          </div>

          <div class="flex justify-end gap-2">
            <button @click="close" class="btn btn-secondary" :disabled="isApplying">Cancel</button>
            <button
              @click="apply"
              class="btn btn-primary"
              :disabled="isApplying || changedItems.length === 0"
            >
              {{ isApplying ? 'Renaming...' : `Rename ${changedItems.length} File${changedItems.length === 1 ? '' : 's'}` }}
            </button>
          </div>
        </div>
      </div>
    </div>
  </Teleport>
</template>
