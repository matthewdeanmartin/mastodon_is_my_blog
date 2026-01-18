import { Routes } from '@angular/router';
import { PublicFeedComponent } from './feed.component';
import { AdminComponent } from './admin.component';
import { PublicPostComponent } from './post.component';
import { LoginComponent } from './login.component';

export const routes: Routes = [
  { path: '', component: PublicFeedComponent },
  { path: 'login', component: LoginComponent },
  { path: 'p/:id', component: PublicPostComponent },
  { path: 'admin', component: AdminComponent },
  { path: '**', redirectTo: '' },
];
