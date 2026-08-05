// API Types

// Library Types
export interface Author {
  id: number;
  name: string;
  hardcover_id: string | null;
  created_at: string;
}

export type BookStatus =
  | 'missing'
  | 'wanted'
  | 'searching'
  | 'grabbed'
  | 'downloading'
  | 'importing'
  | 'in_library'
  | 'failed'
  | 'PERMANENT_FAILED';

export interface FailureHistoryEntry {
  reason: string;
  timestamp: string;
  attempt: number;
}

export interface Book {
  id: number;
  title: string;
  author: Author;
  hardcover_id: string | null;
  isbn: string | null;
  description: string | null;
  publisher: string | null;
  language: string | null;
  tags: string[];
  rating: number | null;
  read_date: string | null;
  cover_url: string | null;
  series_name: string | null;
  series_position: number | null;
  status: BookStatus;
  root_folder_id: number;
  file_path: string | null;
  file_size: number | null;
  search_attempts: number;
  last_searched_at: string | null;
  created_at: string;
  updated_at: string;
  failure_reason: string | null;
  retry_count: number;
  failure_history: FailureHistoryEntry[] | null;
  kindle_delivery_status: KindleDeliveryStatus | null;
  kindle_delivery_attempts: number;
  kindle_first_pending_at: string | null;
  kindle_delivered_at: string | null;
  hardcover_status: string | null;
  kindle_pinned: boolean;
}

export type KindleDeliveryStatus = 'PENDING' | 'IN_PROGRESS' | 'DELIVERED' | 'SKIPPED';

export interface KindleStatus {
  kindle_id: string;
  name: string;
  hostname: string;
  configured: boolean;
  reachable: boolean;
  checked_at: string | null;
  cached?: boolean;
}

export interface KindleDeviceBook {
  name: string;
  size: number;
  modified: string | null;
}

export interface TransferProgress {
  book_id?: number;
  book_title: string;
  bytes_transferred: number;
  bytes_total: number;
  percentage: number;
  speed_bytes_per_sec: number;
  eta_seconds: number;
}

export interface KindleDeliveryProgress extends TransferProgress {
  book_id: number;
}

export interface KindleSyncPreview {
  success: boolean;
  transferred: number;
  skipped: number;
  failed: number;
  cleanup: number;
  dry_run: boolean;
  would_send: Array<{ book_id: number; title: string; remote_path: string }>;
  would_delete: string[];
}

export type FolderOrganization = 'flat' | 'author' | 'series' | 'author_series';

export interface RootFolder {
  id: number;
  name: string;
  path: string;
  folder_organization: FolderOrganization;
  created_at: string;
}

export type DownloadStatus =
  | 'queued'
  | 'downloading'
  | 'completed'
  | 'importing'
  | 'imported'
  | 'failed';

export interface DownloadBook {
  id: number;
  title: string;
  author: string | null;
  cover_url: string | null;
}

export interface Download {
  id: number;
  book_id: number;
  book: DownloadBook | null;
  torrent_hash: string;
  torrent_name: string;
  indexer_name: string;
  download_url: string;
  size: number;
  seeders: number;
  status: DownloadStatus;
  file_path: string | null;
  error_message: string | null;
  created_at: string;
  completed_at: string | null;
  progress?: number;
  download_speed?: number;
  eta?: number;
}

export interface SearchResult {
  guid: string;
  indexer_id: number;
  indexer: string;
  title: string;
  size: number;
  seeders: number;
  leechers: number;
  download_url: string;
  magnet_url: string;
  categories: number[];
  publish_date: string;
  age_days: number;
  rejections: string[];
  approved: boolean;
  // Phase 1 filter rewrite — server-side classification.
  // 'audiobook' and 'ebook-other' verdicts are filtered out server-side
  // and never reach the frontend.
  format_hint?: 'ebook' | 'unknown';
  format_reason?: string;
}

export interface BlocklistEntry {
  id: number;
  indexer: string;
  release_guid: string;
  title: string;
  reason: string | null;
  created_at: string;
}

// Config Types
export interface ProwlarrConfig {
  api_key: string;
  base_url: string;
}

export interface QBittorrentConfig {
  base_url: string;
  username: string;
  password: string;
  category: string;
}

export interface PipelineConfig {
  enabled: boolean;
  search_on_add: boolean;
  import_on_complete: boolean;
  kindle_sync_on_import: boolean;
  status_actions: {
    want_to_read: {
      download: boolean;
    };
    currently_reading: {
      download: boolean;
    };
    read: {
      download: boolean;
    };
  };
}

export interface LibraryConfig {
  root_folders: Array<{
    path: string;
    name: string;
    folder_organization: FolderOrganization;
  }>;
  download_path: string;
  naming_template: string;
}

export interface RenamePreviewItem {
  book_id: number;
  title: string;
  root_folder_id: number;
  old_path: string;
  new_path: string;
  changed: boolean;
  error: string | null;
}

export interface RenamePreviewResult {
  total: number;
  changed_count: number;
  items: RenamePreviewItem[];
}

