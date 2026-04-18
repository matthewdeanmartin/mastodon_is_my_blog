import { Routes } from '@angular/router';
import { PublicFeedComponent } from './feed.component';
import { AdminComponent } from './admin.component';
import { WriteComponent } from './write.component';
import { PublicPostComponent } from './post.component';
import { LoginComponent } from './login.component';
import { ContentComponent } from './content.component';
import { ImageFeedComponent } from './image.component';
import { LinksFeedComponent, NewsFeedComponent, SoftwareFeedComponent } from './software.component';
import { ContentHubTextComponent, ContentHubJobsComponent } from './content-hub-tabs.component';
import { ContentHubPeopleComponent } from './content-hub-people.component';
import { ForumComponent } from './forum.component';
import { AnalyticsComponent } from './analytics.component';
import { PeepsComponent } from './peeps.component';
import { DossierComponent } from './dossier.component';

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
      // Tab views — each works in both "my follows" mode and "hashtag group" mode
      { path: 'images',   component: ImageFeedComponent },
      { path: 'software', component: SoftwareFeedComponent },
      { path: 'links',    component: LinksFeedComponent },
      { path: 'news',     component: NewsFeedComponent },
      // Group-only tab views (also work in follows mode — just show a prompt)
      { path: 'text',     component: ContentHubTextComponent },
      { path: 'jobs',     component: ContentHubJobsComponent },
      { path: 'people',   component: ContentHubPeopleComponent },
    ]
  },

  // Forum App
  { path: 'forum', component: ForumComponent },

  // Analytics
  { path: 'analytics', component: AnalyticsComponent },

  // Peeps Finder
  { path: 'peeps', component: PeepsComponent },
  { path: 'peeps/dossier/:acct', component: DossierComponent },

  { path: '**', redirectTo: '' },
];
