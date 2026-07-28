import { defineStore } from 'pinia';
import { ref } from 'vue';
import type { Book } from '../types';
import { useDownloadStore } from './download';
import { useFailedStore } from './failed';
import { useLibraryStore } from './library';
import { useRssStore } from './rss';
import { useScannerStore } from './scanner';

export const useSyncStore = defineStore('sync', () => {
  const isRunning = ref(false);
  const wsConnected = ref(false);
  const error = ref<string | null>(null);

  // Pipeline state
  const pipelineStats = ref<{
    total: number;
    by_status: Record<string, number>;
    total_size: number;
  } | null>(null);
  const recentBooks = ref<Book[]>([]);
  const hardcoverSyncing = ref(false);
  const kindleSyncing = ref(false);

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

      case 'pong':
        break;
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

  const triggerKindleSync = async (kindle_device: string) => {
    kindleSyncing.value = true;
    try {
      const response = await fetch('/api/sync/kindle', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ kindle_device }),
      });
      if (!response.ok) {
        const errorData = await response.json().catch(() => ({}));
        throw new Error(errorData.detail || 'Kindle sync failed');
      }
      return await response.json();
    } catch (e) {
      const errorMsg = e instanceof Error ? e.message : 'Kindle sync failed';
      setError(errorMsg);
      throw e;
    } finally {
      kindleSyncing.value = false;
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

    connectWebSocket,
    disconnectWebSocket,
    clearError,
    fetchPipelineStats,
    fetchRecentBooks,
    triggerHardcoverSync,
    triggerKindleSync,
  };
});
