#!/usr/bin/env bash
set -euo pipefail
uv run black mastodon_is_my_blog
uv run isort mastodon_is_my_blog
uv run ruff check mastodon_is_my_blog --fix

git2md . \
  --ignore .angular \
  node_modules \
  public \
  *.spec.ts \
  angular.json \
  .editorconfig \
  .gitignore \
    .editorconfig \
    .gitignore \
    .vscode \
    angular.json \
    package-lock.json \
    package.json \
    tailwind.config.js \
    tsconfig.app.json \
    tsconfig.json \
    tsconfig.spec.json \
    dead_code \
    README.md SETUP.md CHANGELOG.md TODO.md \
    .venv uv.lock \
    Makefile Makefile1 LICENSE \
    SOURCE_ALL.md SOURCE_UI.md SOURCE.md \
    scripts \
    app.db \
    favicon.ico \
    alembic alembic_sync \
  --output SOURCE_ALL.md