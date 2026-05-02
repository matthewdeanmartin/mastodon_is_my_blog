import { Component, OnDestroy, OnInit, inject } from '@angular/core';
import { ActivatedRoute, Router } from '@angular/router';
import { Subject, debounceTime, takeUntil } from 'rxjs';
import { ApiService } from './api.service';
import { PlainTextareaEditorComponent } from './plain-textarea-editor.component';
import { ReplyContextPanelComponent } from './reply-context-panel.component';
import { LivePreviewPaneComponent } from './live-preview-pane.component';
import { GrammarHintsComponent } from './grammar-hints.component';
import { Draft, DraftIn, DraftNode, Identity, SpellcheckMatch } from './mastodon';
import { stormSplit, chainNodes } from './storm-splitter';
import { mastodonLength } from './mastodon-length';

import { FormsModule } from '@angular/forms';

type Visibility = 'public' | 'unlisted' | 'private' | 'direct';

@Component({
  selector: 'app-write',
  standalone: true,
  imports: [
    FormsModule,
    PlainTextareaEditorComponent,
    ReplyContextPanelComponent,
    LivePreviewPaneComponent,
    GrammarHintsComponent,
  ],
  templateUrl: 'write.component.html',
})
export class WriteComponent implements OnInit, OnDestroy {
  api = inject(ApiService);
  route = inject(ActivatedRoute);
  router = inject(Router);

  draft: Draft | null = null;
  identities: Identity[] = [];
  selectedIdentityId: number | null = null;

  nodes: DraftNode[] = [];
  selectedId: string | null = null;

  language: string | null = null;
  editorEngine = 'plain';
  replyToStatusId: string | null = null;

  dirty = false;
  saving = false;
  publishing = false;
  publishError: string | null = null;
  showPreview = false;
  addCounter = false;

  grammarMatches: SpellcheckMatch[] = [];
  grammarChecking = false;
  grammarError: string | null = null;
  ltEnabled = false;

  readonly mastodonLength = mastodonLength;

  readonly visibilityOptions: Visibility[] = ['public', 'unlisted', 'private', 'direct'];

  private destroy$ = new Subject<void>();
  private autosave$ = new Subject<void>();

  // ── Derived helpers ────────────────────────────────────────────────────

  get selected(): DraftNode | null {
    return this.nodes.find((n) => n.client_id === this.selectedId) ?? null;
  }

  get hasContent(): boolean {
    return this.nodes.some((n) => n.body.trim().length > 0);
  }

  /** Ordered list for the tree nav — walk parent→child order */
  get orderedNodes(): DraftNode[] {
    return this.topoSort(this.nodes);
  }

  nodeDepth(node: DraftNode): number {
    let depth = 0;
    let cur = node;
    while (cur.parent_client_id) {
      const parent = this.nodes.find((n) => n.client_id === cur.parent_client_id);
      if (!parent) break;
      depth++;
      cur = parent;
    }
    return depth;
  }

  nodeLabel(node: DraftNode, index: number): string {
    const preview = node.body.trim().slice(0, 40) || '(empty)';
    return `${index + 1}. ${preview}`;
  }

  // ── Lifecycle ──────────────────────────────────────────────────────────

  ngOnInit(): void {
    this.api.getIdentities().subscribe((ids) => {
      this.identities = ids;
      if (ids.length) this.selectedIdentityId = ids[0].id;
    });

    this.autosave$
      .pipe(debounceTime(1500), takeUntil(this.destroy$))
      .subscribe(() => this.saveDraft());

    const draftId = this.route.snapshot.paramMap.get('draftId');
    const replyTo = this.route.snapshot.paramMap.get('statusId');

    if (draftId) {
      this.api.getDraft(Number(draftId)).subscribe((d) => this.loadDraft(d));
    } else {
      if (replyTo) this.replyToStatusId = replyTo;
      this.nodes = [this.newNode(null)];
      this.selectedId = this.nodes[0].client_id;
    }
  }

  ngOnDestroy(): void {
    this.destroy$.next();
    this.destroy$.complete();
  }

  // ── Node mutations ─────────────────────────────────────────────────────

  selectNode(id: string): void {
    this.selectedId = id;
  }

