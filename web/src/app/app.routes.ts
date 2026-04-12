import { Routes } from '@angular/router';
import { PublicFeedComponent } from './feed.component';
import { AdminComponent } from './admin.component';
import { WriteComponent } from './write.component';
import { PublicPostComponent } from './post.component';
import { LoginComponent } from './login.component';
import {ContentComponent} from './content.component';
import {ImageFeedComponent} from './image.component';
import {LinksFeedComponent, NewsFeedComponent, SoftwareFeedComponent} from './software.component';
import {ForumComponent} from './forum.component';
import {ContentHubGroupComponent} from './content-hub-group.component';

export const routes: Routes = [
  { path: '', component: PublicFeedComponent },
  { path: 'login', component: LoginComponent },
  { path: 'p/:id', component: PublicPostComponent },
  { path: 'write', component: WriteComponent },
  { path: 'admin', component: AdminComponent },

  // Content Hub
  {
    path: 'content',
    component: ContentComponent,
    children: [
      { path: '', redirectTo: 'images', pathMatch: 'full' },
      // Fixed content-type filters (cached posts from follows)
      { path: 'images', component: ImageFeedComponent },
      { path: 'software', component: SoftwareFeedComponent },
      { path: 'links', component: LinksFeedComponent },
      { path: 'news', component: NewsFeedComponent },
      // Dynamic hashtag groups
      { path: 'group/:groupId', component: ContentHubGroupComponent },
    ]
  },

  // Forum App
  { path: 'forum', component: ForumComponent },

  { path: '**', redirectTo: '' },
];
