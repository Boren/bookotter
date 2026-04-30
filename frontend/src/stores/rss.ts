import { defineStore } from 'pinia';
import { ref } from 'vue';

export interface RssIndexerState {
  indexerId: number;
  indexerName: string | null;
  lastPollAt: string | null;
  lastStatus: string | null;
  lastError: string | null;
  itemsSeenCount: number;
  itemsGrabbedCount: number;
  retryNotBeforeAt: string | null;
  capsSupportsBookSearch: boolean | null;
}

export interface RssMatchEvent {
  indexer: string;
  guid: string;
  bookId: number;
  title: string;
  matchedAt: string;
}

export const useRssStore = defineStore('rss', () => {
  const indexers = ref<RssIndexerState[]>([]);
  const recentMatches = ref<RssMatchEvent[]>([]);
  const syncInProgress = ref(false);
  const lastSyncStartedAt = ref<string | null>(null);
  const lastSyncCompletedAt = ref<string | null>(null);

  const fetchStatus = async () => {
    try {
      const response = await fetch('/api/rss/status');
      if (response.ok) {
        const data = await response.json();
        indexers.value = data.indexers || [];
        recentMatches.value = data.recentMatches || [];
        syncInProgress.value = !!data.syncInProgress;
        lastSyncStartedAt.value = data.lastSyncStartedAt || null;
        lastSyncCompletedAt.value = data.lastSyncCompletedAt || null;
      }
    } catch (error) {
      console.error('Failed to fetch RSS status:', error);
    }
  };

  const triggerSync = async () => {
    try {
      const response = await fetch('/api/rss/sync', { method: 'POST' });
      if (response.status === 200) {
        syncInProgress.value = true;
      } else if (response.status === 409) {
      } else {
        console.error('Failed to trigger RSS sync:', response.statusText);
      }
    } catch (error) {
      console.error('Failed to trigger RSS sync:', error);
    }
  };

  const handleWebSocketEvent = (event: string, data: unknown) => {
    const payload = data as Record<string, unknown>;
    switch (event) {
      case 'rss_sync_started':
        syncInProgress.value = true;
        if (payload?.startedAt) {
          lastSyncStartedAt.value = payload.startedAt as string;
        } else {
          lastSyncStartedAt.value = new Date().toISOString();
        }
        break;
      case 'rss_sync_completed':
        syncInProgress.value = false;
        if (payload?.completedAt) {
          lastSyncCompletedAt.value = payload.completedAt as string;
        } else {
          lastSyncCompletedAt.value = new Date().toISOString();
        }
        break;
      case 'rss_sync_failed':
        syncInProgress.value = false;
        break;
      case 'rss_indexer_polled':
        if (payload?.indexerId) {
          const index = indexers.value.findIndex((i) => i.indexerId === payload.indexerId);
          if (index !== -1) {
            indexers.value[index] = { ...indexers.value[index], ...payload };
          } else {
            indexers.value.push(payload as unknown as RssIndexerState);
          }
        }
        break;
      case 'rss_match_found':
      case 'rss_grabbed':
        if (payload) {
          const existingIndex = recentMatches.value.findIndex((m) => m.guid === payload.guid);
          if (existingIndex !== -1) {
            recentMatches.value[existingIndex] = {
              ...recentMatches.value[existingIndex],
              ...payload,
            } as RssMatchEvent;
          } else {
            recentMatches.value.push(payload as unknown as RssMatchEvent);
          }

          if (recentMatches.value.length > 20) {
            recentMatches.value.splice(0, recentMatches.value.length - 20);
          }
        }
        break;
    }
  };

  return {
    indexers,
    recentMatches,
    syncInProgress,
    lastSyncStartedAt,
    lastSyncCompletedAt,
    fetchStatus,
    triggerSync,
    handleWebSocketEvent,
  };
});
