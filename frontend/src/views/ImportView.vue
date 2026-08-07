<script setup lang="ts">
import { computed, onMounted, ref } from 'vue';
import { useScannerStore } from '../stores/scanner';
import { useToast } from '../composables/useToast';
import ProposalLinkModal from '../components/ProposalLinkModal.vue';
import type { MatchProposal } from '@/types';

const store = useScannerStore();
const toast = useToast();

const selectedRootFolderId = ref<number | null>(null);
const selectedIds = ref<Set<number>>(new Set());
const linkModalOpen = ref(false);
const linkTarget = ref<MatchProposal | null>(null);
const busyIds = ref<Set<number>>(new Set());
const unmatchedShown = ref(50);

onMounted(async () => {
  await Promise.all([store.fetchRootFolders(), store.fetchLastScan(), store.fetchProposals()]);
  if (store.rootFolders.length > 0 && selectedRootFolderId.value === null) {
    selectedRootFolderId.value = store.rootFolders[0].id;
  }
});

const startScan = () => {
  if (selectedRootFolderId.value !== null) {
    store.triggerScan(selectedRootFolderId.value);
  }
};

const allMatchedSelected = computed(
  () =>
    store.matchedProposals.length > 0 &&
    store.matchedProposals.every((p) => selectedIds.value.has(p.id))
);

const toggleSelectAll = () => {
  if (allMatchedSelected.value) {
    selectedIds.value = new Set();
  } else {
    selectedIds.value = new Set(store.matchedProposals.map((p) => p.id));
  }
};

const toggleSelected = (id: number) => {
  const next = new Set(selectedIds.value);
  if (next.has(id)) {
    next.delete(id);
  } else {
    next.add(id);
  }
  selectedIds.value = next;
};

const approveSelected = async () => {
  const ids = [...selectedIds.value];
  try {
    const result = await store.bulkApprove(ids);
    selectedIds.value = new Set();
    if (result) {
      if (result.skipped.length > 0) {
        toast.info(`Imported ${result.approved} books (${result.skipped.length} skipped)`);
      } else {
        toast.success(`Imported ${result.approved} books`);
      }
    }
  } catch {
    // store surfaced the error banner already
  }
};

const withRowBusy = async (id: number, action: () => Promise<void>, successMessage?: string) => {
  busyIds.value = new Set(busyIds.value).add(id);
  try {
    await action();
    if (successMessage) toast.success(successMessage);
  } catch {
    // store surfaced the error banner already
  } finally {
    const next = new Set(busyIds.value);
    next.delete(id);
    busyIds.value = next;
  }
};

const approveOne = (p: MatchProposal) =>
  withRowBusy(p.id, () => store.approveProposal(p.id), `Imported "${p.candidate_title}"`);
const rejectOne = (p: MatchProposal) => withRowBusy(p.id, () => store.rejectProposal(p.id));
const dismissOne = (p: MatchProposal) =>
  withRowBusy(p.id, () => store.dismissProposal(p.id), 'File ignored for future scans');

const openLinkModal = (p: MatchProposal) => {
  linkTarget.value = p;
  linkModalOpen.value = true;
};

const methodLabel = (method: string | null): string => {
  switch (method) {
    case 'embedded_hardcover_id':
      return 'Embedded ID';
    case 'isbn':
      return 'ISBN';
    case 'normalized_exact':
      return 'Exact';
    case 'fuzzy':
      return 'Fuzzy';
    case 'filename':
      return 'Filename';
    case 'manual':
      return 'Manual';
    default:
      return method ?? '—';
  }
};

const scoreClass = (score: number | null): string => {
  if (score === null) return 'bg-stone-100 text-stone-600';
  if (score >= 99) return 'bg-success-100 text-success-700';
  if (score >= 90) return 'bg-ereader-100 text-ereader-700';
  return 'bg-amber-100 text-amber-700';
};

const formatSize = (bytes: number): string => {
  if (bytes >= 1024 * 1024) return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
  return `${(bytes / 1024).toFixed(0)} KB`;
};

const fileName = (relativePath: string): string =>
  relativePath.split('/').pop() ?? relativePath;

const fileDir = (relativePath: string): string => {
  const parts = relativePath.split('/');
  return parts.length > 1 ? parts.slice(0, -1).join('/') : '';
};

