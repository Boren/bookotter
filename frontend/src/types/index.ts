// API Types

export interface SyncRun {
  id: number;
  started_at: string;
  completed_at: string | null;
  status: 'running' | 'completed' | 'failed' | 'cancelled';
  trigger_type: 'manual' | 'scheduled';
  kindle_device: string | null;
  total_books: number;
  matched: number;
  transferred: number;
  failed: number;
  not_found: number;
  skipped: number;
  added_to_readarr: number;
  add_failures: number;
  cleaned_up: number;
  status_ids: number[];
  dry_run: boolean;
  error_message: string | null;
}

export interface BookResult {
  id: number;
  sync_run_id: number;
  hardcover_id: string | null;
  title: string;
  author: string | null;
  isbns: string[] | null;
  cover_url: string | null;
  status: string;
  reading_status: 'want_to_read' | 'currently_reading' | 'read' | null;
  match_method: string | null;
  match_score: number | null;
  readarr_book_id: number | null;
  file_path: string | null;
  file_size: number | null;
  error_message: string | null;
  processed_at: string;
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
  readarr: {
    api_key: string;
    base_url: string;
    path_mappings: Array<{
      readarr_path: string;
      local_path: string;
    }>;
    auto_add: {
      enabled: boolean;
      search_immediately: boolean;
    };
  };
  kindles: Kindle[];
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

export interface SyncStats {
  total_runs: number;
  successful_runs: number;
  total_books_processed: number;
  total_transferred: number;
  total_matched: number;
  total_not_found: number;
  total_failed: number;
  total_skipped: number;
  last_successful_sync: string | null;
}

// WebSocket Events
export interface SyncStartedEvent {
  sync_run_id: number;
  status_ids: number[];
  dry_run: boolean;
}

export interface BooksFetchedEvent {
  sync_run_id: number;
  total_books: number;
}

export interface BookCompletedEvent {
  sync_run_id: number;
  book_title: string;
}

export interface SyncFailedEvent {
  sync_run_id: number;
  error: string;
}

export type PongEvent = Record<string, never>;

export interface BookProgressEvent {
  sync_run_id: number;
  current: number;
  total: number;
  book: {
    title: string;
    author?: string;
    cover_url?: string;
    status: string;
    error_message?: string;
  };
}

export interface TransferProgressEvent {
  sync_run_id: number;
  book_title: string;
  bytes_transferred: number;
  bytes_total: number;
  percentage: number;
  speed_bytes_per_sec: number;
  eta_seconds: number;
}

export interface SyncCompletedEvent {
  sync_run_id: number;
  stats: {
    total_books: number;
    matched: number;
    transferred: number;
    failed: number;
    not_found: number;
    skipped: number;
    cleaned_up: number;
  };
}

// Discriminated union for type-safe WebSocket message handling
export type WebSocketMessage =
  | { event: 'sync_started'; data: SyncStartedEvent }
  | { event: 'books_fetched'; data: BooksFetchedEvent }
  | { event: 'book_progress'; data: BookProgressEvent }
  | { event: 'transfer_progress'; data: TransferProgressEvent }
  | { event: 'book_completed'; data: BookCompletedEvent }
  | { event: 'sync_completed'; data: SyncCompletedEvent }
  | { event: 'sync_failed'; data: SyncFailedEvent }
  | { event: 'pong'; data: PongEvent };
