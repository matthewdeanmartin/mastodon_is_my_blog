# TODO

## Subapps
- Blogs/Storms (Blogger/Google Reader)
- Shorts (Twitter)
- Links (Delicious) - Started!
- Discussions (Forums) - Started!
- Pictures (Flickr) - Started!

## Regressions
- Perf is in the trash again

## Top prio
- Top friends should include mentions and replies to my account. And likes or the list is too short.
- Independently fetch all replies to me to find out who is a Top Friend (mutual and replies) 
- Surveys should all be moved to Questions
- Whole nice profile page with EVERYTHING.
- New filter
  - Shorts
- Button to methodically cache all users in blog roll (with polite sleep, run in backgroup worker)
- Shorts filter (single part storms less than 200 characters)
- BUG: storms are only root + 1 "reply"
- Web Storm/Shorts messed up.
  - Looking for blog like content. Find all posts from Identity
    - Not replies to someone elses root
    - Not starts with '@acct' (old school replies)
    - Having identified blog like content, we will remove the shorts.
  - Now if it meets all the criteria, but it is a single post (no self replies) of less than 50 words, it is a short.
  - Counting workds (exclude link, hashtag, symbols) 
- Pictures in feed are too big! Need some gallery type component that show smaller preview, click to see full size. 
- BUG: Questions should exclude replies, which also means starts with `@so_and_so`


## Links to original content
- Missing link to profile!
- Links to original post are all bad! (direct to other instance instead of Identity instance?)

## Profile header
- Fill in more bio/profile info and make it more compact or click to expand

## Roadmap
- Discovery mode
  - Show content from federated feed with some filters

## Post View
- Storms should be a nice tidy block.
- Counts don't update when changing users
- If bio is long, it should split across 2 columns

## Recommended Discussions
- If discussion is rooted in an authors own work, it is blog-like content. That discussion should appear in the storms/shorts/links/etc
- 3 kinds of discussions
  - Root mention - `@so_and_so did you see this`. Unless you are @so_and_so, this is not blog-like content. It is content discovery.
  - Author reply in discussion rooted by author's post (Should show in relevant location, right?)
  - Reply in discussion rooted by someone else's post (Content discovery)
- UI should show the roots- Discussions only show the disconnected middle part, should show entire tree.
- Quote posts are a type of recommended discussion

## Recommented Posts
- All reblogs

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
- Posts with media show in videos but feed/post doesn't show video
- API call logging never happens, no feel for if API calls have happened.

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
- Should call get_post_context - DONE
- Display the entire graph - DONE
- Show names and icons for who is talking

## Posts - Next 
- Need Next Post button - DONE

## Feed filters
- Need Questions tab that just finds the posts with words ending with ? - DONE
- Everyone button where it shows everyones posts. This happens anyhow when you click the admin page.- MESSED UP
- Counts often fail to update or only after changing blog role AND changing category.
