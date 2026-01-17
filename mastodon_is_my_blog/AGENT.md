# Coding guidelines

- Always type annotate
- Always get as much data from mastodon's APIs to cache locally as possible
- Don't hide exceptions with excessive error handling, let them raise.
- If you are catching Exception, you don't have enough info to know if you are catching a known event or hiding a bug.


