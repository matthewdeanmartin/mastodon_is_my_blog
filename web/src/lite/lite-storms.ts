import { LiteStatus } from './lite.models';

export interface LiteStorm {
  root: LiteStatus;
  replies: LiteStatus[];
}

/** Build storms strictly from same-author reply edges in the loaded window. */
export function buildLiteStorms(statuses: LiteStatus[]): LiteStorm[] {
  const posts = statuses.map((status) => status.reblog ?? status);
  const children = new Map<string, LiteStatus[]>();
  for (const post of posts) {
    if (!post.in_reply_to_id) continue;
    const siblings = children.get(post.in_reply_to_id) ?? [];
    siblings.push(post);
    children.set(post.in_reply_to_id, siblings);
  }

  const collectSelfReplies = (parent: LiteStatus, seen: Set<string>): LiteStatus[] => {
    const replies: LiteStatus[] = [];
    const direct = (children.get(parent.id) ?? [])
      .filter((child) => child.account.id === parent.account.id)
      .sort((left, right) => left.created_at.localeCompare(right.created_at));
    for (const child of direct) {
      if (seen.has(child.id)) continue;
      seen.add(child.id);
      replies.push(child, ...collectSelfReplies(child, seen));
    }
    return replies;
  };

  return posts
    .filter((post) => post.in_reply_to_id === null)
    .map((root) => ({ root, replies: collectSelfReplies(root, new Set([root.id])) }))
    .filter((storm) => storm.replies.length > 0)
    .sort((left, right) => right.root.created_at.localeCompare(left.root.created_at));
}
