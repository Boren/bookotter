import { defineStore } from 'pinia';
import { computed, ref } from 'vue';
import type { Book } from '../types';

export const useLibraryStore = defineStore('library', () => {
  // State
  const books = ref<Book[]>([]);
  const total = ref(0);
  const currentBook = ref<Book | null>(null);
  const isLoading = ref(false);
  const error = ref<string | null>(null);

  // Filter / sort / pagination
  const searchQuery = ref('');
  const filterStatus = ref<string | null>(null);
  const filterAuthor = ref<string | null>(null);
  const sortBy = ref('created_at');
  const sortOrder = ref<'asc' | 'desc'>('desc');
  const limit = ref(50);
  const offset = ref(0);

  // Accumulated authors for filter dropdown
  const knownAuthors = ref<string[]>([]);

  // Error handling
  const clearError = () => {
    error.value = null;
  };

  // Actions
  const fetchBooks = async () => {
    isLoading.value = true;
    error.value = null;
    try {
      const params = new URLSearchParams();
      if (filterStatus.value) params.set('status', filterStatus.value);
      if (filterAuthor.value) params.set('author', filterAuthor.value);
      if (searchQuery.value) params.set('search', searchQuery.value);
      params.set('sort_by', sortBy.value);
      params.set('sort_order', sortOrder.value);
      params.set('limit', String(limit.value));
      params.set('offset', String(offset.value));

      const response = await fetch(`/api/library/books?${params}`);
      if (!response.ok) throw new Error('Failed to fetch books');
      const data = await response.json();
      books.value = data.books;
      total.value = data.total;

      // Accumulate known authors for filter dropdown
      const newAuthors = data.books
        .map((b: Book) => b.author?.name)
        .filter((name: string | undefined): name is string => !!name);
      const authorSet = new Set([...knownAuthors.value, ...newAuthors]);
      knownAuthors.value = Array.from(authorSet).sort();
    } catch (e) {
      error.value = e instanceof Error ? e.message : 'Failed to fetch books';
    } finally {
      isLoading.value = false;
    }
  };

  const fetchBook = async (id: number) => {
    isLoading.value = true;
    error.value = null;
    if (currentBook.value?.id !== id) {
      currentBook.value = null;
    }
    try {
      const response = await fetch(`/api/library/books/${id}`);
      if (!response.ok) {
        if (response.status === 404) throw new Error('Book not found');
        throw new Error('Failed to fetch book');
      }
      const data = await response.json();
      if (currentBook.value?.id === id || !currentBook.value) {
        currentBook.value = data;
      }
      const idx = books.value.findIndex((b) => b.id === id);
      if (idx !== -1) {
        books.value[idx] = data;
      }
    } catch (e) {
      error.value = e instanceof Error ? e.message : 'Failed to fetch book';
    } finally {
      isLoading.value = false;
    }
  };

  const updateBook = async (id: number, data: Record<string, unknown>) => {
    error.value = null;
    try {
      const response = await fetch(`/api/library/books/${id}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(data),
      });
      if (!response.ok) {
        const err = await response.json().catch(() => ({}));
        throw new Error(err.detail || 'Failed to update book');
      }
      const updated: Book = await response.json();
      currentBook.value = updated;
      const idx = books.value.findIndex((b) => b.id === id);
      if (idx !== -1) books.value[idx] = updated;
      return updated;
    } catch (e) {
      error.value = e instanceof Error ? e.message : 'Failed to update book';
      throw e;
    }
  };

  const deleteBook = async (id: number) => {
    error.value = null;
    try {
      const response = await fetch(`/api/library/books/${id}`, {
        method: 'DELETE',
      });
      if (!response.ok) {
        const err = await response.json().catch(() => ({}));
        throw new Error(err.detail || 'Failed to delete book');
      }
      currentBook.value = null;
      books.value = books.value.filter((b) => b.id !== id);
    } catch (e) {
      error.value = e instanceof Error ? e.message : 'Failed to delete book';
      throw e;
    }
  };

  const searchBooks = async (query: string) => {
    searchQuery.value = query;
    offset.value = 0;
    await fetchBooks();
  };

  const createBook = async (title: string, authorName?: string) => {
    const response = await fetch('/api/library/books', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ title, author_name: authorName }),
    });
    if (!response.ok) throw new Error('Failed to create book');
    const book = await response.json();
    books.value = [book, ...books.value];
    total.value += 1;
    return book;
  };

  const setFilterStatus = (status: string | null) => {
    filterStatus.value = status;
    offset.value = 0;
  };

  const handleBookEvent = (event: string, payload: { book_id: number; [key: string]: unknown }) => {
    if (event === 'book_status_changed' || event === 'book_force_retried') {
      const inBooks = books.value.some((b) => b.id === payload.book_id);
      const isCurrent = currentBook.value?.id === payload.book_id;
      if (inBooks || isCurrent) {
        fetchBook(payload.book_id);
      }
    }
  };

  // Computed
  const bookCount = computed(() => books.value.length);
  const totalPages = computed(() => Math.ceil(total.value / limit.value));
  const currentPage = computed(() => Math.floor(offset.value / limit.value) + 1);

  const filteredBooks = computed(() => {
    // Filtering is server-side
    return books.value;
  });

  return {
    // State
    books,
    total,
    currentBook,
    isLoading,
    error,
    searchQuery,
    filterStatus,
    filterAuthor,
    sortBy,
    sortOrder,
    limit,
    offset,
    knownAuthors,

    // Computed
    bookCount,
    totalPages,
    currentPage,
    filteredBooks,

    // Actions
    fetchBooks,
    fetchBook,
    createBook,
    updateBook,
    deleteBook,
    searchBooks,
    setFilterStatus,
    clearError,
    handleBookEvent,
  };
});
