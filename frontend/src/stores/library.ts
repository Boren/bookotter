import { defineStore } from 'pinia';
import { computed, ref } from 'vue';
import type { Book } from '../types';

export const useLibraryStore = defineStore('library', () => {
  // State
  const books = ref<Book[]>([]);
  const isLoading = ref(false);
  const error = ref<string | null>(null);
  const selectedBooks = ref<Set<number>>(new Set());
  const filterStatus = ref<string | null>(null);

  // Error handling
  const clearError = () => {
    error.value = null;
  };

  // Actions
  const fetchBooks = async () => {
    // TODO: Implement fetchBooks - fetch from /api/library/books
    console.log('TODO: fetchBooks');
  };

  const searchBooks = async (query: string) => {
    // TODO: Implement searchBooks - search in library
    console.log('TODO: searchBooks', query);
  };

  const selectBook = (bookId: number) => {
    // TODO: Implement selectBook - add to selectedBooks
    console.log('TODO: selectBook', bookId);
  };

  const deselectBook = (bookId: number) => {
    // TODO: Implement deselectBook - remove from selectedBooks
    console.log('TODO: deselectBook', bookId);
  };

  const clearSelection = () => {
    // TODO: Implement clearSelection - clear all selected books
    console.log('TODO: clearSelection');
  };

  const setFilterStatus = (status: string | null) => {
    // TODO: Implement setFilterStatus - filter books by status
    console.log('TODO: setFilterStatus', status);
  };

  // Computed
  const bookCount = computed(() => books.value.length);

  const selectedCount = computed(() => selectedBooks.value.size);

  const filteredBooks = computed(() => {
    if (!filterStatus.value) return books.value;
    // TODO: Implement filtering logic
    return books.value;
  });

  return {
    // State
    books,
    isLoading,
    error,
    selectedBooks,
    filterStatus,

    // Computed
    bookCount,
    selectedCount,
    filteredBooks,

    // Actions
    fetchBooks,
    searchBooks,
    selectBook,
    deselectBook,
    clearSelection,
    setFilterStatus,
    clearError,
  };
});
