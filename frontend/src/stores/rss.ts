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
  capsCachedAt: string | null;
  capsSupportsBookSearch: boolean | null;
}

export interface RssMatchEvent {
  indexer: string;
  guid: string;
  book_id: number;
  title: string;
  matched_at: string;
  similarity?: number | null;
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
        syncInProgress.value = true;
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
        if (payload?.started_at) {
          lastSyncStartedAt.value = payload.started_at as string;
        } else {
          lastSyncStartedAt.value = new Date().toISOString();
        }
        break;
      case 'rss_sync_completed':
        syncInProgress.value = false;
        if (payload?.completed_at) {
          lastSyncCompletedAt.value = payload.completed_at as string;
        } else {
          lastSyncCompletedAt.value = new Date().toISOString();
        }
        break;
      case 'rss_sync_failed':
        syncInProgress.value = false;
        break;
      case 'rss_indexer_polled':
        if (payload?.indexer_id) {
          const index = indexers.value.findIndex((i) => i.indexerId === payload.indexer_id);
          const previous = index !== -1 ? indexers.value[index] : null;
          const indexerState: RssIndexerState = {
            indexerId: payload.indexer_id as number,
            indexerName: (payload.indexer_name as string | null) ?? null,
            lastPollAt: new Date().toISOString(),
            lastStatus: (payload.status as string | null) ?? null,
            lastError: previous?.lastError ?? null,
            itemsSeenCount: (previous?.itemsSeenCount ?? 0) + ((payload.items_seen as number) ?? 0),
            itemsGrabbedCount: previous?.itemsGrabbedCount ?? 0,
            retryNotBeforeAt: previous?.retryNotBeforeAt ?? null,
            capsCachedAt: previous?.capsCachedAt ?? null,
            capsSupportsBookSearch: previous?.capsSupportsBookSearch ?? null,
          };
          if (index !== -1) {
            indexers.value[index] = { ...indexers.value[index], ...indexerState };
          } else {
            indexers.value.push(indexerState);
          }
        }
        break;
      case 'rss_match_found':
      case 'rss_grabbed':
        if (payload?.guid) {
          const matchEvent: RssMatchEvent = {
            indexer: payload.indexer as string,
            guid: payload.guid as string,
            book_id: payload.book_id as number,
            title: payload.title as string,
            matched_at: (payload.matched_at as string) ?? new Date().toISOString(),
            similarity: (payload.similarity as number | null | undefined) ?? null,
          };
          const existingIndex = recentMatches.value.findIndex((m) => m.guid === matchEvent.guid);
          if (existingIndex !== -1) {
            recentMatches.value[existingIndex] = {
              ...recentMatches.value[existingIndex],
              ...matchEvent,
            };
          } else {
            recentMatches.value.push(matchEvent);
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
