#!/usr/bin/env bash
# Undo a failed GitHub release and the bump PR created by the Release workflow.
#
# Usage:
#   ./scripts/undo_release.sh 0.4.1
#   ./scripts/undo_release.sh v0.4.1 --yes
set -euo pipefail

usage() {
  echo "Usage: $0 <version> [--yes]"
  echo "Example: $0 0.4.1"
}

if [ "$#" -lt 1 ] || [ "$#" -gt 2 ]; then
  usage
  exit 2
fi

VERSION="$1"
TAG="v${VERSION#v}"
ASSUME_YES=false

if [ "$#" -eq 2 ]; then
  if [ "$2" != "--yes" ]; then
    usage
    exit 2
  fi
  ASSUME_YES=true
fi

for command in gh git; do
  if ! command -v "$command" >/dev/null 2>&1; then
    echo "ERROR: Required command not found: ${command}" >&2
    exit 1
  fi
done

gh auth status >/dev/null

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

REPO="$(gh repo view --json nameWithOwner --jq .nameWithOwner)"
if ! RELEASE_ID="$(gh api "repos/${REPO}/releases/tags/${TAG}" --jq .id 2>/dev/null)"; then
  echo "ERROR: GitHub release ${TAG} does not exist in ${REPO}." >&2
  exit 1
fi

BUMP_BRANCH="release/bump-${RELEASE_ID}"
OPEN_PRS="$(gh pr list \
  --repo "$REPO" \
  --state open \
  --head "$BUMP_BRANCH" \
  --json number \
  --jq '.[].number')"

echo "This will undo ${TAG} in ${REPO}:"
if [ -n "$OPEN_PRS" ]; then
  while IFS= read -r pr_number; do
    echo "  - close pull request #${pr_number}"
  done <<< "$OPEN_PRS"
fi
echo "  - delete remote branch ${BUMP_BRANCH}, if it exists"
echo "  - delete GitHub release ${TAG} and its remote tag"
if git rev-parse --verify --quiet "refs/tags/${TAG}" >/dev/null; then
  echo "  - delete local tag ${TAG}"
fi
echo
echo "This does not and cannot delete a package already published to PyPI."

if [ "$ASSUME_YES" = false ]; then
  read -r -p "Type ${TAG} to continue: " CONFIRMATION
  if [ "$CONFIRMATION" != "$TAG" ]; then
    echo "Aborted."
    exit 1
  fi
fi

if [ -n "$OPEN_PRS" ]; then
  while IFS= read -r pr_number; do
    gh pr close "$pr_number" \
      --repo "$REPO" \
      --comment "Closing because release ${TAG} is being undone."
  done <<< "$OPEN_PRS"
fi

if gh api "repos/${REPO}/git/ref/heads/${BUMP_BRANCH}" >/dev/null 2>&1; then
  gh api --method DELETE "repos/${REPO}/git/refs/heads/${BUMP_BRANCH}"
fi

gh release delete "$TAG" --repo "$REPO" --cleanup-tag --yes

if git rev-parse --verify --quiet "refs/tags/${TAG}" >/dev/null; then
  git tag --delete "$TAG"
fi

echo "Undid release ${TAG}."
