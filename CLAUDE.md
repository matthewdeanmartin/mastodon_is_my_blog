Use uv, not the system python.

Never use hungarian notation, in particular _ prefix for "private"
Do not use _ as the start of a variable name for any hungarian reason. Do not use _ as the start of any class, function, etc to indicate private.
It is okay to use _ to mean unused variable or to make ruff happy with an unused variable, for example in tuple
unpacking. That is it.

Main module is in ./mastodon_is_my_blog/ not using a src layout.
Tests in 
- test/ 
- test_integration/ for anything using live API keys
