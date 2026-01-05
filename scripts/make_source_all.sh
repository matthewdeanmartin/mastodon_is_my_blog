#!/usr/bin/env bash
set -euo pipefail

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
    README.md SETUP.md CHANGELOG.md \
    .venv uv.lock \
    Makefile Makefile1 LICENSE \
    SOURCE_ALL.md SOURCE_UI.md SOURCE.md \
    scripts \
    app.db \
    favicon.ico \
  --output SOURCE_ALL.md