import { Component, Input } from '@angular/core';
import { CommonModule } from '@angular/common';
import { DraftNode } from './mastodon';
import { mastodonLength } from './mastodon-length';

@Component({
  selector: 'app-live-preview-pane',
  standalone: true,
  imports: [CommonModule],
  template: `
    <div style="height: 100%;">
      @if (nodes.length === 0 || !nodes[0].body.trim()) {
        <div class="muted" style="font-size: 0.85rem; font-style: italic;">Nothing to preview.</div>
      }

      @for (node of nodes; track node.client_id; let i = $index) {
        @if (node.body.trim()) {
          <div
            class="card"
            [style.border-left]="node.client_id === selectedId ? '3px solid #6366f1' : '3px solid #e1e8ed'"
            style="margin-bottom: 10px; padding: 10px; font-size: 0.88rem;"
          >
            @if (node.spoiler_text) {
              <div style="
                background: #fef3c7;
                color: #92400e;
                font-size: 0.75rem;
                padding: 3px 8px;
                border-radius: 4px;
                margin-bottom: 6px;
                font-weight: 600;
              ">CW: {{ node.spoiler_text }}</div>
            }
            <div style="white-space: pre-wrap; word-break: break-word;">{{ node.body }}</div>
            <div style="display: flex; justify-content: space-between; margin-top: 8px; font-size: 0.75rem; color: #aaa;">
              <span>{{ i + 1 }}/{{ nodes.length }}</span>
              <span [style.color]="mastodonLength(node.body) > 480 ? '#dc2626' : '#aaa'">
                {{ mastodonLength(node.body) }}/500
              </span>
              <span style="text-transform: uppercase;">{{ node.visibility }}</span>
            </div>
          </div>
        }
      }
    </div>
  `,
})
export class LivePreviewPaneComponent {
  @Input() nodes: DraftNode[] = [];
  @Input() selectedId: string | null = null;

  readonly mastodonLength = mastodonLength;
}
