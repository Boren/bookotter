import { defineStore } from 'pinia';
import { computed, ref } from 'vue';
import type { SearchResult } from '../types';

export const useSearchStore = defineStore('search', () => {
  // State
  const query = ref('');
  const author = ref('');
  const results = ref<SearchResult[]>([]);
  const isSearching = ref(false);
  const error = ref<string | null>(null);
  const grabbingIds = ref<Record<string, boolean>>({});
  const grabMessage = ref<{ type: 'success' | 'error'; text: string } | null>(null);

  // Error handling
  const clearError = () => {
    error.value = null;
  };

  const clearGrabMessage = () => {
    grabMessage.value = null;
  };

  // Actions
  const search = async (searchQuery: string, searchAuthor: string = '') => {
    if (!searchQuery.trim()) return;

    isSearching.value = true;
    error.value = null;
    grabMessage.value = null;
    query.value = searchQuery;
    author.value = searchAuthor;

    try {
      const params = new URLSearchParams({ query: searchQuery });
      if (searchAuthor.trim()) {
        params.set('author', searchAuthor);
      }
      const response = await fetch(`/api/search?${params}`);
      if (!response.ok) {
        const data = await response.json().catch(() => ({ detail: 'Search failed' }));
        throw new Error(data.detail || `Search failed (${response.status})`);
      }
      const data = await response.json();
      results.value = data.results || [];
    } catch (e) {
      error.value = e instanceof Error ? e.message : 'Search failed';
      results.value = [];
    } finally {
      isSearching.value = false;
    }
  };

  const grabRelease = async (bookId: number, result: SearchResult) => {
    const key = result.guid;
    grabbingIds.value[key] = true;
    grabMessage.value = null;

    try {
      const response = await fetch('/api/search/grab', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          book_id: bookId,
          result: {
            guid: result.guid,
            indexer_id: result.indexer_id,
            indexer: result.indexer,
            title: result.title,
            size: result.size,
            seeders: result.seeders,
            leechers: result.leechers,
            download_url: result.download_url,
            magnet_url: result.magnet_url,
            categories: result.categories,
            publish_date: result.publish_date,
          },
        }),
      });

      if (!response.ok) {
        const data = await response.json().catch(() => ({ detail: 'Grab failed' }));
        throw new Error(data.detail || `Grab failed (${response.status})`);
      }

      const truncatedTitle =
        result.title.length > 60 ? `${result.title.substring(0, 60)}...` : result.title;
      grabMessage.value = {
        type: 'success',
        text: `Grabbed "${truncatedTitle}" — download queued`,
      };
    } catch (e) {
      grabMessage.value = {
        type: 'error',
        text: e instanceof Error ? e.message : 'Grab failed',
      };
    } finally {
      delete grabbingIds.value[key];
    }
  };

  const clearSearch = () => {
    query.value = '';
    author.value = '';
    results.value = [];
    error.value = null;
    grabMessage.value = null;
  };

  // Computed
  const resultCount = computed(() => results.value.length);

  const hasResults = computed(() => results.value.length > 0);

  const isQueryEmpty = computed(() => query.value.trim().length === 0);

  return {
    // State
    query,
    author,
    results,
    isSearching,
    error,
    grabbingIds,
    grabMessage,

    // Computed
    resultCount,
    hasResults,
    isQueryEmpty,

    // Actions
    search,
    grabRelease,
    clearSearch,
    clearError,
    clearGrabMessage,
  };
});
