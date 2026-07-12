import { HttpErrorResponse } from '@angular/common/http';
import { ChangeDetectionStrategy, Component, OnDestroy, OnInit, inject } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { LivePreviewPaneComponent } from '../app/live-preview-pane.component';
import { mastodonLength } from '../app/mastodon-length';
import { DraftNode } from '../app/mastodon';
import { PlainTextareaEditorComponent } from '../app/plain-textarea-editor.component';
import { chainNodes, stormSplit } from '../app/storm-splitter';
import { LiteMastodonService } from './lite-mastodon.service';
import { LiteDraft, LiteVisibility } from './lite.models';
import { LiteStorageService } from './lite-storage.service';

@Component({
  selector: 'app-lite-write',
  imports: [FormsModule, PlainTextareaEditorComponent, LivePreviewPaneComponent],
  templateUrl: './lite-write.component.html',
  styleUrl: './lite-write.component.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class LiteWriteComponent implements OnInit, OnDestroy {
  readonly storage = inject(LiteStorageService);
  private readonly mastodon = inject(LiteMastodonService);
  private autosaveTimer: ReturnType<typeof setTimeout> | null = null;

  drafts: LiteDraft[] = [];
  draft: LiteDraft | null = null;
  nodes: DraftNode[] = [];
  selectedId: string | null = null;
  language: string | null = null;
  dirty = false;
  saving = false;
  publishing = false;
  publishError: string | null = null;
  savedMessage: string | null = null;
  showPreview = false;
  addCounter = false;

  readonly mastodonLength = mastodonLength;
  readonly visibilityOptions: LiteVisibility[] = ['public', 'unlisted', 'private', 'direct'];

  get selected(): DraftNode | null {
    return this.nodes.find((node) => node.client_id === this.selectedId) ?? null;
  }

  get hasContent(): boolean {
    return this.nodes.some((node) => node.body.trim().length > 0);
  }

  get orderedNodes(): DraftNode[] {
    return topoSort(this.nodes);
  }

  get needsWritePermission(): boolean {
    const connection = this.storage.connection();
    return !!connection && !hasWriteScope(connection.scope);
  }

  get canPublish(): boolean {
    return this.hasContent && !this.needsWritePermission && !!this.storage.connection();
  }

  get canSplit(): boolean {
    return !!this.selected && this.selected.mode === 'single' && !!this.selected.body.trim();
  }

  ngOnInit(): void {
    const connection = this.storage.connection();
    this.drafts = connection ? this.storage.readDrafts(connection) : [];
    if (this.drafts.length) this.loadDraft(this.drafts[0]);
    else this.startNew(false);
  }

  ngOnDestroy(): void {
    if (this.autosaveTimer) clearTimeout(this.autosaveTimer);
    this.saveDraft(false);
  }

  selectNode(id: string): void {
    this.selectedId = id;
  }

  nodeDepth(node: DraftNode): number {
    let depth = 0;
    let current = node;
    while (current.parent_client_id) {
      const parent = this.nodes.find((item) => item.client_id === current.parent_client_id);
      if (!parent) break;
      depth += 1;
      current = parent;
    }
    return depth;
  }

  nodeLabel(node: DraftNode, index: number): string {
    return `${index + 1}. ${node.body.trim().slice(0, 40) || '(empty)'}`;
  }

  onBodyChange(value: string): void {
    if (!this.selected) return;
    this.selected.body = value;
    this.changed();
  }

  onSpoilerChange(value: string): void {
    if (!this.selected) return;
    this.selected.spoiler_text = value || null;
    this.changed();
  }

  onVisibilityChange(value: LiteVisibility): void {
    if (!this.selected) return;
    this.selected.visibility = value;
    this.changed();
  }

  onLanguageChange(value: string): void {
    this.language = value.trim() || null;
    this.changed();
  }

  addSelfReply(): void {
    if (!this.selected) return;
    const child = newNode(this.selected.client_id);
    this.nodes = [...this.nodes, child];
    this.selectedId = child.client_id;
    this.changed();
  }

  deleteNode(id: string): void {
    if (this.nodes.length === 1) return;
    const remove = new Set<string>();
    const collect = (nodeId: string): void => {
      remove.add(nodeId);
      this.nodes
        .filter((node) => node.parent_client_id === nodeId)
        .forEach((node) => collect(node.client_id));
    };
    collect(id);
    this.nodes = this.nodes.filter((node) => !remove.has(node.client_id));
    this.selectedId = this.nodes.at(-1)?.client_id ?? null;
    this.changed();
  }

  convertToStorm(): void {
    const source = this.selected;
    if (!source || !this.canSplit) return;
    const split = stormSplit(source, { maxChars: 500, addCounter: this.addCounter });
    if (split.length <= 1) {
      source.mode = 'manual';
      this.changed();
      return;
    }
    const chained = chainNodes(split, source.parent_client_id);
    const sourceIndex = this.nodes.findIndex((node) => node.client_id === source.client_id);
    const rest = this.nodes.filter((node) => node.client_id !== source.client_id);
    const lastId = chained.at(-1)!.client_id;
    for (const node of rest) {
      if (node.parent_client_id === source.client_id) node.parent_client_id = lastId;
    }
    this.nodes = [...rest.slice(0, sourceIndex), ...chained, ...rest.slice(sourceIndex)];
    this.selectedId = chained[0].client_id;
    this.changed();
  }

  openDraft(id: string): void {
    this.saveDraft(false);
    const draft = this.drafts.find((item) => item.id === id);
    if (draft) this.loadDraft(draft);
  }

  startNew(saveCurrent = true): void {
    if (saveCurrent) this.saveDraft(false);
    this.draft = null;
    this.nodes = [newNode(null)];
    this.selectedId = this.nodes[0].client_id;
    this.language = null;
    this.dirty = false;
    this.savedMessage = null;
    this.publishError = null;
  }

  saveDraft(showMessage = true): void {
    const connection = this.storage.connection();
    if (!connection || !this.dirty || !this.hasContent) return;
    this.saving = true;
    const saved: LiteDraft = {
      version: 1,
      id: this.draft?.id ?? crypto.randomUUID(),
      treeJson: JSON.stringify(this.nodes),
      language: this.language,
      updatedAt: Date.now(),
    };
    this.storage.saveDraft(connection, saved);
    this.draft = saved;
    this.drafts = this.storage.readDrafts(connection);
    this.dirty = false;
    this.saving = false;
    if (showMessage) this.savedMessage = 'Draft saved in this browser.';
  }

  discardDraft(): void {
    const connection = this.storage.connection();
    if (connection && this.draft) this.storage.deleteDraft(connection, this.draft.id);
    this.drafts = connection ? this.storage.readDrafts(connection) : [];
    this.startNew(false);
  }

  async publish(): Promise<void> {
    const connection = this.storage.connection();
    if (!connection || !this.canPublish) return;
    this.saveDraft(false);
    this.publishing = true;
    this.publishError = null;
    const publishedIds = new Map<string, string>();
    try {
      for (const node of this.orderedNodes) {
        if (!node.body.trim()) continue;
        const parentStatusId = node.parent_client_id
          ? (publishedIds.get(node.parent_client_id) ?? null)
          : null;
        const status = await this.mastodon.publishNode(
          connection,
          node,
          this.language,
          parentStatusId,
        );
        publishedIds.set(node.client_id, status.id);
      }
      if (this.draft) this.storage.deleteDraft(connection, this.draft.id);
      this.drafts = this.storage.readDrafts(connection);
      this.startNew(false);
      this.savedMessage = 'Published on Mastodon.';
    } catch (error: unknown) {
      this.publishError = publishErrorMessage(error, publishedIds.size);
    } finally {
      this.publishing = false;
    }
  }

  formatDate(timestamp: number): string {
    return new Date(timestamp).toLocaleString();
  }

  draftPreview(draft: LiteDraft): string {
    const nodes = JSON.parse(draft.treeJson) as DraftNode[];
    return (
      nodes
        .find((node) => node.body.trim())
        ?.body.trim()
        .slice(0, 55) || '(empty)'
    );
  }

  private loadDraft(draft: LiteDraft): void {
    const parsed = JSON.parse(draft.treeJson) as DraftNode[];
    this.draft = draft;
    this.nodes = parsed.length ? parsed : [newNode(null)];
    this.selectedId = this.nodes[0].client_id;
    this.language = draft.language;
    this.dirty = false;
    this.savedMessage = null;
    this.publishError = null;
  }

  private changed(): void {
    this.dirty = true;
    this.savedMessage = null;
    this.publishError = null;
    if (this.autosaveTimer) clearTimeout(this.autosaveTimer);
    this.autosaveTimer = setTimeout(() => this.saveDraft(false), 1500);
  }
}

function newNode(parentId: string | null): DraftNode {
  return {
    client_id: crypto.randomUUID(),
    parent_client_id: parentId,
    mode: 'single',
    body: '',
    spoiler_text: null,
    visibility: 'public',
  };
}

function topoSort(nodes: DraftNode[]): DraftNode[] {
  const result: DraftNode[] = [];
  const visited = new Set<string>();
  const visit = (id: string | null): void => {
    for (const child of nodes.filter((node) => node.parent_client_id === id)) {
      if (visited.has(child.client_id)) continue;
      visited.add(child.client_id);
      result.push(child);
      visit(child.client_id);
    }
  };
  visit(null);
  for (const node of nodes) if (!visited.has(node.client_id)) result.push(node);
  return result;
}

function hasWriteScope(scope: string): boolean {
  const scopes = new Set(scope.split(/\s+/));
  return scopes.has('write') || scopes.has('write:statuses');
}

function publishErrorMessage(error: unknown, publishedCount: number): string {
  const prefix = publishedCount ? `${publishedCount} post(s) published before the failure. ` : '';
  if (error instanceof HttpErrorResponse) {
    if (error.status === 401 || error.status === 403) {
      return `${prefix}Reconnect and approve post-writing access.`;
    }
    if (error.status === 422) return `${prefix}Mastodon rejected the next post. Check its length.`;
    return `${prefix}Mastodon returned HTTP ${error.status}; your local draft is safe.`;
  }
  return `${prefix}${error instanceof Error ? error.message : 'Publishing failed.'}`;
}
