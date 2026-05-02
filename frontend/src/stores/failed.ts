import { defineStore } from 'pinia';
import { ref } from 'vue';
import type { Book } from '../types';

export const useFailedStore = defineStore('failed', () => {
  const permanent_failed = ref<Book[]>([]);
  const recent_failures = ref<Book[]>([]);
  const counts = ref({ permanent_failed: 0, recent_failures: 0 });
  const loading = ref(false);
  const error = ref<string | null>(null);

  async function fetchFailed() {
    loading.value = true;
    error.value = null;
    try {
      const response = await fetch('/api/library/dlq');
      if (!response.ok) {
        throw new Error('Failed to fetch failed books');
      }
      const data = await response.json();
      permanent_failed.value = data.permanent_failed;
      recent_failures.value = data.recent_failures;
      counts.value = data.counts;
    } catch (e) {
      error.value = e instanceof Error ? e.message : 'Failed to fetch failed books';
    } finally {
      loading.value = false;
    }
  }

  function handleBookEvent(
    event: 'book_status_changed' | 'book_force_retried',
    payload: { book_id: number; new_status?: string; book_status?: string }
  ) {
    if (event === 'book_status_changed') {
      if (!['failed', 'PERMANENT_FAILED'].includes(payload.new_status ?? '')) {
        permanent_failed.value = permanent_failed.value.filter((b) => b.id !== payload.book_id);
        recent_failures.value = recent_failures.value.filter((b) => b.id !== payload.book_id);
      }
    } else if (event === 'book_force_retried') {
      permanent_failed.value = permanent_failed.value.filter((b) => b.id !== payload.book_id);
      recent_failures.value = recent_failures.value.filter((b) => b.id !== payload.book_id);
    }
  }

  return {
    permanent_failed,
    recent_failures,
    counts,
    loading,
    error,
    fetchFailed,
    handleBookEvent,
  };
});