const visibleUnmatched = computed(() => store.unmatchedProposals.slice(0, unmatchedShown.value));
</script>

<template>
  <div class="space-y-6">
    <!-- Page Header -->
    <div class="page-header">
      <div class="flex flex-col sm:flex-row sm:items-end sm:justify-between gap-2">
        <div>
          <h1 class="page-title">Library Import</h1>
          <p class="page-subtitle">Scan your books folder and match existing files to your library</p>
        </div>
        <div class="flex items-center gap-2">
          <select
            v-if="store.rootFolders.length > 1"
            v-model="selectedRootFolderId"
            class="input py-2 w-auto"
          >
            <option v-for="folder in store.rootFolders" :key="folder.id" :value="folder.id">
              {{ folder.name }} ({{ folder.path }})
            </option>
          </select>
          <button
            @click="startScan"
            :disabled="store.isScanning || selectedRootFolderId === null"
            class="btn btn-primary"
          >
            <svg v-if="store.isScanning" class="animate-spin -ml-1 mr-2 h-4 w-4 text-white" fill="none" viewBox="0 0 24 24">
              <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="3"></circle>
              <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
            </svg>
            <svg v-else class="w-4 h-4 mr-2" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15"/>
            </svg>
            {{ store.isScanning ? 'Scanning...' : 'Scan Folder' }}
          </button>
        </div>
      </div>
    </div>

    <!-- No root folder configured -->
    <div v-if="store.rootFolders.length === 0 && !store.isLoading" class="bg-amber-50 border border-amber-200 rounded-xl p-4 flex items-start gap-3">
      <svg class="w-5 h-5 text-amber-500 shrink-0 mt-0.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z"/>
      </svg>
      <div>
        <p class="text-sm font-medium text-amber-800">No root folder configured</p>
        <p class="text-sm text-amber-600 mt-0.5">
          Add a root folder in
          <router-link to="/settings" class="underline hover:text-amber-800">Settings</router-link>
          first, then scan it here.
        </p>
      </div>
    </div>

    <!-- Error Banner -->
    <div v-if="store.error" class="bg-error-50 border border-error-200 rounded-xl p-4 flex items-start gap-3">
      <svg class="w-5 h-5 text-error-500 shrink-0 mt-0.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 8v4m0 4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z"/>
      </svg>
      <p class="text-sm text-error-700 flex-1">{{ store.error }}</p>
    </div>

    <!-- Scan Progress -->
    <div v-if="store.isScanning" class="card p-5">
      <div class="flex items-center gap-3 mb-3">
        <svg class="animate-spin h-5 w-5 text-ereader-600" fill="none" viewBox="0 0 24 24">
          <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="3"></circle>
          <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
        </svg>
        <p class="font-medium text-stone-900">Scanning folder...</p>
      </div>
      <div v-if="store.progress" class="space-y-2">
        <div class="grid grid-cols-2 sm:grid-cols-4 gap-3 text-center">
          <div class="bg-stone-50 rounded-lg py-2">
            <p class="text-lg font-semibold text-stone-900">{{ store.progress.files_seen }}</p>
            <p class="text-xs text-stone-500">Files seen</p>
          </div>
          <div class="bg-stone-50 rounded-lg py-2">
            <p class="text-lg font-semibold text-success-600">{{ store.progress.files_matched + store.progress.files_proposed }}</p>
            <p class="text-xs text-stone-500">Matched</p>
          </div>
          <div class="bg-stone-50 rounded-lg py-2">
            <p class="text-lg font-semibold text-amber-600">{{ store.progress.files_unmatched }}</p>
            <p class="text-xs text-stone-500">Unmatched</p>
          </div>
          <div class="bg-stone-50 rounded-lg py-2">
            <p class="text-lg font-semibold text-error-600">{{ store.progress.files_failed }}</p>
            <p class="text-xs text-stone-500">Failed</p>
          </div>
        </div>
        <p v-if="store.progress.current_path" class="text-xs text-stone-400 truncate">
          {{ store.progress.current_path }}
        </p>
      </div>
    </div>

    <!-- Last Scan Summary -->
    <div v-else-if="store.lastScan" class="card p-4">
      <div class="flex flex-wrap items-center gap-x-6 gap-y-2 text-sm">
        <span class="text-stone-500">
          Last scan:
          <span class="font-medium" :class="store.lastScan.status === 'failed' ? 'text-error-600' : 'text-stone-900'">
            {{ store.lastScan.status }}
          </span>
        </span>
        <span class="text-stone-500">{{ store.lastScan.files_seen }} files</span>
        <span class="text-success-600">{{ store.lastScan.files_matched + store.lastScan.files_proposed }} matched</span>
        <span class="text-amber-600">{{ store.lastScan.files_unmatched }} unmatched</span>
        <span v-if="store.lastScan.files_failed > 0" class="text-error-600">
          {{ store.lastScan.files_failed }} unreadable
        </span>
        <span v-if="store.lastScan.finished_at" class="text-stone-400 ml-auto">
          {{ new Date(store.lastScan.finished_at + 'Z').toLocaleString() }}
        </span>
      </div>
      <p v-if="store.lastScan.error_message" class="text-sm text-error-600 mt-2">
        {{ store.lastScan.error_message }}
      </p>
    </div>

    <!-- Loading -->
    <div v-if="store.isLoading" class="flex justify-center py-16">
      <div class="flex items-center gap-3 text-stone-500">
        <svg class="animate-spin h-6 w-6 text-ereader-600" fill="none" viewBox="0 0 24 24">
          <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="3"></circle>
          <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
        </svg>
        <span class="text-sm font-medium">Loading proposals...</span>
      </div>
    </div>

    <template v-else>
      <!-- Matched Proposals -->
      <div v-if="store.matchedProposals.length > 0" class="card overflow-hidden">
        <div class="flex items-center justify-between px-4 py-3 border-b border-stone-200 bg-stone-50/50">
          <div class="flex items-center gap-3">
            <h2 class="font-semibold text-stone-900">Matched Files</h2>
            <span class="text-xs text-stone-500">{{ store.matchedProposals.length }} pending</span>
          </div>
          <button
            @click="approveSelected"
            :disabled="selectedIds.size === 0 || store.isBulkApproving"
            class="btn btn-primary py-1.5 px-3 text-xs"
          >
            <svg v-if="store.isBulkApproving" class="animate-spin -ml-0.5 mr-1.5 h-3.5 w-3.5" fill="none" viewBox="0 0 24 24">
              <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="3"></circle>
              <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
            </svg>
            Import Selected ({{ selectedIds.size }})
          </button>
        </div>
        <div class="overflow-x-auto">
          <table class="w-full text-left border-collapse">
            <thead>
              <tr class="border-b border-stone-200 bg-stone-50/50">
                <th class="px-4 py-3 w-10">
                  <input
                    type="checkbox"
                    :checked="allMatchedSelected"
                    @change="toggleSelectAll"
                    class="rounded border-stone-300 text-ereader-600 focus:ring-ereader-500"
                  />
                </th>
                <th class="px-4 py-3 text-xs font-medium text-stone-500 uppercase tracking-wider">File</th>
                <th class="px-4 py-3 text-xs font-medium text-stone-500 uppercase tracking-wider">Matched Book</th>
                <th class="px-4 py-3 text-xs font-medium text-stone-500 uppercase tracking-wider">Match</th>
                <th class="px-4 py-3 text-xs font-medium text-stone-500 uppercase tracking-wider text-right">Actions</th>
              </tr>
            </thead>
            <tbody class="divide-y divide-stone-100">
              <tr
                v-for="proposal in store.matchedProposals"
                :key="proposal.id"
                class="hover:bg-stone-50/50 transition-colors"
                :class="busyIds.has(proposal.id) ? 'opacity-50 pointer-events-none' : ''"
              >
                <td class="px-4 py-3">
                  <input
                    type="checkbox"
                    :checked="selectedIds.has(proposal.id)"
                    @change="toggleSelected(proposal.id)"
                    class="rounded border-stone-300 text-ereader-600 focus:ring-ereader-500"
                  />
                </td>
                <td class="px-4 py-3 max-w-xs">
                  <p class="text-sm font-medium text-stone-900 truncate" :title="proposal.relative_path">
                    {{ fileName(proposal.relative_path) }}
                  </p>
                  <p class="text-xs text-stone-400 truncate">
                    {{ fileDir(proposal.relative_path) }}<span v-if="fileDir(proposal.relative_path)"> &middot; </span>{{ formatSize(proposal.file_size) }}
                  </p>
                </td>
                <td class="px-4 py-3 max-w-xs">
                  <router-link
                    v-if="proposal.candidate_book_id"
                    :to="{ name: 'book-detail', params: { id: proposal.candidate_book_id } }"
                    class="text-sm font-medium text-stone-900 hover:text-ereader-600 transition-colors block truncate"
                    :title="proposal.candidate_title ?? undefined"
                  >
                    {{ proposal.candidate_title }}
                  </router-link>
                  <p class="text-xs text-stone-500 truncate">{{ proposal.candidate_author || 'Unknown Author' }}</p>
                </td>
                <td class="px-4 py-3">
                  <span
                    class="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-medium"
                    :class="scoreClass(proposal.score)"
                  >
                    {{ methodLabel(proposal.match_method) }}
                    <span v-if="proposal.score !== null">{{ Math.round(proposal.score) }}%</span>
                  </span>
                </td>
                <td class="px-4 py-3 text-right whitespace-nowrap">
                  <button @click="approveOne(proposal)" class="btn btn-primary py-1 px-2.5 text-xs mr-1.5">
                    Import
                  </button>
                  <button @click="openLinkModal(proposal)" class="btn btn-secondary py-1 px-2.5 text-xs mr-1.5" title="Match to a different book">
                    Change
                  </button>
                  <button @click="rejectOne(proposal)" class="btn btn-secondary py-1 px-2.5 text-xs" title="Reject this match">
                    Reject
                  </button>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>

      <!-- Unmatched Files -->
      <div v-if="store.unmatchedProposals.length > 0" class="card overflow-hidden">
        <div class="flex items-center justify-between px-4 py-3 border-b border-stone-200 bg-stone-50/50">
          <div class="flex items-center gap-3">
            <h2 class="font-semibold text-stone-900">Unmatched Files</h2>
            <span class="text-xs text-stone-500">{{ store.unmatchedProposals.length }} files with no library match</span>
          </div>
        </div>
        <div class="divide-y divide-stone-100">
          <div
            v-for="proposal in visibleUnmatched"
            :key="proposal.id"
            class="flex items-center justify-between gap-3 px-4 py-2.5 hover:bg-stone-50/50 transition-colors"
            :class="busyIds.has(proposal.id) ? 'opacity-50 pointer-events-none' : ''"
          >
            <div class="min-w-0">
              <p class="text-sm font-medium text-stone-900 truncate" :title="proposal.relative_path">
                {{ fileName(proposal.relative_path) }}
              </p>
              <p class="text-xs text-stone-400 truncate">
                {{ fileDir(proposal.relative_path) }}<span v-if="fileDir(proposal.relative_path)"> &middot; </span>{{ formatSize(proposal.file_size) }}
              </p>
            </div>
            <div class="shrink-0 whitespace-nowrap">
              <button @click="openLinkModal(proposal)" class="btn btn-primary py-1 px-2.5 text-xs mr-1.5">
                Find Match
              </button>
              <button @click="dismissOne(proposal)" class="btn btn-secondary py-1 px-2.5 text-xs" title="Ignore this file in future scans">
                Ignore
              </button>
            </div>
          </div>
        </div>
        <div v-if="store.unmatchedProposals.length > unmatchedShown" class="px-4 py-3 border-t border-stone-200 text-center">
          <button @click="unmatchedShown += 100" class="btn btn-secondary py-1.5 px-4 text-xs">
            Show more ({{ store.unmatchedProposals.length - unmatchedShown }} remaining)
          </button>
        </div>
      </div>

      <!-- Empty State -->
      <div v-if="store.proposals.length === 0 && !store.isScanning" class="card">
        <div class="empty-state">
          <div class="empty-state-icon">
            <svg fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M3 7v10a2 2 0 002 2h14a2 2 0 002-2V9a2 2 0 00-2-2h-6l-2-2H5a2 2 0 00-2 2z"/>
            </svg>
          </div>
          <p class="empty-state-title">No pending imports</p>
          <p class="empty-state-description">
            Scan your books folder to find files that can be matched to your library.
          </p>
        </div>
      </div>
    </template>

    <ProposalLinkModal
      v-model="linkModalOpen"
      :proposal="linkTarget"
      @linked="linkTarget = null"
    />
  </div>
</template>
