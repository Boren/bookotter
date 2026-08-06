import { createPinia, setActivePinia } from 'pinia';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { useLibraryStore } from '../stores/library';

describe('fetchSeriesBooks', () => {
  beforeEach(() => {
    setActivePinia(createPinia());
    vi.restoreAllMocks();
  });

  it('requests books filtered by series sorted by position', async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ books: [{ id: 1, title: 'Leviathan Wakes' }], total: 1 }),
    });
    vi.stubGlobal('fetch', fetchMock);

    const store = useLibraryStore();
    const books = await store.fetchSeriesBooks('The Expanse');

    expect(fetchMock).toHaveBeenCalledOnce();
    const url = fetchMock.mock.calls[0][0] as string;
    expect(url).toContain('series=The+Expanse');
    expect(url).toContain('sort_by=series_position');
    expect(url).toContain('sort_order=asc');
    expect(books).toEqual([{ id: 1, title: 'Leviathan Wakes' }]);
  });

  it('returns an empty list on a failed response', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: false, status: 500 }));

    const store = useLibraryStore();
    const books = await store.fetchSeriesBooks('The Expanse');

    expect(books).toEqual([]);
  });
});
