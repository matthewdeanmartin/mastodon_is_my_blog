# Uninstalling mimb

mimb keeps data outside its install directory so upgrades don't lose your
blog. A full uninstall is therefore two commands: `mimb uninstall` (removes
your data) and `pipx uninstall mastodon-is-my-blog` (removes the program).

## Before you uninstall

If there is any chance you'll come back, take your data with you first:

```
mimb db export --out mimb-backup.jsonl
```

That single file can be re-imported later with `mimb db import --in
mimb-backup.jsonl`. If you published a blog, the built site in your repo's
`docs/` folder is yours and is never touched by uninstall.

## What `mimb uninstall` removes

Run the preview first — it changes nothing and shows exactly what would go:

```
mimb uninstall --dry-run
```

The plan has three separately confirmed steps:

1. **Home data & config** — the application data directory
   (`%LOCALAPPDATA%\mastodon_is_my_blog` on Windows,
   `~/.local/share/mastodon_is_my_blog` and
   `~/.config/mastodon_is_my_blog` on Linux,
   `~/Library/Application Support/mastodon_is_my_blog` on macOS).
   This holds the SQLite database and `accounts.json`. If your `DB_URL`
   points at a SQLite file somewhere else, that file is listed and removed
   too.
2. **OS keyring entries** — the Mastodon client IDs, secrets, and access
   tokens mimb stored in your system keychain. Every key is listed by name
   before anything is deleted, and this step has its own confirmation.
3. **Postgres database** — only offered if you run mimb against Postgres
   and the server is reachable. This is a `DROP DATABASE`, separately
   confirmed; your Postgres server itself is untouched.

## Running it

Interactive (prompts for each step):

```
mimb uninstall
```

Non-interactive, everything:

```
mimb uninstall --yes --keyring --drop-db
```

`--yes` only covers step 1; the keyring and Postgres steps never happen
without their own flag or an explicit yes at the prompt.

## What it never touches

- The installed program — finish with `pipx uninstall mastodon-is-my-blog`
  (or `pip uninstall mastodon-is-my-blog`).
- `.env` files in your project directories.
- Your published blog (`docs/` in your blog repo) and anything pushed to git.

## Broken install instead of a goodbye?

If you're uninstalling because things are broken, try `mimb doctor` first —
every warning comes with the command that fixes it. A reinstall
(`pipx reinstall mastodon-is-my-blog`) keeps all your data, because the data
lives in the directories above, not in the install.
