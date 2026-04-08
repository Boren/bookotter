import { defineStore } from 'pinia';
import { computed, ref } from 'vue';
import type { Book } from '../types';

export const useDownloadStore = defineStore('download', () => {
  // State
  const queue = ref<Book[]>([]);
  const isDownloading = ref(false);
  const currentDownload = ref<Book | null>(null);
  const downloadProgress = ref<number>(0);
  const error = ref<string | null>(null);
  const completedDownloads = ref<Book[]>([]);

  // Error handling
  const clearError = () => {
    error.value = null;
  };

  // Actions
  const addToQueue = (book: Book) => {
    // TODO: Implement addToQueue - add book to download queue
    console.log('TODO: addToQueue', book);
  };

  const removeFromQueue = (bookId: number) => {
    // TODO: Implement removeFromQueue - remove book from queue
    console.log('TODO: removeFromQueue', bookId);
  };

  const clearQueue = () => {
    // TODO: Implement clearQueue - clear all queued downloads
    console.log('TODO: clearQueue');
  };

  const startDownload = async () => {
    // TODO: Implement startDownload - start downloading queued books
    console.log('TODO: startDownload');
  };

  const pauseDownload = async () => {
    // TODO: Implement pauseDownload - pause current download
    console.log('TODO: pauseDownload');
  };

  const resumeDownload = async () => {
    // TODO: Implement resumeDownload - resume paused download
    console.log('TODO: resumeDownload');
  };

  const cancelDownload = async () => {
    // TODO: Implement cancelDownload - cancel current download
    console.log('TODO: cancelDownload');
  };

  const downloadToKindle = async (bookId: number, kindleDevice: string) => {
    // TODO: Implement downloadToKindle - download book to specific kindle
    console.log('TODO: downloadToKindle', bookId, kindleDevice);
  };

  // Computed
  const queueLength = computed(() => queue.value.length);

  const completedCount = computed(() => completedDownloads.value.length);

  const isQueueEmpty = computed(() => queue.value.length === 0);

  const progressPercent = computed(() => downloadProgress.value);

  return {
    // State
    queue,
    isDownloading,
    currentDownload,
    downloadProgress,
    error,
    completedDownloads,

    // Computed
    queueLength,
    completedCount,
    isQueueEmpty,
    progressPercent,

    // Actions
    addToQueue,
    removeFromQueue,
    clearQueue,
    startDownload,
    pauseDownload,
    resumeDownload,
    cancelDownload,
    downloadToKindle,
    clearError,
  };
});
