import { Routes } from '@angular/router';
import {PublicFeedComponent} from './feed.component';
import {AdminComponent} from './admin.component';
import {PublicPostComponent} from './post.component';

export const routes: Routes = [
  { path: '', component: PublicFeedComponent },
  //{ path: 'user/:acct', component: UserFeedComponent },
  { path: 'p/:id', component: PublicPostComponent },
  { path: 'admin', component: AdminComponent },
  { path: '**', redirectTo: '' }
];


