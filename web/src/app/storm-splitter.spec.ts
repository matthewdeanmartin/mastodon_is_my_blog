import { stormSplit, chainNodes } from './storm-splitter';
import { DraftNode } from './mastodon';

function makeNode(body: string, overrides: Partial<DraftNode> = {}): DraftNode {
  return {
    client_id: crypto.randomUUID(),
    parent_client_id: null,
    mode: 'single',
    body,
    spoiler_text: null,
    visibility: 'public',
    ...overrides,
  };
}

describe('stormSplit', () => {
  it('returns a single manual node when the text fits', () => {
    const node = makeNode('Short post.');
    const result = stormSplit(node, { maxChars: 100 });

    expect(result.length).toBe(1);
    expect(result[0].mode).toBe('manual');
    expect(result[0].body).toBe('Short post.');
  });

  it('returns a single manual node for empty/whitespace body', () => {
    const result = stormSplit(makeNode('   '));
    expect(result.length).toBe(1);
    expect(result[0].mode).toBe('manual');
  });

  it('splits long text into chunks within the limit', () => {
    const sentences = Array.from({ length: 6 }, (_, i) => `Sentence number ${i + 1} here.`);
    const node = makeNode(sentences.join(' '));

    const result = stormSplit(node, { maxChars: 60 });

    expect(result.length).toBeGreaterThan(1);
    for (const chunk of result) {
      expect(chunk.body.length).toBeLessThanOrEqual(60);
      expect(chunk.mode).toBe('manual');
    }
    // No content lost
    expect(result.map((c) => c.body).join(' ')).toBe(sentences.join(' '));
  });

  it('appends (i/N) counters that stay within the limit', () => {
    const sentences = Array.from({ length: 5 }, (_, i) => `Alpha beta gamma ${i}.`);
    const node = makeNode(sentences.join(' '));

    const result = stormSplit(node, { maxChars: 40, addCounter: true });

    expect(result.length).toBeGreaterThan(1);
    result.forEach((chunk, i) => {
      expect(chunk.body).toMatch(new RegExp(`\\(${i + 1}/${result.length}\\)$`));
      expect(chunk.body.length).toBeLessThanOrEqual(40);
    });
  });

  it('keeps chunks within the limit even with 10+ chunks (wide counter suffix)', () => {
    // Force many chunks: each sentence fills a chunk on its own.
    const sentences = Array.from({ length: 15 }, (_, i) => `Item ${String(i).padStart(2, '0')}.`);
    const node = makeNode(sentences.join(' '));

    const result = stormSplit(node, { maxChars: 20, addCounter: true });

    expect(result.length).toBeGreaterThanOrEqual(10);
    for (const chunk of result) {
      // " (12/15)" is 8 chars — the naive 7-char reserve overflowed here.
      expect(chunk.body.length).toBeLessThanOrEqual(20);
    }
  });

  it('preserves spoiler text and visibility on every chunk', () => {
    const sentences = Array.from({ length: 6 }, (_, i) => `Sentence number ${i + 1} here.`);
    const node = makeNode(sentences.join(' '), { spoiler_text: 'cw', visibility: 'unlisted' });

    const result = stormSplit(node, { maxChars: 60 });

    expect(result.length).toBeGreaterThan(1);
    for (const chunk of result) {
      expect(chunk.spoiler_text).toBe('cw');
      expect(chunk.visibility).toBe('unlisted');
    }
  });

  it('first chunk inherits the source parent, later chunks start unwired', () => {
    const sentences = Array.from({ length: 6 }, (_, i) => `Sentence number ${i + 1} here.`);
    const node = makeNode(sentences.join(' '), { parent_client_id: 'parent-123' });

    const result = stormSplit(node, { maxChars: 60 });

    expect(result[0].parent_client_id).toBe('parent-123');
    for (const chunk of result.slice(1)) {
      expect(chunk.parent_client_id).toBeNull();
    }
  });
});

describe('chainNodes', () => {
  it('returns empty array for no nodes', () => {
    expect(chainNodes([], 'root')).toEqual([]);
  });

  it('chains each node to the previous one, first to the given parent', () => {
    const nodes = [makeNode('a'), makeNode('b'), makeNode('c')];

    const chained = chainNodes(nodes, 'root-id');

    expect(chained[0].parent_client_id).toBe('root-id');
    expect(chained[1].parent_client_id).toBe(chained[0].client_id);
    expect(chained[2].parent_client_id).toBe(chained[1].client_id);
  });

  it('does not mutate the input nodes', () => {
    const nodes = [makeNode('a'), makeNode('b')];
    const originalParent = nodes[1].parent_client_id;

    chainNodes(nodes, 'root-id');

    expect(nodes[1].parent_client_id).toBe(originalParent);
  });
});
