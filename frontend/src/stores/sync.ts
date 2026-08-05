import { defineStore } from 'pinia';
import { computed, ref } from 'vue';
import { useToast } from '../composables/useToast';
import type { Book, KindleDeliveryProgress, KindleSyncPreview, TransferProgress } from '../types';
import { useDownloadStore } from './download';
import { useFailedStore } from './failed';
import { useLibraryStore } from './library';
import { useRssStore } from './rss';
import { useScannerStore } from './scanner';

// Safety net: release the syncing state if the WebSocket completion event
// never arrives (e.g. connection dropped mid-sync).
const KINDLE_SYNC_FALLBACK_MS = 15 * 60 * 1000;

export const useSyncStore = defineStore('sync', () => {
  const wsConnected = ref(false);
  const error = ref<string | null>(null);

  // Pipeline state
  const pipelineStats = ref<{
    total_books: number;
    by_status: Record<string, number>;
    by_kindle_delivery_status?: Record<string, number>;
    author_count: number;
    total_size_bytes: number;
  } | null>(null);
  const recentBooks = ref<Book[]>([]);
  const hardcoverSyncing = ref(false);
  const kindleSyncing = ref(false);
  const kindleSyncProgress = ref<TransferProgress | null>(null);
  const kindleSyncInfo = ref<{ kindle_id: string; total_books: number } | null>(null);
  // Result of the last dry-run sync ("Preview" on the Kindle page)
  const kindleSyncPreview = ref<KindleSyncPreview | null>(null);
  // Per-book pipeline delivery ("Send to Kindle" on a book page)
  const kindleDeliveryProgress = ref<KindleDeliveryProgress | null>(null);
  let kindleSyncTimeout: number | null = null;

  // Drives the sidebar "Syncing…" indicator
  const isRunning = computed(() => hardcoverSyncing.value || kindleSyncing.value);

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

      case 'kindle_sync_started':
        // Also covers syncs triggered from another tab or a schedule
        kindleSyncing.value = true;
        kindleSyncInfo.value = message.data as { kindle_id: string; total_books: number };
        break;

      case 'transfer_progress':
        kindleSyncProgress.value = message.data as TransferProgress;
        break;

      case 'kindle_delivery_started':
        libraryStore.handleBookEvent(
          'kindle_delivery_started',
          message.data as { book_id: number }
        );
        break;

      case 'kindle_delivery_progress':
        kindleDeliveryProgress.value = message.data as KindleDeliveryProgress;
        break;

      case 'kindle_sync_completed': {
        const d = message.data as { transferred: number; skipped: number; failed: number };
        finishKindleSync();
        const toast = useToast();
        const summary = `${d.transferred} sent, ${d.skipped} already on device`;
        if (d.failed > 0) {
          toast.error(`Kindle sync: ${summary}, ${d.failed} failed`);
        } else {
          toast.success(`Kindle sync complete: ${summary}`);
        }
        fetchPipelineStats();
        break;
      }

      case 'kindle_sync_failed':
        finishKindleSync();
        useToast().error(`Kindle sync failed: ${(message.data as { error: string }).error}`);
        break;

      case 'kindle_delivered':
      case 'kindle_delivery_skipped':
      case 'kindle_delivery_requeued':
        if (message.event !== 'kindle_delivery_requeued') {
          kindleDeliveryProgress.value = null;
        }
        // Keep any visible book badge fresh (library grid / book detail)
        libraryStore.handleBookEvent(message.event, message.data as { book_id: number });
        fetchPipelineStats();
        break;

      case 'pong':
        break;
    }
  };

  const finishKindleSync = () => {
    kindleSyncing.value = false;
    kindleSyncProgress.value = null;
    kindleSyncInfo.value = null;
    if (kindleSyncTimeout) {
      clearTimeout(kindleSyncTimeout);
      kindleSyncTimeout = null;
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

  const triggerKindleSync = async (kindle_device: string, dryRun = false) => {
    const toast = useToast();
    if (dryRun) {
      // Dry runs respond synchronously and never touch the syncing/progress state.
      try {
        const response = await fetch('/api/sync/kindle', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ kindle_device, dry_run: true }),
        });
        if (!response.ok) {
          const errorData = await response.json().catch(() => ({}));
          const msg = errorData.detail?.message || errorData.detail || 'Kindle sync preview failed';
          throw new Error(msg);
        }
        const preview: KindleSyncPreview = await response.json();
        kindleSyncPreview.value = preview;
        return preview;
      } catch (e) {
        const errorMsg = e instanceof Error ? e.message : 'Kindle sync preview failed';
        toast.error(errorMsg);
        throw e;
      }
    }
    kindleSyncing.value = true;
    kindleSyncProgress.value = null;
    kindleSyncPreview.value = null;
    try {
      const response = await fetch('/api/sync/kindle', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ kindle_device }),
      });
      if (!response.ok) {
        const errorData = await response.json().catch(() => ({}));
        // FastAPI nests structured details: {"detail": {"error", "message"}}
        const msg = errorData.detail?.message || errorData.detail || 'Kindle sync failed';
        throw new Error(msg);
      }
      // The sync now runs in the background; stay in "Syncing…" until the
      // kindle_sync_completed/failed WebSocket event arrives.
      kindleSyncTimeout = window.setTimeout(() => finishKindleSync(), KINDLE_SYNC_FALLBACK_MS);
      return await response.json();
    } catch (e) {
      finishKindleSync();
      const errorMsg = e instanceof Error ? e.message : 'Kindle sync failed';
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
    kindleSyncing,
    kindleSyncProgress,
    kindleSyncInfo,
    kindleSyncPreview,
    kindleDeliveryProgress,

    connectWebSocket,
    disconnectWebSocket,
    clearError,
    fetchPipelineStats,
    fetchRecentBooks,
    triggerHardcoverSync,
    triggerKindleSync,
  };
});
