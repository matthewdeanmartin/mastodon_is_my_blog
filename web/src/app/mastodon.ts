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
  username: string;
  acct: string;
  display_name: string;
  avatar: string;
  avatar_static: string;
  header: string;
  header_static: string;
  locked: boolean;
  bot: boolean;
  created_at: string;
  note: string;
  url: string;
  followers_count: number;
  following_count: number;
  statuses_count: number;
  last_status_at: string;
  fields: unknown[];
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
}

export interface MastodonContext {
  ancestors: MastodonStatus[];
  descendants: MastodonStatus[];
  target: MastodonStatus;
}
