import { defineStore } from 'pinia';
import { computed, ref } from 'vue';
import { useToast } from '../composables/useToast';
import type { Kindle, KindleDeviceBook, KindleStatus } from '../types';

export const useKindlesStore = defineStore('kindles', () => {
  const kindles = ref<Kindle[]>([]);
  const selectedKindleId = ref<string | null>(null);
  const isLoading = ref(false);

  const statuses = ref<Record<string, KindleStatus>>({});
  const statusLoading = ref(false);

  const deviceBooks = ref<KindleDeviceBook[]>([]);
  const deviceBooksLoading = ref(false);
  const deviceBooksError = ref<string | null>(null);
  const deviceBooksFetchedAt = ref<Date | null>(null);

  const selectedKindle = computed(
    () => kindles.value.find((k) => k.id === selectedKindleId.value) ?? null
  );
  const selectedStatus = computed(() =>
    selectedKindleId.value ? (statuses.value[selectedKindleId.value] ?? null) : null
  );

  const fetchKindles = async () => {
    isLoading.value = true;
    try {
      const response = await fetch('/api/kindles');
      if (!response.ok) return;
      const data: Kindle[] = await response.json();
      kindles.value = data;
      const selectionValid = data.some((k) => k.id === selectedKindleId.value);
      if (!selectionValid) {
        // Prefer a device with a hostname; the seeded placeholder has none
        const firstReal = data.find((k) => k.hostname) ?? data[0];
        selectedKindleId.value = firstReal?.id ?? null;
      }
    } catch {
      // Non-fatal: views render an empty-device state
    } finally {
      isLoading.value = false;
    }
  };

  const fetchStatus = async (kindleId: string, refresh = false) => {
    statusLoading.value = true;
    try {
      const response = await fetch(
        `/api/kindles/${kindleId}/status${refresh ? '?refresh=true' : ''}`
      );
      if (response.ok) {
        statuses.value = { ...statuses.value, [kindleId]: await response.json() };
      }
    } catch {
      // Leave the previous status in place
    } finally {
      statusLoading.value = false;
    }
  };

  const fetchDeviceBooks = async (kindleId: string) => {
    deviceBooksLoading.value = true;
    deviceBooksError.value = null;
    try {
      const response = await fetch(`/api/kindles/${kindleId}/books`);
      const data = await response.json();
      if (data.success) {
        deviceBooks.value = data.books;
        deviceBooksFetchedAt.value = new Date();
      } else {
        deviceBooks.value = [];
        deviceBooksError.value = data.error || 'Could not list books on the Kindle';
      }
    } catch {
      deviceBooks.value = [];
      deviceBooksError.value = 'Could not reach the server';
    } finally {
      deviceBooksLoading.value = false;
    }
  };

  const testConnection = async (kindleId: string) => {
    const toast = useToast();
    try {
      const response = await fetch(`/api/kindles/${kindleId}/test`, { method: 'POST' });
      const result = await response.json();
      if (result.success) {
        toast.success(result.message || 'Kindle connection OK');
      } else {
        toast.error(result.error || 'Kindle connection failed');
      }
      return result;
    } catch {
      toast.error('Kindle connection test failed');
      return { success: false };
    }
  };

  return {
    kindles,
    selectedKindleId,
    isLoading,
    statuses,
    statusLoading,
    deviceBooks,
    deviceBooksLoading,
    deviceBooksError,
    deviceBooksFetchedAt,

    selectedKindle,
    selectedStatus,

    fetchKindles,
    fetchStatus,
    fetchDeviceBooks,
    testConnection,
  };
});
