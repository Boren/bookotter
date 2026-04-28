import { defineStore } from 'pinia';
import { computed, ref } from 'vue';
import type { Book } from '@/types';

export const useWantedStore = defineStore('wanted', () => {
  const books = ref<Book[]>([]);
  const isLoading = ref(false);
  const isSearchingAll = ref(false);
  const error = ref<string | null>(null);
  const searchAllResult = ref<{ triggered: number } | null>(null);

  const fetchMissing = async () => {
    isLoading.value = true;
    error.value = null;
    try {
      const response = await fetch('/api/wanted/missing');
      if (!response.ok) throw new Error('Failed to fetch missing books');
      const data = await response.json();
      books.value = data.books || [];
    } catch (e) {
      error.value = e instanceof Error ? e.message : 'Failed to fetch';
    } finally {
      isLoading.value = false;
    }
  };

  const searchAll = async () => {
    isSearchingAll.value = true;
    error.value = null;
    try {
      const response = await fetch('/api/wanted/search-all', { method: 'POST' });
      if (!response.ok) throw new Error('Search all failed');
      const data = await response.json();
      searchAllResult.value = data;
      await fetchMissing();
    } catch (e) {
      error.value = e instanceof Error ? e.message : 'Search all failed';
    } finally {
      isSearchingAll.value = false;
    }
  };

  const missingCount = computed(() => books.value.length);

  return {
    books,
    isLoading,
    isSearchingAll,
    error,
    searchAllResult,
    missingCount,
    fetchMissing,
    searchAll,
  };
});
