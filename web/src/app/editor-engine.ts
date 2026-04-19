import { EventEmitter, Type } from '@angular/core';

export interface EditorEngineComponent {
  value: string;
  valueChange: EventEmitter<string>;
  language: string | null;
  readonly: boolean;
  focus(): void;
  insertAtCursor(text: string): void;
}

export interface EditorEngine {
  id: string;
  label: string;
  component: Type<EditorEngineComponent>;
  keybindingsHelpUrl?: string;
}
