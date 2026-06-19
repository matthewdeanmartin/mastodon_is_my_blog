import { Component, EventEmitter, Output, inject } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { ApiService } from './api.service';

type ConnectMode = 'oauth' | 'manual';

@Component({
  selector: 'app-connect-account',
  standalone: true,
  imports: [CommonModule, FormsModule],
  templateUrl: 'connect-account.component.html',
})
export class ConnectAccountComponent {
  api = inject(ApiService);

  @Output() closed = new EventEmitter<void>();
  @Output() connected = new EventEmitter<void>();

  mode: ConnectMode = 'oauth';
  baseUrl = '';
  clientId = '';
  clientSecret = '';
  accessToken = '';

  submitting = false;
  error: string | null = null;

  setMode(mode: ConnectMode): void {
    this.mode = mode;
    this.error = null;
  }

  close(): void {
    this.closed.emit();
  }

  submit(): void {
    if (!this.baseUrl.trim()) {
      this.error = 'Enter your Mastodon instance URL (e.g. https://mastodon.social).';
      return;
    }

    this.submitting = true;
    this.error = null;

    if (this.mode === 'oauth') {
      this.api.startConnectAccountOAuth(this.baseUrl.trim()).subscribe({
        next: (res) => {
          window.location.href = res.authorize_url;
        },
        error: (err: { error?: { detail?: string } }) => {
          this.submitting = false;
          this.error = err?.error?.detail ?? 'Failed to start OAuth connection.';
        },
      });
      return;
    }

    this.api
      .addIdentityApiKey(
        this.baseUrl.trim(),
        this.clientId.trim(),
        this.clientSecret.trim(),
        this.accessToken.trim(),
      )
      .subscribe({
        next: () => {
          this.submitting = false;
          this.connected.emit();
        },
        error: (err: { error?: { detail?: string } }) => {
          this.submitting = false;
          this.error = err?.error?.detail ?? 'Failed to add account.';
        },
      });
  }
}
