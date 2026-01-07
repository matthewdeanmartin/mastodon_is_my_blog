# TODO

## Post View
- Storms should be a nice tidy block.
- Counts don't update when changing users
- Discussions only show the disconnected middle part, should show entire tree.
- If bio is long, it should split across 2 columns

## Blogroll
- Seems to always sort the same way. Should continually update sort order based on who posted last
- Need button to force update of blog roll (which normally only shows mostly recently active)
- UI: Need a "next blog roll" button

## Quality of life things
- UI:  Click on blog roll should pop user to top of screen
- Almost works! When backend server is down, there should be some message and it should poll ( a cheap endpoint) for when it is up again

## Bugs
- If you click blog roll user and wait, then before it returns you click another category, the 2nd request finishes and blows up on PK violations
- When you click on a blog roll user, counts are displayed as 0 until you click another category
- When you click Admin, the sidebar shows counts for everything and if you click a filter button you get a mix of everyones content.
- Storms count is links count. Wrong!

## Content creation
- Need edit button on all own
- Need a reply button
- Need to support drafts
- Need to support posting multiple posts at same time (a post storm)

## Multiple Accounts
- Need to support multiple accounts and account switching

## Hosting multiple tenants
- Each tenant can have multiple accounts
- Tenants must not be able to query other tenants' data
- Would require some auth layer


## Hash tags as filters
- Fetch hashtags for a user (get_hashtags)
- Display those hash tags at top of feed
- Clicking a hashtag filters feed down to just those posts with those hashtags

## Post Component
- Should call get_post_context
- Display the entire graph
- Show names and icons for who is talking