  onBodyChange(value: string): void {
    if (!this.selected) return;
    this.selected.body = value;
    this.dirty = true;
    this.autosave$.next();
  }

  onSpoilerChange(value: string): void {
    if (!this.selected) return;
    this.selected.spoiler_text = value || null;
    this.dirty = true;
    this.autosave$.next();
  }

  onVisibilityChange(value: Visibility): void {
    if (!this.selected) return;
    this.selected.visibility = value;
    this.dirty = true;
    this.autosave$.next();
  }

  addSelfReply(): void {
    if (!this.selected) return;
    const child = this.newNode(this.selected.client_id);
    this.nodes.push(child);
    this.selectedId = child.client_id;
    this.dirty = true;
    this.autosave$.next();
  }

  deleteNode(id: string): void {
    // Refuse to delete the only node
    if (this.nodes.length === 1) return;
    // Also delete all descendants
    const toRemove = new Set<string>();
    const collect = (nid: string) => {
      toRemove.add(nid);
      this.nodes.filter((n) => n.parent_client_id === nid).forEach((n) => collect(n.client_id));
    };
    collect(id);
    this.nodes = this.nodes.filter((n) => !toRemove.has(n.client_id));
    if (this.selectedId && toRemove.has(this.selectedId)) {
      this.selectedId = this.nodes[this.nodes.length - 1]?.client_id ?? null;
    }
    this.dirty = true;
    this.autosave$.next();
  }

  // ── Storm split ────────────────────────────────────────────────────────

  get canSplit(): boolean {
    return (
      !!this.selected && this.selected.mode === 'single' && this.selected.body.trim().length > 0
    );
  }

  convertToStorm(): void {
    const source = this.selected;
    if (!source || !this.canSplit) return;

    const newNodes = stormSplit(source, { maxChars: 500, addCounter: this.addCounter });
    if (newNodes.length <= 1) {
      // Nothing to split — just flip to manual
      source.mode = 'manual';
      this.dirty = true;
      this.autosave$.next();
      return;
    }

    const chained = chainNodes(newNodes, source.parent_client_id);

    // Replace source node with the chain; preserve any existing siblings/children
    const sourceIndex = this.nodes.findIndex((n) => n.client_id === source.client_id);
    const rest = this.nodes.filter((n) => n.client_id !== source.client_id);

    // Re-parent any nodes that had source as parent to the last chained node
    const lastId = chained[chained.length - 1].client_id;
    for (const n of rest) {
      if (n.parent_client_id === source.client_id) {
        n.parent_client_id = lastId;
      }
    }

    // Insert chain at source position
    this.nodes = [...rest.slice(0, sourceIndex), ...chained, ...rest.slice(sourceIndex)];
    this.selectedId = chained[0].client_id;
    this.dirty = true;
    this.autosave$.next();
  }

  // ── Grammar / spellcheck ──────────────────────────────────────────────

  checkGrammar(): void {
    if (!this.selected) return;
    const text = this.selected.body.trim();
    if (!text) return;
    this.grammarChecking = true;
    this.grammarError = null;
    this.api.spellcheck(text, this.language ?? 'en-US').subscribe({
      next: (result) => {
        this.grammarMatches = result.matches;
        this.grammarChecking = false;
        this.showPreview = true;
      },
      error: () => {
        this.grammarError = 'LanguageTool unavailable. Run it locally on port 8081.';
        this.grammarChecking = false;
      },
    });
  }

  applyReplacement(event: { match: SpellcheckMatch; replacement: string }): void {
    if (!this.selected) return;
    const { match, replacement } = event;
    const body = this.selected.body;
    const next =
      body.slice(0, match.offset) + replacement + body.slice(match.offset + match.length);
    this.selected.body = next;
    this.dirty = true;
    this.autosave$.next();
    // Re-check after applying
    this.grammarMatches = this.grammarMatches.filter((m) => m !== match);
  }

  // ── Persistence ────────────────────────────────────────────────────────

  private buildPayload(): DraftIn {
    return {
      tree_json: JSON.stringify(this.nodes),
      editor_engine: this.editorEngine,
      language: this.language,
      identity_id: this.selectedIdentityId,
      reply_to_status_id: this.replyToStatusId,
    };
  }

