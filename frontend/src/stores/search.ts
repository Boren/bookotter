import { defineStore } from 'pinia';
import { computed, ref } from 'vue';
import type { Book } from '../types';

export const useSearchStore = defineStore('search', () => {
  // State
  const query = ref('');
  const results = ref<Book[]>([]);
  const isSearching = ref(false);
  const error = ref<string | null>(null);
  const searchHistory = ref<string[]>([]);

  // Error handling
  const clearError = () => {
    error.value = null;
  };

  // Actions
  const search = async (searchQuery: string) => {
    // TODO: Implement search - search across library and hardcover
    console.log('TODO: search', searchQuery);
  };

  const clearSearch = () => {
    // TODO: Implement clearSearch - clear results and query
    console.log('TODO: clearSearch');
  };

  const addToHistory = (searchQuery: string) => {
    // TODO: Implement addToHistory - add query to search history
    console.log('TODO: addToHistory', searchQuery);
  };

  const clearHistory = () => {
    // TODO: Implement clearHistory - clear search history
    console.log('TODO: clearHistory');
  };

  const searchHardcover = async (searchQuery: string) => {
    // TODO: Implement searchHardcover - search hardcover API
    console.log('TODO: searchHardcover', searchQuery);
  };

  const searchReadarr = async (searchQuery: string) => {
    // TODO: Implement searchReadarr - search readarr library
    console.log('TODO: searchReadarr', searchQuery);
  };

  // Computed
  const resultCount = computed(() => results.value.length);

  const hasResults = computed(() => results.value.length > 0);

  const isQueryEmpty = computed(() => query.value.trim().length === 0);

  return {
    // State
    query,
    results,
    isSearching,
    error,
    searchHistory,

    // Computed
    resultCount,
    hasResults,
    isQueryEmpty,

    // Actions
    search,
    clearSearch,
    addToHistory,
    clearHistory,
    searchHardcover,
    searchReadarr,
    clearError,
  };
});
