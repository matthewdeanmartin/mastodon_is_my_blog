import { Routes } from '@angular/router';
import { PublicFeedComponent } from './feed.component';
import { AdminComponent } from './admin.component';
import { PublicPostComponent } from './post.component';
import { LoginComponent } from './login.component';
import {ContentComponent} from './content.component';
import {ImageFeedComponent} from './image.component';
import {LinksFeedComponent, NewsFeedComponent, SoftwareFeedComponent} from './software.component';
import {ForumComponent} from './forum.component';

export const routes: Routes = [
  { path: '', component: PublicFeedComponent },
  { path: 'login', component: LoginComponent },
  { path: 'p/:id', component: PublicPostComponent },
  { path: 'admin', component: AdminComponent },

  // Content App
  {
    path: 'content',
    component: ContentComponent,
    children: [
      { path: '', redirectTo: 'images', pathMatch: 'full' },
      { path: 'images', component: ImageFeedComponent },
      { path: 'software', component: SoftwareFeedComponent },
      { path: 'links', component: LinksFeedComponent },
      { path: 'news', component: NewsFeedComponent },
    ]
  },

  // Forum App
  { path: 'forum', component: ForumComponent },

  { path: '**', redirectTo: '' },
];
