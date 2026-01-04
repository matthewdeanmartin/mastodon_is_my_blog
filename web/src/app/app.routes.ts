import { Routes } from '@angular/router';
import {PublicFeedComponent} from './public-feed.component';
import {AdminComponent} from './admin.component';
import {PublicPostComponent} from './public-post.component';

export const routes: Routes = [
  { path: '', component: PublicFeedComponent },
  { path: 'p/:id', component: PublicPostComponent },
  { path: 'admin', component: AdminComponent },
  { path: '**', redirectTo: '' }
];
