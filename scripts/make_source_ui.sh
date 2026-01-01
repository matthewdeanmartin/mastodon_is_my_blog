#!/usr/bin/env bash
set -euo pipefail

git2md web \
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
    README.md \
  --output SOURCE_UI.md