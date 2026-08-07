import { defineStore } from 'pinia';
import { computed, ref } from 'vue';
import { useToast } from '../composables/useToast';
import type { Book, EreaderDeliveryProgress, EreaderSyncPreview, TransferProgress } from '../types';
import { useDownloadStore } from './download';
import { useFailedStore } from './failed';
import { useLibraryStore } from './library';
import { useRssStore } from './rss';
import { useScannerStore } from './scanner';

// Safety net: release the syncing state if the WebSocket completion event
// never arrives (e.g. connection dropped mid-sync).
const EREADER_SYNC_FALLBACK_MS = 15 * 60 * 1000;

export const useSyncStore = defineStore('sync', () => {
  const wsConnected = ref(false);
  const error = ref<string | null>(null);

  // Pipeline state
  const pipelineStats = ref<{
    total_books: number;
    by_status: Record<string, number>;
    by_ereader_delivery_status?: Record<string, number>;
    author_count: number;
    total_size_bytes: number;
  } | null>(null);
  const recentBooks = ref<Book[]>([]);
  const hardcoverSyncing = ref(false);
  const ereaderSyncing = ref(false);
  const ereaderSyncProgress = ref<TransferProgress | null>(null);
  const ereaderSyncInfo = ref<{ ereader_id: string; total_books: number } | null>(null);
  // Result of the last dry-run sync ("Preview" on the E-reader page)
  const ereaderSyncPreview = ref<EreaderSyncPreview | null>(null);
  // Per-book pipeline delivery ("Send to E-reader" on a book page)
  const ereaderDeliveryProgress = ref<EreaderDeliveryProgress | null>(null);
  let ereaderSyncTimeout: number | null = null;

  // Drives the sidebar "Syncing…" indicator
  const isRunning = computed(() => hardcoverSyncing.value || ereaderSyncing.value);

  const setError = (message: string) => {
    error.value = message;
    setTimeout(() => {
      if (error.value === message) {
        error.value = null;
      }
    }, 15000);
  };

  const clearError = () => {
    error.value = null;
  };

  // WebSocket connection
  let ws: WebSocket | null = null;
  let reconnectTimer: number | null = null;

  const connectWebSocket = () => {
    if (ws?.readyState === WebSocket.OPEN) return;

    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const wsUrl = `${protocol}//${window.location.host}/api/ws`;

    ws = new WebSocket(wsUrl);

    ws.onopen = () => {
      wsConnected.value = true;
    };

    ws.onclose = () => {
      wsConnected.value = false;
      if (reconnectTimer) clearTimeout(reconnectTimer);
      reconnectTimer = window.setTimeout(connectWebSocket, 3000);
    };

    ws.onerror = () => {
      setError('WebSocket connection error');
    };

    ws.onmessage = (event) => {
      try {
        const message = JSON.parse(event.data);
        handleWebSocketMessage(message);
      } catch {
        setError('Received invalid WebSocket message');
      }
    };
  };

  const disconnectWebSocket = () => {
    if (reconnectTimer) {
      clearTimeout(reconnectTimer);
      reconnectTimer = null;
    }
    if (ws) {
      ws.close();
      ws = null;
    }
  };

  const handleWebSocketMessage = (message: { event: string; data: unknown }) => {
    const downloadStore = useDownloadStore();
    const rssStore = useRssStore();
    const failedStore = useFailedStore();
    const libraryStore = useLibraryStore();

    if (message.event.startsWith('rss_')) {
      rssStore.handleWebSocketEvent(message.event, message.data);
      return;
    }

    if (message.event.startsWith('scan_')) {
      useScannerStore().handleWebSocketEvent(message.event, message.data);
      return;
    }

    switch (message.event) {
      case 'book_status_changed':
        fetchPipelineStats();
        failedStore.handleBookEvent(
          'book_status_changed',
          message.data as { book_id: number; new_status: string }
        );
        libraryStore.handleBookEvent(
          'book_status_changed',
          message.data as { book_id: number; new_status: string }
        );
        break;

      case 'book_force_retried':
        failedStore.handleBookEvent(
          'book_force_retried',
          message.data as { book_id: number; book_status: string }
        );
        libraryStore.handleBookEvent(
          'book_force_retried',
          message.data as { book_id: number; book_status: string }
        );
        break;

      case 'book_searching':
      case 'book_grabbed':
      case 'download_started':
      case 'download_completed':
      case 'download_failed':
      case 'import_started':
      case 'import_failed':
      case 'book_failed':
        if (message.event === 'download_started' || message.event === 'download_completed') {
          downloadStore.handleWebSocketMessage(message);
        }
        fetchPipelineStats();
        break;

      case 'download_progress':
        downloadStore.handleWebSocketMessage(message);
        break;

      case 'import_completed':
        downloadStore.handleWebSocketMessage(message);
        fetchPipelineStats();
        fetchRecentBooks();
        break;

      case 'ereader_sync_started':
        // Also covers syncs triggered from another tab or a schedule
        ereaderSyncing.value = true;
        ereaderSyncInfo.value = message.data as { ereader_id: string; total_books: number };
        break;

      case 'transfer_progress':
        ereaderSyncProgress.value = message.data as TransferProgress;
        break;

      case 'ereader_delivery_started':
        libraryStore.handleBookEvent(
          'ereader_delivery_started',
          message.data as { book_id: number }
        );
        break;

      case 'ereader_delivery_progress':
        ereaderDeliveryProgress.value = message.data as EreaderDeliveryProgress;
        break;

      case 'ereader_sync_completed': {
        const d = message.data as { transferred: number; skipped: number; failed: number };
        finishEreaderSync();
        const toast = useToast();
        const summary = `${d.transferred} sent, ${d.skipped} already on device`;
        if (d.failed > 0) {
          toast.error(`E-reader sync: ${summary}, ${d.failed} failed`);
        } else {
          toast.success(`E-reader sync complete: ${summary}`);
        }
        fetchPipelineStats();
        break;
      }

      case 'ereader_sync_failed':
        finishEreaderSync();
        useToast().error(`E-reader sync failed: ${(message.data as { error: string }).error}`);
        break;

      case 'ereader_delivered':
      case 'ereader_delivery_skipped':
      case 'ereader_delivery_requeued':
        if (message.event !== 'ereader_delivery_requeued') {
          ereaderDeliveryProgress.value = null;
        }
        // Keep any visible book badge fresh (library grid / book detail)
        libraryStore.handleBookEvent(message.event, message.data as { book_id: number });
        fetchPipelineStats();
        break;

      case 'pong':
        break;
    }
  };

  const finishEreaderSync = () => {
    ereaderSyncing.value = false;
    ereaderSyncProgress.value = null;
    ereaderSyncInfo.value = null;
    if (ereaderSyncTimeout) {
      clearTimeout(ereaderSyncTimeout);
      ereaderSyncTimeout = null;
    }
  };

  const fetchPipelineStats = async () => {
    try {
      const response = await fetch('/api/library/stats');
      if (response.ok) pipelineStats.value = await response.json();
    } catch {
      setError('Failed to fetch pipeline stats');
    }
  };

  const fetchRecentBooks = async () => {
    try {
      const response = await fetch('/api/library/books?sort=created_at&order=desc&limit=5');
      if (response.ok) {
        const data = await response.json();
        recentBooks.value = data.books || data;
      }
    } catch {
      setError('Failed to fetch recent books');
    }
  };

  const triggerHardcoverSync = async () => {
    hardcoverSyncing.value = true;
    try {
      const response = await fetch('/api/sync/hardcover', { method: 'POST' });
      if (!response.ok) {
        const errorData = await response.json().catch(() => ({}));
        throw new Error(errorData.detail || 'Hardcover sync failed');
      }
      return await response.json();
    } catch (e) {
      const errorMsg = e instanceof Error ? e.message : 'Hardcover sync failed';
      setError(errorMsg);
      throw e;
    } finally {
      hardcoverSyncing.value = false;
      fetchPipelineStats();
      fetchRecentBooks();
    }
  };

  const triggerEreaderSync = async (ereader_device: string, dryRun = false) => {
    const toast = useToast();
    if (dryRun) {
      // Dry runs respond synchronously and never touch the syncing/progress state.
      try {
        const response = await fetch('/api/sync/ereader', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ ereader_device, dry_run: true }),
        });
        if (!response.ok) {
          const errorData = await response.json().catch(() => ({}));
          const msg = errorData.detail?.message || errorData.detail || 'E-reader sync preview failed';
          throw new Error(msg);
        }
        const preview: EreaderSyncPreview = await response.json();
        ereaderSyncPreview.value = preview;
        return preview;
      } catch (e) {
        const errorMsg = e instanceof Error ? e.message : 'E-reader sync preview failed';
        toast.error(errorMsg);
        throw e;
      }
    }
    ereaderSyncing.value = true;
    ereaderSyncProgress.value = null;
    ereaderSyncPreview.value = null;
    try {
      const response = await fetch('/api/sync/ereader', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ ereader_device }),
      });
      if (!response.ok) {
        const errorData = await response.json().catch(() => ({}));
        // FastAPI nests structured details: {"detail": {"error", "message"}}
        const msg = errorData.detail?.message || errorData.detail || 'E-reader sync failed';
        throw new Error(msg);
      }
      // The sync now runs in the background; stay in "Syncing…" until the
      // ereader_sync_completed/failed WebSocket event arrives.
      ereaderSyncTimeout = window.setTimeout(() => finishEreaderSync(), EREADER_SYNC_FALLBACK_MS);
      return await response.json();
    } catch (e) {
      finishEreaderSync();
      const errorMsg = e instanceof Error ? e.message : 'E-reader sync failed';
      toast.error(errorMsg);
      throw e;
    }
  };

  return {
    isRunning,
    wsConnected,
    error,
    pipelineStats,
    recentBooks,
    hardcoverSyncing,
    ereaderSyncing,
    ereaderSyncProgress,
    ereaderSyncInfo,
    ereaderSyncPreview,
    ereaderDeliveryProgress,

    connectWebSocket,
    disconnectWebSocket,
    clearError,
    fetchPipelineStats,
    fetchRecentBooks,
    triggerHardcoverSync,
    triggerEreaderSync,
  };
});
