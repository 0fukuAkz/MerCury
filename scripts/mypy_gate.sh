#!/usr/bin/env bash
#
# Type-check ratchet — fail CI only when *new* mypy errors are introduced.
#
# The codebase carries a known, grandfathered type-debt baseline recorded in
# .mypy_baseline (the legacy Column()-style ORM models account for most of
# it; see the Mapped[] migration tracked in the improvement plan). Driving
# that to zero is a multi-week effort, so until then this gate stops the
# debt from *growing* while leaving the existing errors in place.
#
# Behaviour:
#   current > baseline  -> FAIL  (you added type errors — fix them)
#   current < baseline  -> PASS  (and nudge you to ratchet the baseline down
#                                 so the improvement is locked in)
#   current = baseline  -> PASS
#
# The gate is count-based on purpose: error counts are immune to the
# line-number churn that normal refactors produce, so it won't flap on
# unrelated edits. The trade-off is that it can't tell "fixed A, added B"
# apart when the net count is unchanged — acceptable for a debt ratchet.
#
# IMPORTANT: the baseline is version-sensitive. Regenerate it whenever the
# pinned mypy version changes:  mypy src/ 2>/dev/null | grep -c 'error:'
#
set -uo pipefail

cd "$(dirname "$0")/.."

# Prefer the project venv locally; fall back to mypy on PATH (CI installs it
# globally). Keeps `make` and the GitHub runner producing identical counts.
MYPY="mypy"
[ -x ".venv/bin/mypy" ] && MYPY=".venv/bin/mypy"

BASELINE_FILE=".mypy_baseline"
baseline="$(tr -dc '0-9' <"$BASELINE_FILE" 2>/dev/null || true)"
baseline="${baseline:-0}"

# mypy exits 0 (clean) or 1 (type errors). Anything higher is a real failure
# (config error, crash) — surface it rather than miscount it as "0 errors".
output="$("$MYPY" src/ 2>&1)"
rc=$?
if [ "$rc" -gt 1 ]; then
    echo "mypy failed to run (exit $rc), not a type-error count:"
    printf '%s\n' "$output"
    exit 1
fi

current="$(printf '%s\n' "$output" | grep -c 'error:')"
echo "mypy type errors: current=$current baseline=$baseline"

if [ "$current" -gt "$baseline" ]; then
    echo "FAIL: $((current - baseline)) new mypy error(s) over the baseline of $baseline."
    echo "----- current errors -----"
    printf '%s\n' "$output" | grep 'error:'
    exit 1
fi

if [ "$current" -lt "$baseline" ]; then
    echo "Improvement: $((baseline - current)) fewer error(s) than baseline."
    echo "Lock it in:  echo $current > $BASELINE_FILE"
fi

echo "PASS: no new type errors."
exit 0
