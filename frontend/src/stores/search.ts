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

  const previewResults = ref<Record<number, SearchResult[]>>({});
  const previewLoading = ref<Record<number, boolean>>({});
  const previewErrors = ref<Record<number, string | null>>({});
  const autoSearching = ref<Record<number, boolean>>({});
  const autoSearchMessage = ref<{ type: 'success' | 'error'; text: string } | null>(null);

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

  const previewForBook = async (bookId: number) => {
    previewLoading.value[bookId] = true;
    previewErrors.value[bookId] = null;
    try {
      const response = await fetch(`/api/search/preview/${bookId}`, { method: 'POST' });
      if (!response.ok) {
        const data = await response.json().catch(() => ({ detail: 'Preview failed' }));
        throw new Error(data.detail || `Preview failed (${response.status})`);
      }
      const data = await response.json();
      previewResults.value[bookId] = data.results || [];
    } catch (e) {
      previewErrors.value[bookId] = e instanceof Error ? e.message : 'Preview failed';
      previewResults.value[bookId] = [];
    } finally {
      previewLoading.value[bookId] = false;
    }
  };

  const clearPreviewForBook = (bookId: number) => {
    delete previewResults.value[bookId];
    delete previewLoading.value[bookId];
    delete previewErrors.value[bookId];
  };

  const autoSearchForBook = async (bookId: number) => {
    autoSearching.value[bookId] = true;
    autoSearchMessage.value = null;
    try {
      const response = await fetch(`/api/search/auto/${bookId}`, { method: 'POST' });
      if (!response.ok) {
        const data = await response.json().catch(() => ({ detail: 'Auto-search failed' }));
        throw new Error(data.detail || `Auto-search failed (${response.status})`);
      }
      const data = await response.json();
      if (data.success) {
        const truncated =
          data.result_title && data.result_title.length > 60
            ? `${data.result_title.substring(0, 60)}...`
            : data.result_title;
        autoSearchMessage.value = {
          type: 'success',
          text: truncated ? `Grabbed "${truncated}" — download queued` : 'Download queued',
        };
      } else {
        autoSearchMessage.value = {
          type: 'error',
          text: data.message || 'No results found',
        };
      }
      return data;
    } catch (e) {
      autoSearchMessage.value = {
        type: 'error',
        text: e instanceof Error ? e.message : 'Auto-search failed',
      };
      return null;
    } finally {
      autoSearching.value[bookId] = false;
    }
  };

  const clearAutoSearchMessage = () => {
    autoSearchMessage.value = null;
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
    previewResults,
    previewLoading,
    previewErrors,
    autoSearching,
    autoSearchMessage,

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
    previewForBook,
    clearPreviewForBook,
    autoSearchForBook,
    clearAutoSearchMessage,
  };
});
