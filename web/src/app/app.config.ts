import { ApplicationConfig, provideZonelessChangeDetection } from '@angular/core';
import { provideRouter, withHashLocation } from '@angular/router'; // Import withHashLocation
import { provideHttpClient } from '@angular/common/http'; // Import provideHttpClient

import { routes } from './app.routes';

export const appConfig: ApplicationConfig = {
  providers: [
    provideZonelessChangeDetection(), // Optional but standard
    provideRouter(routes, withHashLocation()), // Add hash location here
    provideHttpClient() // Add this so your ApiService works
  ]
};
