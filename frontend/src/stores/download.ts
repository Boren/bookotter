import { defineStore } from 'pinia';
import { computed, ref } from 'vue';
import type { Download } from '../types';

export const useDownloadStore = defineStore('download', () => {
  // State
  const downloads = ref<Download[]>([]);
  const loading = ref(false);
  const error = ref<string | null>(null);
  const total = ref(0);

  // Error handling
  const clearError = () => {
    error.value = null;
  };

  // Actions
  const fetchDownloads = async (status?: string) => {
    loading.value = true;
    try {
      const params = new URLSearchParams();
      if (status) params.set('status', status);
      params.set('limit', '100');
      const response = await fetch(`/api/downloads?${params}`);
      if (!response.ok) throw new Error('Failed to fetch downloads');
      const data = await response.json();
      downloads.value = data.downloads;
      total.value = data.total;
    } catch (e) {
      error.value = e instanceof Error ? e.message : 'Failed to fetch downloads';
    } finally {
      loading.value = false;
    }
  };

  const cancelDownload = async (downloadId: number) => {
    try {
      const response = await fetch(`/api/downloads/${downloadId}`, { method: 'DELETE' });
      if (!response.ok) throw new Error('Failed to cancel download');
      await fetchDownloads();
    } catch (e) {
      error.value = e instanceof Error ? e.message : 'Failed to cancel download';
    }
  };

  // Computed
  const activeDownloads = computed(() =>
    downloads.value.filter((d) => d.status === 'queued' || d.status === 'downloading'),
  );

  const completedDownloads = computed(() =>
    downloads.value.filter((d) => d.status === 'completed' || d.status === 'imported'),
  );

  const failedDownloads = computed(() => downloads.value.filter((d) => d.status === 'failed'));

  const isDownloading = computed(() => downloads.value.some((d) => d.status === 'downloading'));

  const queueLength = computed(() => activeDownloads.value.length);

  const isQueueEmpty = computed(() => downloads.value.length === 0);

  return {
    // State
    downloads,
    loading,
    error,
    total,

    // Computed
    activeDownloads,
    completedDownloads,
    failedDownloads,
    isDownloading,
    queueLength,
    isQueueEmpty,

    // Actions
    fetchDownloads,
    cancelDownload,
    clearError,
  };
});
