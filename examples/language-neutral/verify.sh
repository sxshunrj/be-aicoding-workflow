#!/usr/bin/env bash
set -euo pipefail

case "${1:-}" in
  build|unit-test)
    ;;
  *)
    echo "usage: $0 {build|unit-test}" >&2
    exit 2
    ;;
esac

test -f .ai-workflow.yaml
test -f README.md
grep -q '^schema_version: 2$' .ai-workflow.yaml
grep -q '^repository: language-neutral-example$' .ai-workflow.yaml
grep -q '^  build: \[bash, verify.sh, build\]$' .ai-workflow.yaml
grep -q '^  unit_test: \[bash, verify.sh, unit-test\]$' .ai-workflow.yaml
grep -q '^disabled_nodes: \[verify.integration_test\]$' .ai-workflow.yaml

echo "language-neutral ${1} ok"
