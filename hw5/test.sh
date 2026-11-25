#!/bin/sh
set -eu
cd "$(dirname "$0")"
# Unique project, volumes and ephemeral host ports even with a demo already running.
project="cinema-test-$(date +%s)-$$"
export MOVIE_PORT=0 AGGREGATION_PORT=0 REGISTRY_PORT=0
export GENERATOR_INTERVAL_SECONDS=0 AGGREGATION_INTERVAL_SECONDS=3
compose() { docker compose -p "$project" "$@"; }
cleanup() {
  result=$?
  trap - EXIT
  if [ "$result" -ne 0 ]; then compose logs --tail=80 >&2 || true; fi
  compose down -v --remove-orphans
  exit "$result"
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
compose --profile test run --build --rm tests
