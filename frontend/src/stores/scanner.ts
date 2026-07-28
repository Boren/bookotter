import { defineStore } from 'pinia';
import { computed, ref } from 'vue';
import type {
  Book,
  HardcoverSearchResult,
  MatchProposal,
  RootFolder,
  ScanProgressEvent,
  ScanSummary,
} from '@/types';

const PROPOSAL_PAGE_SIZE = 500;
const MAX_PROPOSALS = 5000;

export const useScannerStore = defineStore('scanner', () => {
  const rootFolders = ref<RootFolder[]>([]);
  const lastScan = ref<ScanSummary | null>(null);
  const progress = ref<ScanProgressEvent | null>(null);
  const proposals = ref<MatchProposal[]>([]);
  const isScanning = ref(false);
  const isLoading = ref(false);
  const isBulkApproving = ref(false);
  const error = ref<string | null>(null);

  const matchedProposals = computed(() =>
    proposals.value
      .filter((p) => p.candidate_book_id !== null)
      .sort((a, b) => (b.score ?? 0) - (a.score ?? 0))
  );
  const unmatchedProposals = computed(() =>
    proposals.value
      .filter((p) => p.candidate_book_id === null)
      .sort((a, b) => a.relative_path.localeCompare(b.relative_path))
  );

  const setError = (message: string) => {
    error.value = message;
    setTimeout(() => {
      if (error.value === message) error.value = null;
    }, 15000);
  };

  const request = async (url: string, init?: RequestInit) => {
    const response = await fetch(url, init);
    if (!response.ok) {
      const data = await response.json().catch(() => ({}));
      throw new Error(data.detail || `Request failed (${response.status})`);
    }
    return response.json();
  };

  const fetchRootFolders = async () => {
    try {
      const data = await request('/api/root-folders');
      rootFolders.value = data.folders || [];
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to fetch root folders');
    }
  };

  const fetchLastScan = async () => {
    try {
      const data: ScanSummary[] = await request('/api/scanner/scans?limit=1');
      lastScan.value = data[0] ?? null;
      isScanning.value = lastScan.value?.status === 'running';
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to fetch scans');
    }
  };

  const fetchProposals = async () => {
    isLoading.value = true;
    try {
      const all: MatchProposal[] = [];
      for (let offset = 0; offset < MAX_PROPOSALS; offset += PROPOSAL_PAGE_SIZE) {
        const page: MatchProposal[] = await request(
          `/api/scanner/proposals?status=pending&limit=${PROPOSAL_PAGE_SIZE}&offset=${offset}`
        );
        all.push(...page);
        if (page.length < PROPOSAL_PAGE_SIZE) break;
      }
      proposals.value = all;
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to fetch proposals');
    } finally {
      isLoading.value = false;
    }
  };

  const triggerScan = async (rootFolderId: number) => {
    error.value = null;
    try {
      await request('/api/scanner/scans', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ root_folder_id: rootFolderId }),
      });
      isScanning.value = true;
      progress.value = null;
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to start scan');
    }
  };

  const removeProposal = (proposalId: number) => {
    proposals.value = proposals.value.filter((p) => p.id !== proposalId);
  };

  const approveProposal = async (proposalId: number) => {
    try {
      await request(`/api/scanner/proposals/${proposalId}/approve`, { method: 'POST' });
      removeProposal(proposalId);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to approve proposal');
      throw e;
    }
  };

  const rejectProposal = async (proposalId: number) => {
    try {
      await request(`/api/scanner/proposals/${proposalId}/reject`, { method: 'POST' });
      removeProposal(proposalId);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to reject proposal');
      throw e;
    }
  };

  const dismissProposal = async (proposalId: number) => {
    try {
      await request(`/api/scanner/proposals/${proposalId}/dismiss`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ proposal_id: proposalId, add_to_dismissed_paths: true }),
      });
      removeProposal(proposalId);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to dismiss proposal');
      throw e;
    }
  };

  const bulkApprove = async (proposalIds: number[]) => {
    if (proposalIds.length === 0) return null;
    isBulkApproving.value = true;
    try {
      const data = await request('/api/scanner/proposals/bulk-approve', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ proposal_ids: proposalIds }),
      });
      await fetchProposals();
      return data as { approved: number; skipped: { proposal_id: number; reason: string }[] };
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Bulk approve failed');
      throw e;
    } finally {
      isBulkApproving.value = false;
    }
  };

  const searchHardcover = async (query: string): Promise<HardcoverSearchResult[]> => {
    return request('/api/scanner/hardcover/search', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ query, limit: 10 }),
    });
  };

  const searchLibrary = async (query: string): Promise<Book[]> => {
    const data = await request(
      `/api/library/books?search=${encodeURIComponent(query)}&limit=20&sort_by=title&sort_order=asc`
    );
    return data.books || [];
  };

  const linkHardcover = async (proposalId: number, hardcoverId: number) => {
    try {
      await request(`/api/scanner/proposals/${proposalId}/link-hardcover`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ proposal_id: proposalId, hardcover_id: hardcoverId }),
      });
      removeProposal(proposalId);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to link book');
      throw e;
    }
  };

  const linkBook = async (proposalId: number, bookId: number) => {
    try {
      await request(`/api/scanner/proposals/${proposalId}/link-book`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ proposal_id: proposalId, book_id: bookId }),
      });
      removeProposal(proposalId);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to link book');
      throw e;
    }
  };

  const handleWebSocketEvent = (event: string, data: unknown) => {
    switch (event) {
      case 'scan_started':
        isScanning.value = true;
        progress.value = null;
        break;
      case 'scan_progress':
        progress.value = data as ScanProgressEvent;
        break;
      case 'scan_completed':
        isScanning.value = false;
        progress.value = null;
        fetchLastScan();
        fetchProposals();
        break;
      case 'scan_failed': {
        isScanning.value = false;
        progress.value = null;
        const failure = data as { error_message?: string };
        setError(failure.error_message || 'Scan failed');
        fetchLastScan();
        break;
      }
    }
  };

  return {
    rootFolders,
    lastScan,
    progress,
    proposals,
    matchedProposals,
    unmatchedProposals,
    isScanning,
    isLoading,
    isBulkApproving,
    error,
    fetchRootFolders,
    fetchLastScan,
    fetchProposals,
    triggerScan,
    approveProposal,
    rejectProposal,
    dismissProposal,
    bulkApprove,
    searchHardcover,
    searchLibrary,
    linkHardcover,
    linkBook,
    handleWebSocketEvent,
  };
});
