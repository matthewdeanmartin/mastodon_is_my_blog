import { Component, OnInit } from '@angular/core';
import { ApiService } from './api.service';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';

@Component({
  selector: 'app-admin',
  standalone: true,
  imports: [CommonModule, FormsModule],
  templateUrl: 'admin.component.html',
})
export class AdminComponent implements OnInit {
  status: any;
  draft = '';
  syncing = false;

  constructor(public api: ApiService) {}

  ngOnInit() {
    this.refreshStatus();
  }

  refreshStatus() {
    this.api.getAdminStatus().subscribe((s) => (this.status = s));
  }

  sync() {
    this.syncing = true;
    this.api.triggerSync(true).subscribe({
      next: () => {
        this.syncing = false;
        this.refreshStatus();
        alert('Sync complete!');
      },
      error: () => (this.syncing = false),
    });
  }

  publish() {
    this.api.createPost(this.draft).subscribe({
      next: () => {
        this.draft = '';
        alert('Published! Cache is updating...');
        this.refreshStatus();
      },
      error: (e) => alert('Error: ' + e.message),
    });
  }
}
