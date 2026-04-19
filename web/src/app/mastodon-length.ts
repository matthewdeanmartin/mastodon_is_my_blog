// Mastodon counts URLs as exactly 23 chars regardless of actual length.
// Ref: https://docs.joinmastodon.org/user/posting/#links
const URL_DISPLAY_LENGTH = 23;
const URL_RE = /https?:\/\/\S+/g;

export function mastodonLength(text: string): number {
  let len = text.length;
  for (const match of text.matchAll(URL_RE)) {
    len -= match[0].length;
    len += URL_DISPLAY_LENGTH;
  }
  return len;
}
