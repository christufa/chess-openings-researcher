#!/usr/bin/env bash
# Record this main build's images on the deploy-state branch as openings.yaml
# (commit, worker.digest, api.digest). deploy/apps/research.yaml reads it with a git files
# generator, so a new signed build is a manifest change Argo CD syncs.
# Called by images.yml (job release) from a full-history checkout of main.
#
#   env: WORKER_DIGEST, API_DIGEST  sha256:... digests this run pushed and signed
#
# Both or neither: the worker and API must come from the same commit, so a run where
# either image failed leaves deploy-state as it was. deploy-state isn't covered by main's
# ruleset, so GITHUB_TOKEN can push; only fast-forward commits from here.
set -euo pipefail
branch=deploy-state
file=openings.yaml

for name in WORKER_DIGEST API_DIGEST; do
  digest=${!name:-}
  if [ -z "$digest" ]; then
    echo "::warning::$name is empty (that image wasn't published): deploy-state unchanged"
    exit 0
  fi
  [[ $digest =~ ^sha256:[0-9a-f]{64}$ ]] || { echo "::error::$name: bad digest '$digest'"; exit 1; }
done

git config user.name "github-actions[bot]"
git config user.email "41898282+github-actions[bot]@users.noreply.github.com"

if git fetch --depth=1 origin "$branch"; then
  git switch --detach FETCH_HEAD
else
  echo "no $branch branch yet: starting it"
  git switch --orphan "$branch"
  cat > README.md <<'EOF'
# deploy-state

Written only by `.github/workflows/images.yml` (job `release`): the commit and image
digests of the newest signed main build, read by `deploy/apps/research.yaml`.
Don't edit by hand except to roll back (`git revert`).
EOF
fi

# A re-run of an older workflow must not roll back a newer release.
prev=$(sed -n 's/^commit: *//p' "$file" 2>/dev/null || true)
if [ -n "$prev" ] && [ "$prev" != "$GITHUB_SHA" ] && ! git merge-base --is-ancestor "$prev" "$GITHUB_SHA"; then
  echo "::warning::deploy-state already has $prev, which is not an ancestor of $GITHUB_SHA; skipped"
  exit 0
fi

cat > "$file" <<EOF
# Written by .github/workflows/images.yml for main commit $GITHUB_SHA. Don't edit.
commit: $GITHUB_SHA
worker:
  digest: $WORKER_DIGEST
api:
  digest: $API_DIGEST
EOF

git add -A
if git diff --cached --quiet; then
  echo "deploy-state is already up to date"
  exit 0
fi
git commit -q -m "release ${GITHUB_SHA::12}" \
  -m "${GITHUB_SERVER_URL}/${GITHUB_REPOSITORY}/actions/runs/${GITHUB_RUN_ID}"
git push origin "HEAD:refs/heads/$branch"
echo "### deploy-state: openings-worker and openings-api → \`${GITHUB_SHA::12}\`" >> "${GITHUB_STEP_SUMMARY:-/dev/null}"
