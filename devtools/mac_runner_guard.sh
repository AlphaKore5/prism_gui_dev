#!/bin/bash
# Runs ON THE BUILD MAC before every job (ACTIONS_RUNNER_HOOK_JOB_STARTED) and
# refuses anything but our own builds. It lives outside the checkout, owned by
# the Mac's administrator, so a pull request cannot edit it. Installed by hand:
# docs/MAC_BUILD_RUNNER.md, part 4. One layer, not a wall: see part 1 there.
REPO=AlphaKore5/prism_gui_dev
ok=no
case "${GITHUB_EVENT_NAME:-}" in
  push|schedule|workflow_dispatch) ok=event ;;
esac
if [ "$ok" = event ]; then
  case "${GITHUB_WORKFLOW_REF:-}" in
    "$REPO/.github/workflows/build.yml@refs/heads/main") ok=yes ;;
    "$REPO/.github/workflows/build.yml@refs/tags/v"*) ok=yes ;;
    "$REPO/.github/workflows/macos-pins.yml@refs/heads/main") ok=yes ;;
  esac
fi
if [ "$ok" != yes ]; then
  echo "::error::This Mac refused the job: event '${GITHUB_EVENT_NAME:-}', workflow '${GITHUB_WORKFLOW_REF:-}'."
  exit 1
fi
echo "Allowed: ${GITHUB_EVENT_NAME} ${GITHUB_WORKFLOW_REF}"
