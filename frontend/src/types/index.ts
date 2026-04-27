// API Types

// Library Types
export interface Author {
  id: number;
  name: string;
  hardcover_id: string | null;
  created_at: string;
}

export type BookStatus =
  | 'wanted'
  | 'searching'
  | 'grabbed'
  | 'downloading'
  | 'importing'
  | 'in_library'
  | 'failed';

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
  // Phase 1 filter rewrite — server-side classification.
  // 'audiobook' and 'ebook-other' verdicts are filtered out server-side
  // and never reach the frontend.
  format_hint?: 'ebook' | 'unknown';
  format_reason?: string;
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
      kindle_sync: boolean;
    };
    currently_reading: {
      download: boolean;
      kindle_sync: boolean;
    };
    read: {
      download: boolean;
      kindle_sync: boolean;
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
    skip_existing: boolean;
    folder_organization: 'flat' | 'author' | 'series' | 'author_series';
    cleanup_enabled: boolean;
    cleanup_sdr_folders: boolean;
    cleanup_protected_paths: string[];
  };
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
