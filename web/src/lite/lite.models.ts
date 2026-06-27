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
}

export interface LiteStatus {
  id: string;
  content: string;
  spoiler_text: string;
  created_at: string;
  url: string | null;
  visibility: string;
  in_reply_to_id: string | null;
  account: LiteAccount;
  reblog: LiteStatus | null;
  media_attachments: LiteMediaAttachment[];
  replies_count: number;
  reblogs_count: number;
  favourites_count: number;
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

export type LiteFilter = 'recent' | 'shorts' | 'replies' | 'media' | 'links' | 'boosts';
export type LitePage = 'home' | 'me' | 'media' | 'links' | 'about';
