export interface MastodonMediaAttachment {
  id: string;
  type: string;
  url: string;
  preview_url: string;
  remote_url?: string;
  description?: string;
  blurhash?: string;
}

export interface MastodonStatus {
  id: string;
  content: string;
  created_at: string;
  visibility: string;
  account: MastodonAccount;
  in_reply_to_id: string | null;
  reblog?: MastodonStatus;
  media_attachments: MastodonMediaAttachment[];
  mentions: unknown[];
  tags: unknown[];
  emojis: unknown[];
  replies_count: number;
  reblogs_count: number;
  favourites_count: number;
  favourited: boolean;
  reblogged: boolean;
  muted: boolean;
  bookmarked: boolean;
  pinned: boolean;
  url: string;
  uri: string;
}

export interface MastodonAccount {
  id: string;
  username?: string;
  acct: string;
  display_name: string;
  avatar: string;
  avatar_static?: string;
  header?: string;
  header_static?: string;
  locked?: boolean;
  bot: boolean;
  created_at?: string | null;
  note: string;
  url: string;
  followers_count?: number;
  following_count?: number;
  statuses_count?: number;
  last_status_at?: string | null;
  fields?: unknown[];
  counts?: {
    followers: number;
    following: number;
    statuses: number;
  };
  is_following?: boolean;
  is_followed_by?: boolean;
  cache_state?: AccountCacheState;
}

export interface AccountCacheState {
  cached_posts: number;
  latest_cached_post_at: string | null;
  is_stale: boolean;
  stale_reason: string;
}

export interface AccountCatchupStatus {
  running: boolean;
  finished: boolean;
  acct: string;
  mode: 'recent' | 'deep';
  stage: string;
  pages_fetched: number;
  posts_fetched: number;
  new_posts: number;
  updated_posts: number;
  started_at: string;
  finished_at: string | null;
  error: string | null;
  cancel_requested: boolean;
}

export interface AdminStatus {
  connected: boolean;
  last_sync: string;
  current_user: MastodonAccount | null;
}

export interface Identity {
  id: number;
  acct: string;
  display_name: string;
  avatar_url: string;
  is_active: boolean;
  base_url: string;
}

export interface MastodonContext {
  ancestors: MastodonStatus[];
  descendants: MastodonStatus[];
  target: MastodonStatus;
}

export interface CatchupStatus {
  running: boolean;
  mode: 'urgent' | 'trickle';
  done: number;
  total: number;
  current_acct: string | null;
  errors: number;
  started_at: string;
  finished_at: string | null;
  rate_limited: boolean;
}

export interface CatchupQueueEntry {
  acct: string;
  display_name: string;
  is_followed_by: boolean;
  last_status_at: string | null;
}

export interface CatchupQueue {
  identity_id: number;
  queue: CatchupQueueEntry[];
}

export interface OwnAccountCatchupResult {
  status: 'success' | 'error' | 'skipped' | 'not_found';
  count?: number;
  msg?: string;
}

export interface BulkSyncJobStatus {
  kind: string;
  identity_id: number;
  started_at: number;
  done: number;
  total: number | null;
  stage: string;
  finished: boolean;
  ok: boolean;
  error: string | null;
  result: Record<string, number> | null;
  cancel_requested: boolean;
}

// Content Hub

export interface ContentHubTerm {
  id: number;
  term: string;
  term_type: 'hashtag' | 'search';
}

export interface ContentHubGroup {
  id: number;
  name: string;
  slug: string;
  source_type: 'client_bundle' | 'server_follow';
  is_read_only: boolean;
  last_fetched_at: string | null;
  terms: ContentHubTerm[];
}

export interface ContentHubPost {
  id: string;
  content: string;
  author_acct: string;
  author_avatar: string;
  author_display_name: string;
  created_at: string;
  media_attachments: unknown[];
  tags: unknown[];
  counts: { replies: number; reblogs: number; likes: number };
  has_video: boolean;
  has_link: boolean;
  is_reblog: boolean;
  is_reply: boolean;
}

export interface ContentHubGroupPostsResponse {
  items: ContentHubPost[];
  next_cursor: string | null;
  stale: boolean;
  group: { id: number; name: string; last_fetched_at: string | null };
}

// Admin bundle models

export interface AdminBundleTerm {
  id: number;
  term: string;
  term_type: 'hashtag' | 'search';
  normalized_term: string;
}

export interface AdminBundle {
  id: number;
  name: string;
  slug: string;
  source_type: 'client_bundle' | 'server_follow';
  is_read_only: boolean;
  last_fetched_at: string | null;
  created_at: string;
  updated_at: string;
  terms: AdminBundleTerm[];
}

// Analytics (DuckDB-backed)

export interface HashtagTrendRow {
  bucket_start: string;
  tag: string;
  count: number;
}

export interface ContentSearchRow {
  id: string;
  author_acct: string;
  created_at: string;
  content: string;
}

export interface HeatmapCell {
  dow: number;
  hour: number;
  count: number;
}

export interface ReposterRow {
  account_acct: string;
  current: number;
  prior: number;
  delta: number;
}

export interface NotificationTrendBucket {
  bucket_start: string;
  type: string;
  count: number;
}

export interface NotificationTrendActor {
  account_acct: string;
  count: number;
}

export interface NotificationTrendsResponse {
  by_type: NotificationTrendBucket[];
  by_actor: NotificationTrendActor[];
}

// Peeps Finder

export interface PeepsEntry {
  account_id: string;
  acct: string;
  display_name: string;
  avatar: string;
  is_following: boolean;
  is_followed_by: boolean;
  statuses_count: number;
  in_score: number;
  out_score: number;
  combined_score: number;
}

export interface EngagementMatrix {
  inner_circle: PeepsEntry[];
  fans: PeepsEntry[];
  idols: PeepsEntry[];
  broadcasters: PeepsEntry[];
}

export interface DossierHashtag {
  tag: string;
  count: number;
}

export interface DossierInteractionWindow {
  them_to_me: number;
  me_to_them: number;
}

export interface DossierMediaProfile {
  total: number;
  has_media: number;
  has_video: number;
  has_link: number;
}

export interface Dossier {
  id: string;
  acct: string;
  display_name: string;
  avatar: string;
  header: string;
  url: string;
  note: string;
  fields: unknown[];
  bot: boolean;
  followers_count: number;
  following_count: number;
  statuses_count: number;
  is_following: boolean;
  is_followed_by: boolean;
  post_reply_ratio: number | null;
  top_hashtags: DossierHashtag[];
  interaction_history: Record<string, DossierInteractionWindow>;
  media_profile: DossierMediaProfile;
  is_stale: boolean;
}

export interface GroupPerson {
  acct: string;
  display_name: string;
  avatar: string;
  note: string;
  is_following: boolean;
  is_followed_by: boolean;
  post_count_in_group: number;
  last_in_group: string | null;
  total_engagement_in_group: number;
}
