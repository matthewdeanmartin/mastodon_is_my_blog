import { DraftNode } from './mastodon';

const DEFAULT_LIMIT = 500;
// Reserve space for " (n/N)" suffix when counter is on
const COUNTER_SUFFIX_LEN = 7;

/**
 * Split a single DraftNode (mode:'single') into N manual nodes.
 * Uses Intl.Segmenter for sentence boundaries when available,
 * falls back to splitting on ". " otherwise.
 */
export function stormSplit(
  source: DraftNode,
  options: { maxChars?: number; addCounter?: boolean } = {},
): DraftNode[] {
  const limit = options.maxChars ?? DEFAULT_LIMIT;
  const addCounter = options.addCounter ?? false;
  const budget = addCounter ? limit - COUNTER_SUFFIX_LEN : limit;

  const text = source.body.trim();
  if (!text) return [{ ...source, mode: 'manual' }];

  const segments = splitToSegments(text);
  const chunks = greedyPack(segments, budget);

  if (chunks.length <= 1) {
    return [{ ...source, body: text, mode: 'manual' }];
  }

  return chunks.map((body, i) => {
    const suffix = addCounter ? ` (${i + 1}/${chunks.length})` : '';
    return {
      client_id: crypto.randomUUID(),
      parent_client_id: i === 0 ? source.parent_client_id : null, // wired up by caller
      mode: 'manual' as const,
      body: body + suffix,
      spoiler_text: source.spoiler_text,
      visibility: source.visibility,
    };
  });
}

/** Chain nodes parent→child in sequence, starting from parentId. */
export function chainNodes(nodes: DraftNode[], parentId: string | null): DraftNode[] {
  if (nodes.length === 0) return [];
  const result = nodes.map((n, i) => ({ ...n }));
  result[0].parent_client_id = parentId;
  for (let i = 1; i < result.length; i++) {
    result[i].parent_client_id = result[i - 1].client_id;
  }
  return result;
}

function splitToSegments(text: string): string[] {
  const paragraphs = text.split(/\n{2,}/);
  const segments: string[] = [];

  for (const para of paragraphs) {
    const trimmed = para.trim();
    if (!trimmed) continue;

    // Try Intl.Segmenter for sentence splitting
    if (typeof Intl !== 'undefined' && 'Segmenter' in Intl) {
      try {
        const SegmenterCtor = (
          Intl as unknown as Record<
            string,
            new (
              l: undefined,
              o: { granularity: string },
            ) => { segment(s: string): Iterable<{ segment: string }> }
          >
        )['Segmenter'];
        const segmenter = new SegmenterCtor(undefined, { granularity: 'sentence' });
        for (const seg of segmenter.segment(trimmed)) {
          const s = seg.segment.trim();
          if (s) segments.push(s);
        }
        continue;
      } catch {
        // fall through
      }
    }

    // Fallback: split on ". " or ".\n"
    const sentences = trimmed.split(/(?<=\.)\s+/);
    for (const s of sentences) {
      const t = s.trim();
      if (t) segments.push(t);
    }
  }

  return segments.length ? segments : [text.trim()];
}

function greedyPack(segments: string[], budget: number): string[] {
  const chunks: string[] = [];
  let current = '';

  for (const seg of segments) {
    // Single segment exceeds budget — emit as its own chunk anyway
    if (seg.length > budget) {
      if (current) {
        chunks.push(current.trim());
        current = '';
      }
      chunks.push(seg.trim());
      continue;
    }

    const joined = current ? current + ' ' + seg : seg;
    if (joined.length <= budget) {
      current = joined;
    } else {
      if (current) chunks.push(current.trim());
      current = seg;
    }
  }

  if (current.trim()) chunks.push(current.trim());
  return chunks;
}