  private loadDraft(d: Draft): void {
    this.draft = d;
    try {
      const parsed: DraftNode[] = JSON.parse(d.tree_json || '[]');
      this.nodes = parsed.length ? parsed : [this.newNode(null)];
    } catch {
      this.nodes = [this.newNode(null)];
    }
    this.selectedId = this.nodes[0].client_id;
    this.editorEngine = d.editor_engine;
    this.language = d.language;
    this.replyToStatusId = d.reply_to_status_id;
    if (d.identity_id) this.selectedIdentityId = d.identity_id;
    this.dirty = false;
  }

  saveDraft(): void {
    if (!this.dirty) return;
    const payload = this.buildPayload();
    this.saving = true;

    if (this.draft) {
      this.api.updateDraft(this.draft.id, payload).subscribe({
        next: (d) => {
          this.draft = d;
          this.dirty = false;
          this.saving = false;
        },
        error: () => (this.saving = false),
      });
    } else {
      this.api.createDraft(payload).subscribe({
        next: (d) => {
          this.draft = d;
          this.dirty = false;
          this.saving = false;
          this.router.navigate(['/write/draft', d.id], { replaceUrl: true });
        },
        error: () => (this.saving = false),
      });
    }
  }

  // ── Publish ────────────────────────────────────────────────────────────

  publish(): void {
    if (!this.hasContent || !this.selectedIdentityId) return;
    this.publishError = null;

    const doPublish = () => {
      if (this.draft) {
        this.doPublishDraft();
      } else {
        // Create draft first then publish
        this.api.createDraft(this.buildPayload()).subscribe({
          next: (d) => {
            this.draft = d;
            this.dirty = false;
            this.router.navigate(['/write/draft', d.id], { replaceUrl: true });
            this.doPublishDraft();
          },
          error: (e: { message: string }) => (this.publishError = e.message),
        });
      }
    };

    if (this.dirty && this.draft) {
      this.api.updateDraft(this.draft.id, this.buildPayload()).subscribe({
        next: (d) => {
          this.draft = d;
          this.dirty = false;
          doPublish();
        },
        error: (e: { message: string }) => (this.publishError = e.message),
      });
    } else {
      doPublish();
    }
  }

  private doPublishDraft(): void {
    if (!this.draft || !this.selectedIdentityId) return;
    this.publishing = true;
    this.api.publishDraft(this.draft.id, this.selectedIdentityId).subscribe({
      next: () => {
        this.publishing = false;
        this.draft = null;
        this.nodes = [this.newNode(null)];
        this.selectedId = this.nodes[0].client_id;
        alert('Published! Cache is updating...');
        this.router.navigate(['/write']);
      },
      error: (e: { message: string }) => {
        this.publishing = false;
        this.publishError = e.message;
      },
    });
  }

  discardDraft(): void {
    if (!this.draft) return;
    if (!confirm('Discard this draft?')) return;
    this.api.deleteDraft(this.draft.id).subscribe({
      next: () => {
        this.draft = null;
        this.nodes = [this.newNode(null)];
        this.selectedId = this.nodes[0].client_id;
        this.router.navigate(['/write']);
      },
    });
  }

  // ── Utilities ──────────────────────────────────────────────────────────

  private newNode(parentId: string | null): DraftNode {
    return {
      client_id: crypto.randomUUID(),
      parent_client_id: parentId,
      mode: 'single',
      body: '',
      spoiler_text: null,
      visibility: 'public',
    };
  }

  private topoSort(nodes: DraftNode[]): DraftNode[] {
    const result: DraftNode[] = [];
    const visited = new Set<string>();

    const visit = (id: string | null) => {
      const children = nodes.filter((n) => n.parent_client_id === id);
      for (const child of children) {
        if (!visited.has(child.client_id)) {
          visited.add(child.client_id);
          result.push(child);
          visit(child.client_id);
        }
      }
    };

    visit(null);
    // Append any orphans (shouldn't happen in practice)
    for (const n of nodes) {
      if (!visited.has(n.client_id)) result.push(n);
    }
    return result;
  }
}
