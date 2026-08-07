<script setup lang="ts">
import { ref, watch } from 'vue';
import type { Book, HardcoverSearchResult, MatchProposal } from '@/types';
import { useScannerStore } from '../stores/scanner';
import { useToast } from '../composables/useToast';

const props = defineProps<{
  proposal: MatchProposal | null;
  modelValue: boolean;
}>();

const emit = defineEmits<{
  (e: 'update:modelValue', value: boolean): void;
  (e: 'linked'): void;
}>();

const store = useScannerStore();
const toast = useToast();

const activeTab = ref<'library' | 'hardcover'>('library');
const query = ref('');
const isSearching = ref(false);
const isLinking = ref(false);
const searchError = ref<string | null>(null);
const libraryResults = ref<Book[]>([]);
const hardcoverResults = ref<HardcoverSearchResult[]>([]);
const hasSearched = ref(false);

const suggestQuery = (relativePath: string): string => {
  const base = (relativePath.split('/').pop() ?? relativePath).replace(/\.epub$/i, '');
  const parts = base.split(' - ').map((p) => p.trim()).filter(Boolean);
  if (parts.length >= 2) {
    // Files are typically "Author - [Series #N -] Title"; search by title + author.
    return `${parts[parts.length - 1]} ${parts[0]}`.replace(/#[\d.]+/g, '').trim();
  }
  return base;
};

watch(
  () => props.modelValue,
  (open) => {
    if (open && props.proposal) {
      query.value = suggestQuery(props.proposal.relative_path);
      libraryResults.value = [];
      hardcoverResults.value = [];
      hasSearched.value = false;
      searchError.value = null;
      activeTab.value = 'library';
      search();
    }
  }
);

const close = () => emit('update:modelValue', false);

const search = async () => {
  if (!query.value.trim()) return;
  isSearching.value = true;
  searchError.value = null;
  try {
    if (activeTab.value === 'library') {
      libraryResults.value = await store.searchLibrary(query.value.trim());
    } else {
      hardcoverResults.value = await store.searchHardcover(query.value.trim());
    }
    hasSearched.value = true;
  } catch (e) {
    searchError.value = e instanceof Error ? e.message : 'Search failed';
  } finally {
    isSearching.value = false;
  }
};

const switchTab = (tab: 'library' | 'hardcover') => {
  if (activeTab.value === tab) return;
  activeTab.value = tab;
  searchError.value = null;
  const results = tab === 'library' ? libraryResults.value : hardcoverResults.value;
  if (results.length === 0 && query.value.trim()) search();
};

const linkLibraryBook = async (book: Book) => {
  if (!props.proposal || isLinking.value) return;
  isLinking.value = true;
  try {
    await store.linkBook(props.proposal.id, book.id);
    toast.success(`Linked file to "${book.title}"`);
    emit('linked');
    close();
  } catch {
    // store surfaced the error banner already
  } finally {
    isLinking.value = false;
  }
};

const linkHardcoverBook = async (result: HardcoverSearchResult) => {
  if (!props.proposal || isLinking.value) return;
  isLinking.value = true;
  try {
    await store.linkHardcover(props.proposal.id, result.hardcover_id);
    toast.success(`Added "${result.title}" to library`);
    emit('linked');
    close();
  } catch {
    // store surfaced the error banner already
  } finally {
    isLinking.value = false;
  }
};
</script>

<template>
  <Teleport to="body">
    <div v-if="modelValue && proposal" class="modal-overlay" @click="close">
      <div class="modal-content max-w-2xl" @click.stop>
        <div class="flex justify-between items-start mb-4">
          <div class="min-w-0">
            <h3 class="text-lg font-semibold text-stone-900">Match File</h3>
            <p class="text-sm text-stone-500 truncate" :title="proposal.relative_path">
              {{ proposal.relative_path }}
            </p>
          </div>
          <button @click="close" class="text-stone-400 hover:text-stone-600 transition-colors shrink-0 ml-3">
            <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12" />
            </svg>
          </button>
        </div>

        <!-- Tabs -->
        <div class="flex gap-1 mb-4 bg-stone-100 rounded-lg p-1">
          <button
            @click="switchTab('library')"
            :class="[
              'flex-1 py-1.5 px-3 rounded-md text-sm font-medium transition-colors',
              activeTab === 'library' ? 'bg-white text-stone-900 shadow-sm' : 'text-stone-500 hover:text-stone-700'
            ]"
          >
            Existing Book
          </button>
          <button
            @click="switchTab('hardcover')"
            :class="[
              'flex-1 py-1.5 px-3 rounded-md text-sm font-medium transition-colors',
              activeTab === 'hardcover' ? 'bg-white text-stone-900 shadow-sm' : 'text-stone-500 hover:text-stone-700'
            ]"
          >
            Search Hardcover
          </button>
        </div>

        <!-- Search Input -->
        <div class="flex gap-2 mb-4">
          <input
            v-model="query"
            type="text"
            class="input flex-1"
            placeholder="Search by title or author..."
            @keyup.enter="search"
          />
          <button @click="search" :disabled="isSearching || !query.trim()" class="btn btn-primary">
            <svg v-if="isSearching" class="animate-spin h-4 w-4" fill="none" viewBox="0 0 24 24">
              <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="3"></circle>
              <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
            </svg>
            <span v-else>Search</span>
          </button>
        </div>

        <div v-if="searchError" class="bg-error-50 border border-error-200 rounded-lg p-3 mb-4">
          <p class="text-sm text-error-700">{{ searchError }}</p>
        </div>

        <!-- Results -->
        <div class="max-h-80 overflow-y-auto space-y-2">
          <template v-if="activeTab === 'library'">
            <div
              v-for="book in libraryResults"
              :key="book.id"
              class="flex items-center justify-between gap-3 p-3 rounded-lg border border-stone-200 hover:border-ereader-300 transition-colors"
            >
              <div class="min-w-0">
                <p class="font-medium text-stone-900 truncate">{{ book.title }}</p>
                <p class="text-sm text-stone-500 truncate">
                  {{ book.author?.name || 'Unknown Author' }}
                  <span v-if="book.file_path" class="text-amber-600"> &middot; already has a file</span>
                </p>
              </div>
              <button
                @click="linkLibraryBook(book)"
                :disabled="isLinking || !!book.file_path"
                class="btn btn-primary py-1.5 px-3 text-xs shrink-0"
                :title="book.file_path ? 'This book is already linked to a file' : ''"
              >
                Link
              </button>
            </div>
            <div v-if="hasSearched && !isSearching && libraryResults.length === 0" class="text-center py-8 text-sm text-stone-500">
              No matching books in your library. Try the Hardcover tab to add it as a new book.
            </div>
          </template>

          <template v-else>
            <div
              v-for="result in hardcoverResults"
              :key="result.hardcover_id"
              class="flex items-center justify-between gap-3 p-3 rounded-lg border border-stone-200 hover:border-ereader-300 transition-colors"
            >
              <div class="min-w-0">
                <p class="font-medium text-stone-900 truncate">{{ result.title }}</p>
                <p class="text-sm text-stone-500 truncate">{{ result.author_names.join(', ') || 'Unknown Author' }}</p>
              </div>
              <button
                @click="linkHardcoverBook(result)"
                :disabled="isLinking"
                class="btn btn-primary py-1.5 px-3 text-xs shrink-0"
              >
                Add &amp; Link
              </button>
            </div>
            <div v-if="hasSearched && !isSearching && hardcoverResults.length === 0" class="text-center py-8 text-sm text-stone-500">
              No results on Hardcover for this query.
            </div>
          </template>
        </div>
      </div>
    </div>
  </Teleport>
</template>
