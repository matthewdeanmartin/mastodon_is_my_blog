import { bootstrapApplication } from '@angular/platform-browser';
import { provideHttpClient } from '@angular/common/http';
import { provideZonelessChangeDetection } from '@angular/core';

import { LiteAppComponent } from './lite/lite-app.component';

bootstrapApplication(LiteAppComponent, {
  providers: [provideHttpClient(), provideZonelessChangeDetection()],
}).catch((error: unknown) => console.error(error));
