import { Component, inject } from '@angular/core';
import { ApiService } from './api.service';
import { FormsModule } from '@angular/forms';

@Component({
  selector: 'app-write',
  standalone: true,
  imports: [FormsModule],
  templateUrl: 'write.component.html',
})
export class WriteComponent {
  api = inject(ApiService);

  draft = '';

  publish() {
    this.api.createPost(this.draft).subscribe({
      next: () => {
        this.draft = '';
        alert('Published! Cache is updating...');
      },
      error: (e: { message: string }) => alert('Error: ' + e.message),
    });
  }
}
