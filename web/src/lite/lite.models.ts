export interface LiteMediaAttachment {
  id: string;
  type: 'image' | 'video' | 'gifv' | 'audio' | 'unknown';
  url: string;
  preview_url: string;
  description: string | null;
}

export interface LiteAccount {
  id: string;
  username: string;
  acct: string;
  display_name: string;
  avatar: string;
  note: string;
  url: string;
  followers_count: number;
  following_count: number;
  statuses_count: number;
  bot?: boolean;
  locked?: boolean;
  last_status_at?: string | null;
}

export interface LiteTag {
  name: string;
}

export interface LiteStatus {
  id: string;
  content: string;
  spoiler_text: string;
  created_at: string;
  url: string | null;
  visibility: string;
  in_reply_to_id: string | null;
  in_reply_to_account_id?: string | null;
  account: LiteAccount;
  reblog: LiteStatus | null;
  media_attachments: LiteMediaAttachment[];
  replies_count: number;
  reblogs_count: number;
  favourites_count: number;
  tags?: LiteTag[];
}

export interface LiteContext {
  ancestors: LiteStatus[];
  descendants: LiteStatus[];
}

export interface LiteConnection {
  version: 1;
  instanceUrl: string;
  clientId: string;
  clientSecret: string;
  accessToken: string;
  scope: string;
  account: LiteAccount;
}

export interface PendingOAuth {
  version: 1;
  instanceUrl: string;
  clientId: string;
  clientSecret: string;
  redirectUri: string;
  state: string;
  verifier: string;
  createdAt: number;
}

export interface AppRegistration {
  client_id: string;
  client_secret: string;
}

export interface TokenResponse {
  access_token: string;
  scope: string;
}

export type LiteVisibility = 'public' | 'unlisted' | 'private' | 'direct';

export interface LiteDraft {
  version: 1;
  id: string;
  treeJson: string;
  language: string | null;
  updatedAt: number;
}

export type LiteNotificationType = 'mention' | 'favourite' | 'reblog' | 'status' | 'follow';

export interface LiteNotification {
  id: string;
  type: LiteNotificationType;
  created_at: string;
  account: LiteAccount;
}

export interface LiteRelationship {
  id: string;
  following: boolean;
  followed_by: boolean;
}

export type LitePeopleFilter =
  | 'all'
  | 'top_friends'
  | 'readers'
  | 'mutuals'
  | 'chatty'
  | 'idols'
  | 'broadcasters'
  | 'bots'
  | 'lively'
  | 'graveyard'
  | 'parasocials'
  | 'other';

export type LiteFilter =
  | 'posts'
  | 'storms'
  | 'shorts'
  | 'replies'
  | 'questions'
  | 'media'
  | 'links'
  | 'software'
  | 'news'
  | 'boosts';
export type LitePage = 'people' | 'content' | 'forums' | 'write' | 'analytics' | 'observability';

export type LiteForumFilter =
  | 'all'
  | 'questions'
  | 'friends_started'
  | 'popular'
  | 'recent'
  | 'mine'
  | 'participating';
