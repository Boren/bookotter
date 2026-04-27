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

  const handleWebSocketMessage = (message: { event: string; data: unknown }) => {
    if (message.event === 'download_started') {
      // Refresh downloads list when a new download starts
      fetchDownloads();
    } else if (message.event === 'download_progress') {
      // Update progress for a specific download
      const data = message.data as {
        download_id?: number;
        progress?: number;
        download_speed?: number;
        eta?: number;
      };
      if (data.download_id) {
        const idx = downloads.value.findIndex((d) => d.id === data.download_id);
        if (idx !== -1) {
          downloads.value[idx] = {
            ...downloads.value[idx],
            progress: data.progress ?? downloads.value[idx].progress,
            download_speed: data.download_speed ?? downloads.value[idx].download_speed,
            eta: data.eta ?? downloads.value[idx].eta,
          };
        }
      }
    } else if (message.event === 'download_completed' || message.event === 'import_completed') {
      // Refresh downloads list when a download completes or import finishes
      fetchDownloads();
    }
  };

  // Computed
  const activeDownloads = computed(() =>
    downloads.value.filter((d) => d.status === 'queued' || d.status === 'downloading')
  );

  const completedDownloads = computed(() =>
    downloads.value.filter((d) => d.status === 'completed' || d.status === 'imported')
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
    handleWebSocketMessage,
  };
});
