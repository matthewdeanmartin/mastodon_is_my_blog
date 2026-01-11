#!/usr/bin/env bash
set -euo pipefail

git2md web \
  --ignore .angular \
  .vscode\extensions.json \
  node_modules \
  public \
  .vscode \
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
    README.md \
    app.db \
    favicon.ico \
  --output SOURCE_UI.md