import { defineStore } from 'pinia';
import { ref } from 'vue';
import type { BlocklistEntry } from '@/types';

export const useBlocklistStore = defineStore('blocklist', () => {
  const entries = ref<BlocklistEntry[]>([]);
  const isLoading = ref(false);
  const error = ref<string | null>(null);

  const list = async () => {
    isLoading.value = true;
    try {
      const response = await fetch('/api/blocklist');
      if (!response.ok) throw new Error('Failed to fetch blocklist');
      const data = await response.json();
      entries.value = data.entries || [];
    } catch (e) {
      error.value = e instanceof Error ? e.message : 'Failed to fetch';
    } finally {
      isLoading.value = false;
    }
  };

  const add = async (indexer: string, release_guid: string, title: string, reason?: string) => {
    const response = await fetch('/api/blocklist/from-release', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ indexer, release_guid, title, reason }),
    });
    if (response.status === 409) throw new Error('Already blocklisted');
    if (!response.ok) throw new Error('Failed to add to blocklist');
    await list(); // Refresh
    return await response.json();
  };

  const remove = async (id: number) => {
    const response = await fetch(`/api/blocklist/${id}`, { method: 'DELETE' });
    if (!response.ok) throw new Error('Failed to remove from blocklist');
    await list(); // Refresh
  };

  return { entries, isLoading, error, list, add, remove };
});