export interface RenameApplyResult {
  total: number;
  renamed: number;
  skipped: number;
  failed: number;
  items: Array<RenamePreviewItem & { status: 'renamed' | 'skipped' | 'failed' }>;
}

export interface Kindle {
  id: string;
  name: string;
  hostname: string;
  port: number;
  username: string;
  password?: string;
  ssh_key_path?: string;
  destination_path: string;
}

export interface Schedule {
  id: string;
  name: string;
  cron_expression: string;
  enabled: boolean;
  kindle_device: string | null;
  dry_run: boolean;
  last_run_at: string | null;
  next_run_at: string | null;
}

export interface Config {
  hardcover: {
    api_token: string;
    api_url: string;
  };
  prowlarr: ProwlarrConfig;
  qbittorrent: QBittorrentConfig;
  kindles: Kindle[];
  pipeline: PipelineConfig;
  matching: {
    use_isbn: boolean;
    use_fuzzy: boolean;
    fuzzy_threshold: number;
  };
  sync: {
    include_statuses: {
      want_to_read: boolean;
      currently_reading: boolean;
      read: boolean;
    };
  };
  transfer: {
    dry_run: boolean;
    sync_shelves: {
      want_to_read: boolean;
      currently_reading: boolean;
      read: boolean;
    };
    folder_organization: 'flat' | 'author' | 'series' | 'author_series';
    cleanup_enabled: boolean;
    cleanup_sdr_folders: boolean;
    cleanup_protected_paths: string[];
  };
  library: LibraryConfig;
  logging: {
    log_file: string;
    log_level: string;
    console_output: boolean;
  };
}

// WebSocket Events
export type PongEvent = Record<string, never>;

export interface BookWantedEvent {
  book_id: number;
  title: string;
  author: string;
}

export interface SearchStartedEvent {
  book_id: number;
  title: string;
  query: string;
}

export interface SearchCompletedEvent {
  book_id: number;
  results_count: number;
  best_result?: SearchResult;
}

export interface DownloadStartedEvent {
  download_id: number;
  book_id: number;
  torrent_name: string;
  size: number;
}

export interface DownloadProgressEvent {
  download_id: number;
  book_id: number;
  progress: number;
  download_speed: number;
  eta: number;
}

export interface DownloadCompletedEvent {
  download_id: number;
  book_id: number;
  file_path: string;
}

export interface ImportStartedEvent {
  download_id: number;
  book_id: number;
  file_path: string;
}

export interface ImportCompletedEvent {
  book_id: number;
  file_path: string;
  root_folder_id: number;
}

// Discriminated union for type-safe WebSocket message handling
export type WebSocketMessage =
  | { event: 'pong'; data: PongEvent }
  | { event: 'book_wanted'; data: BookWantedEvent }
  | { event: 'search_started'; data: SearchStartedEvent }
  | { event: 'search_completed'; data: SearchCompletedEvent }
  | { event: 'download_started'; data: DownloadStartedEvent }
  | { event: 'download_progress'; data: DownloadProgressEvent }
  | { event: 'download_completed'; data: DownloadCompletedEvent }
  | { event: 'import_started'; data: ImportStartedEvent }
  | { event: 'import_completed'; data: ImportCompletedEvent };

// Scanner / Library Import Types
export type ScanStatus = 'running' | 'completed' | 'failed' | 'cancelled';

export interface ScanSummary {
  id: number;
  root_folder_id: number;
  status: ScanStatus;
  started_at: string;
  finished_at: string | null;
  files_seen: number;
  files_matched: number;
  files_proposed: number;
  files_unmatched: number;
  files_failed: number;
  error_message: string | null;
}

export interface ScanProgressEvent {
  scan_id: number;
  root_folder_id: number;
  files_seen: number;
  files_matched: number;
  files_proposed: number;
  files_unmatched: number;
  files_failed: number;
  current_path: string | null;
  finished: boolean;
}

export type MatchProposalStatus =
  | 'pending'
  | 'approved'
  | 'rejected'
  | 'auto_linked'
  | 'superseded';

export interface MatchProposal {
  id: number;
  scan_id: number;
  root_folder_id: number;
  relative_path: string;
  file_size: number;
  candidate_book_id: number | null;
  match_method: string | null;
  score: number | null;
  status: MatchProposalStatus;
  created_at: string;
  decided_at: string | null;
  candidate_title: string | null;
  candidate_author: string | null;
  candidate_hardcover_id: string | null;
}

export interface HardcoverSearchResult {
  hardcover_id: number;
  title: string;
  author_names: string[];
  isbns: string[];
}

export interface BrowseEntry {
  name: string;
  type: 'dir' | 'file' | 'broken_symlink';
  is_symlink: boolean;
  size: number | null;
}

export interface BrowseResponse {
  current_path: string;
  parent_path: string | null;
  exists: boolean;
  is_dir: boolean;
  is_writable: boolean | null;
  entries: BrowseEntry[];
  truncated: boolean;
}

export type PathBrowserMode = 'local' | 'kindle';
