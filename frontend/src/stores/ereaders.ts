import { defineStore } from 'pinia';
import { computed, ref } from 'vue';
import { useToast } from '../composables/useToast';
import type { Ereader, EreaderDeviceBook, EreaderStatus } from '../types';

export const useEreadersStore = defineStore('ereaders', () => {
  const ereaders = ref<Ereader[]>([]);
  const selectedEreaderId = ref<string | null>(null);
  const isLoading = ref(false);

  const statuses = ref<Record<string, EreaderStatus>>({});
  const statusLoading = ref(false);

  const deviceBooks = ref<EreaderDeviceBook[]>([]);
  const deviceBooksLoading = ref(false);
  const deviceBooksError = ref<string | null>(null);
  const deviceBooksFetchedAt = ref<Date | null>(null);

  const selectedEreader = computed(
    () => ereaders.value.find((k) => k.id === selectedEreaderId.value) ?? null
  );
  const selectedStatus = computed(() =>
    selectedEreaderId.value ? (statuses.value[selectedEreaderId.value] ?? null) : null
  );

  const fetchEreaders = async () => {
    isLoading.value = true;
    try {
      const response = await fetch('/api/ereaders');
      if (!response.ok) return;
      const data: Ereader[] = await response.json();
      ereaders.value = data;
      const selectionValid = data.some((k) => k.id === selectedEreaderId.value);
      if (!selectionValid) {
        // Prefer a device with a hostname; the seeded placeholder has none
        const firstReal = data.find((k) => k.hostname) ?? data[0];
        selectedEreaderId.value = firstReal?.id ?? null;
      }
    } catch {
      // Non-fatal: views render an empty-device state
    } finally {
      isLoading.value = false;
    }
  };

  const fetchStatus = async (ereaderId: string, refresh = false) => {
    statusLoading.value = true;
    try {
      const response = await fetch(
        `/api/ereaders/${ereaderId}/status${refresh ? '?refresh=true' : ''}`
      );
      if (response.ok) {
        statuses.value = { ...statuses.value, [ereaderId]: await response.json() };
      }
    } catch {
      // Leave the previous status in place
    } finally {
      statusLoading.value = false;
    }
  };

  const fetchDeviceBooks = async (ereaderId: string) => {
    deviceBooksLoading.value = true;
    deviceBooksError.value = null;
    try {
      const response = await fetch(`/api/ereaders/${ereaderId}/books`);
      const data = await response.json();
      if (data.success) {
        deviceBooks.value = data.books;
        deviceBooksFetchedAt.value = new Date();
      } else {
        deviceBooks.value = [];
        deviceBooksError.value = data.error || 'Could not list books on the E-reader';
      }
    } catch {
      deviceBooks.value = [];
      deviceBooksError.value = 'Could not reach the server';
    } finally {
      deviceBooksLoading.value = false;
    }
  };

  const testConnection = async (ereaderId: string) => {
    const toast = useToast();
    try {
      const response = await fetch(`/api/ereaders/${ereaderId}/test`, { method: 'POST' });
      const result = await response.json();
      if (result.success) {
        toast.success(result.message || 'E-reader connection OK');
      } else {
        toast.error(result.error || 'E-reader connection failed');
      }
      return result;
    } catch {
      toast.error('E-reader connection test failed');
      return { success: false };
    }
  };

  return {
    ereaders,
    selectedEreaderId,
    isLoading,
    statuses,
    statusLoading,
    deviceBooks,
    deviceBooksLoading,
    deviceBooksError,
    deviceBooksFetchedAt,

    selectedEreader,
    selectedStatus,

    fetchEreaders,
    fetchStatus,
    fetchDeviceBooks,
    testConnection,
  };
});
