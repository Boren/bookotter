import { defineStore } from 'pinia';
import { computed, ref } from 'vue';
import type {
  Book,
  BookProgressEvent,
  BookResult,
  SyncRun,
  SyncStats,
  TransferProgressEvent,
  WebSocketMessage,
} from '../types';

export const useSyncStore = defineStore('sync', () => {
  // State
  const isRunning = ref(false);
  const currentRunId = ref<number | null>(null);
  const progress = ref<BookProgressEvent | null>(null);
  const transferProgress = ref<TransferProgressEvent | null>(null);
  const latestRun = ref<SyncRun | null>(null);
  const stats = ref<SyncStats | null>(null);
  const latestChanges = ref<BookResult[]>([]);
  const wsConnected = ref(false);
  const error = ref<string | null>(null);

  // Pipeline state
  const pipelineStats = ref<{ total: number; by_status: Record<string, number>; total_size: number } | null>(null);
  const recentBooks = ref<Book[]>([]);
  const hardcoverSyncing = ref(false);
  const kindleSyncing = ref(false);

  // Error handling
  const setError = (message: string) => {
    error.value = message;
    // Auto-clear after 15 seconds
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

  // Actions
  const connectWebSocket = () => {
    if (ws?.readyState === WebSocket.OPEN) return;

    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const wsUrl = `${protocol}//${window.location.host}/api/ws`;

    ws = new WebSocket(wsUrl);

    ws.onopen = () => {
      wsConnected.value = true;
      console.log('WebSocket connected');
    };

    ws.onclose = () => {
      wsConnected.value = false;
      console.log('WebSocket disconnected');
      // Reconnect after 3 seconds
      if (reconnectTimer) clearTimeout(reconnectTimer);
      reconnectTimer = window.setTimeout(connectWebSocket, 3000);
    };

    ws.onerror = (error) => {
      console.error('WebSocket error:', error);
    };

    ws.onmessage = (event) => {
      try {
        const message = JSON.parse(event.data);
        handleWebSocketMessage(message);
      } catch (e) {
        console.error('Failed to parse WebSocket message:', e);
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

  const handleWebSocketMessage = (message: WebSocketMessage) => {
    switch (message.event) {
      case 'sync_started':
        isRunning.value = true;
        currentRunId.value = message.data.sync_run_id;
        progress.value = null;
        break;

      case 'books_fetched':
        // Update total books count
        break;

      case 'book_progress':
        progress.value = message.data;
        break;

      case 'transfer_progress':
        transferProgress.value = message.data;
        break;

      case 'book_completed':
        // Clear transfer progress when book completes
        transferProgress.value = null;
        break;

      case 'sync_completed':
        isRunning.value = false;
        progress.value = null;
        transferProgress.value = null;
        currentRunId.value = null;
        fetchStatus();
        fetchLatestChanges();
        break;

      case 'sync_failed':
        isRunning.value = false;
        progress.value = null;
        transferProgress.value = null;
        currentRunId.value = null;
        setError(message.data.error || 'Sync failed');
        fetchStatus();
        break;

      case 'book_wanted':
      case 'download_started':
      case 'download_completed':
        fetchPipelineStats();
        break;

      case 'import_completed':
        fetchPipelineStats();
        fetchRecentBooks();
        break;

      case 'pong':
        break;
    }
  };

  const fetchStatus = async () => {
    try {
      const response = await fetch('/api/sync/status');
      if (!response.ok) {
        const errorData = await response.json().catch(() => ({}));
        throw new Error(errorData.detail || `Server error: ${response.status}`);
      }
      const data = await response.json();
      isRunning.value = data.is_running;
      latestRun.value = data.latest_run;
    } catch (e) {
      console.error('Failed to fetch status:', e);
      setError(e instanceof Error ? e.message : 'Failed to connect to server');
    }
  };

  const fetchStats = async () => {
    try {
      const response = await fetch('/api/sync/stats');
      if (!response.ok) {
        const errorData = await response.json().catch(() => ({}));
        throw new Error(errorData.detail || `Server error: ${response.status}`);
      }
      stats.value = await response.json();
    } catch (e) {
      console.error('Failed to fetch stats:', e);
      setError(e instanceof Error ? e.message : 'Failed to fetch statistics');
    }
  };

  const fetchLatestChanges = async () => {
    try {
      const response = await fetch('/api/sync/latest-changes?limit=10');
      if (!response.ok) {
        const errorData = await response.json().catch(() => ({}));
        throw new Error(errorData.detail || `Server error: ${response.status}`);
      }
      const data = await response.json();
      latestChanges.value = data.books;
    } catch (e) {
      console.error('Failed to fetch latest changes:', e);
    }
  };

  const startSync = async (options: { kindle_device?: string; dry_run?: boolean } = {}) => {
    // Optimistic UI update - show progress immediately
    isRunning.value = true;
    progress.value = {
      sync_run_id: 0,
      current: 0,
      total: 0,
      book: { title: 'Initializing...', status: 'Connecting to services' },
    };

    try {
      const response = await fetch('/api/sync/start', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          kindle_device: options.kindle_device,
          dry_run: options.dry_run ?? false,
        }),
      });

      if (!response.ok) {
        const error = await response.json();
        throw new Error(error.detail || 'Failed to start sync');
      }

      return await response.json();
    } catch (e) {
      // Reset optimistic state on error
      isRunning.value = false;
      progress.value = null;
      const errorMsg = e instanceof Error ? e.message : 'Failed to start sync';
      console.error('Failed to start sync:', e);
      setError(errorMsg);
      throw e;
    }
  };

  const stopSync = async () => {
    try {
      const response = await fetch('/api/sync/stop', { method: 'POST' });
      return await response.json();
    } catch (e) {
      console.error('Failed to stop sync:', e);
      throw e;
    }
  };

  const fetchPipelineStats = async () => {
    try {
      const response = await fetch('/api/library/stats');
      if (response.ok) pipelineStats.value = await response.json();
    } catch (e) {
      console.error('Failed to fetch pipeline stats:', e);
    }
  };

  const fetchRecentBooks = async () => {
    try {
      const response = await fetch('/api/library/books?sort=created_at&order=desc&limit=5');
      if (response.ok) {
        const data = await response.json();
        recentBooks.value = data.books || data;
      }
    } catch (e) {
      console.error('Failed to fetch recent books:', e);
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

  // Computed
  const progressPercent = computed(() => {
    if (!progress.value) return 0;
    return Math.round((progress.value.current / progress.value.total) * 100);
  });

  const transferSpeedFormatted = computed(() => {
    if (!transferProgress.value) return '';
    const speed = transferProgress.value.speed_bytes_per_sec;
    if (speed >= 1_000_000) {
      return `${(speed / 1_000_000).toFixed(1)} MB/s`;
    }
    return `${Math.round(speed / 1_000)} KB/s`;
  });

  const transferEtaFormatted = computed(() => {
    if (!transferProgress.value) return '';
    const seconds = transferProgress.value.eta_seconds;
    if (seconds < 60) {
      return `${seconds}s`;
    }
    const minutes = Math.floor(seconds / 60);
    const remainingSecs = seconds % 60;
    return `${minutes}:${remainingSecs.toString().padStart(2, '0')}`;
  });

  return {
    isRunning,
    currentRunId,
    progress,
    transferProgress,
    latestRun,
    stats,
    latestChanges,
    wsConnected,
    error,
    pipelineStats,
    recentBooks,
    hardcoverSyncing,
    kindleSyncing,

    progressPercent,
    transferSpeedFormatted,
    transferEtaFormatted,

    connectWebSocket,
    disconnectWebSocket,
    fetchStatus,
    fetchStats,
    fetchLatestChanges,
    startSync,
    stopSync,
    clearError,
    fetchPipelineStats,
    fetchRecentBooks,
    triggerHardcoverSync,
    triggerKindleSync,
  };
});
