import { Routes } from '@angular/router';
import { HomeComponent } from './home.component';
import { PostComponent } from './post.component';

export const routes: Routes = [
  { path: '', component: HomeComponent },
  { path: 'post/:id', component: PostComponent },
  { path: 'connected', component: HomeComponent },
];
