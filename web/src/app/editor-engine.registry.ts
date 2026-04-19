import { Injectable } from '@angular/core';
import { EditorEngine } from './editor-engine';

@Injectable({ providedIn: 'root' })
export class EditorEngineRegistry {
  private engines = new Map<string, EditorEngine>();

  register(engine: EditorEngine): void {
    this.engines.set(engine.id, engine);
  }

  get(id: string): EditorEngine | undefined {
    return this.engines.get(id);
  }

  list(): EditorEngine[] {
    return Array.from(this.engines.values());
  }
}
