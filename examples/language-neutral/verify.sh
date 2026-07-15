#!/usr/bin/env bash
set -euo pipefail

case "${1:-}" in
  build|test)
    ;;
  *)
    echo "usage: $0 {build|test}" >&2
    exit 2
    ;;
esac

test -f .ai-workflow.yaml
test -f README.md
grep -q '^schema_version: 1$' .ai-workflow.yaml
grep -q '^repository: language-neutral-example$' .ai-workflow.yaml
grep -q '^  build: \[bash, verify.sh, build\]$' .ai-workflow.yaml
grep -q '^  test: \[bash, verify.sh, test\]$' .ai-workflow.yaml
