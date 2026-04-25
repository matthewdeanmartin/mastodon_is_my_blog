import { Component, EventEmitter, Input, Output } from '@angular/core';
import { CommonModule } from '@angular/common';
import { SpellcheckMatch } from './mastodon';

@Component({
  selector: 'app-grammar-hints',
  standalone: true,
  imports: [CommonModule],
  template: `
    <div>
      <div
        style="font-size: 0.75rem; font-weight: 600; text-transform: uppercase; color: #888; margin-bottom: 10px;"
      >
        Grammar / spelling hints ({{ matches.length }})
      </div>

      @if (matches.length === 0) {
        <div style="font-size: 0.85rem; color: #16a34a; font-style: italic;">No issues found.</div>
      }

      @for (m of matches; track m.offset) {
        <div
          style="
          border: 1px solid #e5e7eb;
          border-left: 3px solid #f59e0b;
          border-radius: 6px;
          padding: 8px 10px;
          margin-bottom: 8px;
          font-size: 0.85rem;
        "
        >
          <div style="font-weight: 500; margin-bottom: 4px;">
            "{{ snippet(m) }}"
            <span style="font-weight: 400; color: #6b7280; margin-left: 6px;">{{ m.message }}</span>
          </div>

          @if (m.replacements.length > 0) {
            <div style="display: flex; flex-wrap: wrap; gap: 4px; margin-top: 6px;">
              <span style="font-size: 0.75rem; color: #6b7280; align-self: center;"
                >Replace with:</span
              >
              @for (r of m.replacements; track r) {
                <button
                  (click)="applyReplacement.emit({ match: m, replacement: r })"
                  style="font-size: 0.78rem; padding: 2px 8px; background: none; border: 1px solid #6366f1; color: #6366f1; border-radius: 4px;"
                >
                  {{ r }}
                </button>
              }
            </div>
          }
        </div>
      }
    </div>
  `,
})
export class GrammarHintsComponent {
  @Input() matches: SpellcheckMatch[] = [];
  @Input() text = '';
  @Output() applyReplacement = new EventEmitter<{ match: SpellcheckMatch; replacement: string }>();

  snippet(m: SpellcheckMatch): string {
    return this.text.slice(m.offset, m.offset + m.length);
  }
}
