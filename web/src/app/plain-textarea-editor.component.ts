import {
  Component,
  ElementRef,
  EventEmitter,
  Input,
  OnInit,
  Output,
  ViewChild,
  inject,
} from '@angular/core';
import { FormsModule } from '@angular/forms';
import { EditorEngineRegistry } from './editor-engine.registry';

@Component({
  selector: 'app-plain-textarea-editor',
  standalone: true,
  imports: [FormsModule],
  template: `
    <textarea
      #ta
      [(ngModel)]="value"
      (ngModelChange)="valueChange.emit($event)"
      [attr.lang]="language || null"
      [attr.readonly]="readonly || null"
      spellcheck="true"
      placeholder="What's on your mind?"
    ></textarea>
  `,
})
export class PlainTextareaEditorComponent implements OnInit {
  @Input() value = '';
  @Output() valueChange = new EventEmitter<string>();
  @Input() language: string | null = null;
  @Input() readonly = false;

  @ViewChild('ta') ta!: ElementRef<HTMLTextAreaElement>;

  private registry = inject(EditorEngineRegistry);

  ngOnInit(): void {
    this.registry.register({
      id: 'plain',
      label: 'Plain text',
      component: PlainTextareaEditorComponent,
    });
  }

  focus(): void {
    this.ta?.nativeElement.focus();
  }

  insertAtCursor(text: string): void {
    const el = this.ta?.nativeElement;
    if (!el) return;
    const start = el.selectionStart ?? el.value.length;
    const end = el.selectionEnd ?? el.value.length;
    const next = el.value.slice(0, start) + text + el.value.slice(end);
    this.value = next;
    this.valueChange.emit(next);
    setTimeout(() => {
      el.selectionStart = el.selectionEnd = start + text.length;
    });
  }
}
