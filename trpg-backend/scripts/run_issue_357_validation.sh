#!/usr/bin/env bash
set -euo pipefail

ENV_FILE=${1:-/Users/jiahao/.config/trpg/issue357-benchmark.env}
OUTPUT_DIR=${2:-/tmp/issue-357-validation-$(date +%Y%m%d-%H%M%S)}
TRANSPORT_CALL_CAP=${ISSUE_357_TRANSPORT_CALL_CAP:-2500}
SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
BACKEND_DIR=$(cd "${SCRIPT_DIR}/.." && pwd)
REPO_DIR=$(cd "${BACKEND_DIR}/.." && pwd)

if [[ ! "${TRANSPORT_CALL_CAP}" =~ ^[1-9][0-9]*$ ]]; then
  echo "ISSUE_357_TRANSPORT_CALL_CAP must be a positive integer" >&2
  exit 2
fi

if [[ ! -f "${ENV_FILE}" ]]; then
  echo "Issue #357 environment file does not exist: ${ENV_FILE}" >&2
  exit 2
fi

if [[ "$(uname -s)" == "Darwin" ]]; then
  FILE_MODE=$(stat -f '%Lp' "${ENV_FILE}")
else
  FILE_MODE=$(stat -c '%a' "${ENV_FILE}")
fi
if [[ "${FILE_MODE}" != "600" ]]; then
  echo "Issue #357 environment file must have mode 0600" >&2
  exit 2
fi

case "$(cd "$(dirname "${ENV_FILE}")" && pwd)/$(basename "${ENV_FILE}")" in
  "${REPO_DIR}"/*)
    echo "Issue #357 environment file must be outside the repository" >&2
    exit 2
    ;;
esac

umask 077
set -a
# shellcheck disable=SC1090 -- the path is an explicit user-owned argument.
source "${ENV_FILE}"
set +a

: "${HOST_MODEL_PROVIDER:?HOST_MODEL_PROVIDER is required}"
: "${DEEPSEEK_API_KEY:?DEEPSEEK_API_KEY is required for the Host model}"
: "${DEEPSEEK_BASE_URL:?DEEPSEEK_BASE_URL is required for the Host model}"
: "${DEEPSEEK_MODEL:?DEEPSEEK_MODEL is required for the Host model}"

# The Planner has an independent client and configuration. The values may be
# identical to the Host for a same-model comparison, but they must be explicit
# so a benchmark cannot silently change model or endpoint between producers.
: "${TURN_PLANNER_PROVIDER:?TURN_PLANNER_PROVIDER is required}"
: "${TURN_PLANNER_API_KEY:?TURN_PLANNER_API_KEY is required}"
: "${TURN_PLANNER_BASE_URL:?TURN_PLANNER_BASE_URL is required}"
: "${TURN_PLANNER_MODEL:?TURN_PLANNER_MODEL is required}"

if [[ "${HOST_MODEL_PROVIDER}" != "deepseek" ]]; then
  echo "Issue #357 protocol requires HOST_MODEL_PROVIDER=deepseek" >&2
  exit 2
fi
if [[ "${TURN_PLANNER_PROVIDER}" != "deepseek" ]]; then
  echo "Issue #357 protocol requires TURN_PLANNER_PROVIDER=deepseek" >&2
  exit 2
fi
export TURN_PLANNER_TIMEOUT_SECONDS=5
export TURN_PLANNER_MAX_ATTEMPTS=2
export TURN_PLANNER_RETRY_BACKOFF_SECONDS=0.25
export TURN_PLANNER_ROLLOUT_PERCENT=0
export ISSUE_357_SUBJECT_REVISION
ISSUE_357_SUBJECT_REVISION=$(git -C "${REPO_DIR}" rev-parse HEAD)

mkdir -p "${OUTPUT_DIR}/smoke" "${OUTPUT_DIR}/round-1" "${OUTPUT_DIR}/round-2"
cd "${BACKEND_DIR}"

report_calls() {
  uv run python - "$1" <<'PY'
import json
import sys

with open(sys.argv[1], encoding="utf-8") as stream:
    report = json.load(stream)
value = report["overall"]["transport_calls"]
print(value["total"] if isinstance(value, dict) else value)
PY
}

USED_CALLS=0
remaining_calls() {
  local remaining=$((TRANSPORT_CALL_CAP - USED_CALLS))
  if ((remaining < 1)); then
    echo "Issue #357 transport call cap reached: ${USED_CALLS}/${TRANSPORT_CALL_CAP}" >&2
    exit 1
  fi
  echo "${remaining}"
}

run_corpus() {
  local producer=$1
  local repetitions=$2
  local output=$3
  uv run python tests/benchmarks/issue_357_planner.py \
    --producer "${producer}" \
    --repetitions "${repetitions}" \
    --transport-call-budget "$(remaining_calls)" \
    --output "${output}"
  USED_CALLS=$((USED_CALLS + $(report_calls "${output}")))
}

run_e2e() {
  local producer=$1
  local repetitions=$2
  local output=$3
  if [[ "${producer}" == "legacy" ]]; then
    ISSUE_356_BENCHMARK_MODE=real \
    ISSUE_356_BENCHMARK_REPEATS="${repetitions}" \
    ISSUE_356_BENCHMARK_OUTPUT="${output}" \
    ISSUE_356_SUBJECT_REVISION="${ISSUE_357_SUBJECT_REVISION}" \
    ISSUE_357_TRANSPORT_CALL_BUDGET="$(remaining_calls)" \
      uv run pytest -s tests/benchmarks/issue_356_turn_run.py
  else
    ISSUE_357_TURN_BENCHMARK_REPEATS="${repetitions}" \
    ISSUE_357_TURN_BENCHMARK_OUTPUT="${output}" \
    ISSUE_357_TRANSPORT_CALL_BUDGET="$(remaining_calls)" \
      uv run pytest -s tests/benchmarks/issue_357_turn_run.py
  fi
  USED_CALLS=$((USED_CALLS + $(report_calls "${output}")))
}

echo "Running Issue #357 smoke (excluded from formal quality metrics)"
run_corpus legacy 1 "${OUTPUT_DIR}/smoke/legacy-corpus.json"
run_corpus semantic 1 "${OUTPUT_DIR}/smoke/semantic-corpus.json"
run_e2e legacy 1 "${OUTPUT_DIR}/smoke/legacy-e2e.json"
run_e2e semantic 1 "${OUTPUT_DIR}/smoke/semantic-e2e.json"
SMOKE_CALLS=${USED_CALLS}
uv run python tests/benchmarks/issue_357_compare.py smoke \
  --legacy-corpus "${OUTPUT_DIR}/smoke/legacy-corpus.json" \
  --semantic-corpus "${OUTPUT_DIR}/smoke/semantic-corpus.json" \
  --legacy-e2e "${OUTPUT_DIR}/smoke/legacy-e2e.json" \
  --semantic-e2e "${OUTPUT_DIR}/smoke/semantic-e2e.json" \
  --transport-call-cap "${TRANSPORT_CALL_CAP}" \
  --json-output "${OUTPUT_DIR}/smoke/comparison.json" \
  --markdown-output "${OUTPUT_DIR}/smoke/comparison.md"

echo "Running Issue #357 Round 1 (legacy first)"
run_corpus legacy 5 "${OUTPUT_DIR}/round-1/legacy-corpus.json"
run_corpus semantic 5 "${OUTPUT_DIR}/round-1/semantic-corpus.json"
run_e2e legacy 20 "${OUTPUT_DIR}/round-1/legacy-e2e.json"
run_e2e semantic 20 "${OUTPUT_DIR}/round-1/semantic-e2e.json"
uv run python tests/benchmarks/issue_357_compare.py round \
  --round 1 \
  --legacy-corpus "${OUTPUT_DIR}/round-1/legacy-corpus.json" \
  --semantic-corpus "${OUTPUT_DIR}/round-1/semantic-corpus.json" \
  --legacy-e2e "${OUTPUT_DIR}/round-1/legacy-e2e.json" \
  --semantic-e2e "${OUTPUT_DIR}/round-1/semantic-e2e.json" \
  --prior-transport-calls "${SMOKE_CALLS}" \
  --transport-call-cap "${TRANSPORT_CALL_CAP}" \
  --json-output "${OUTPUT_DIR}/round-1/comparison.json" \
  --markdown-output "${OUTPUT_DIR}/round-1/comparison.md"
ROUND_1_CALLS=$((USED_CALLS - SMOKE_CALLS))

echo "Running Issue #357 Round 2 (semantic first)"
run_corpus semantic 5 "${OUTPUT_DIR}/round-2/semantic-corpus.json"
run_corpus legacy 5 "${OUTPUT_DIR}/round-2/legacy-corpus.json"
run_e2e semantic 20 "${OUTPUT_DIR}/round-2/semantic-e2e.json"
run_e2e legacy 20 "${OUTPUT_DIR}/round-2/legacy-e2e.json"
ROUND_2_STATUS=0
uv run python tests/benchmarks/issue_357_compare.py round \
  --round 2 \
  --legacy-corpus "${OUTPUT_DIR}/round-2/legacy-corpus.json" \
  --semantic-corpus "${OUTPUT_DIR}/round-2/semantic-corpus.json" \
  --legacy-e2e "${OUTPUT_DIR}/round-2/legacy-e2e.json" \
  --semantic-e2e "${OUTPUT_DIR}/round-2/semantic-e2e.json" \
  --prior-transport-calls "$((SMOKE_CALLS + ROUND_1_CALLS))" \
  --transport-call-cap "${TRANSPORT_CALL_CAP}" \
  --json-output "${OUTPUT_DIR}/round-2/comparison.json" \
  --markdown-output "${OUTPUT_DIR}/round-2/comparison.md" || ROUND_2_STATUS=$?

SUMMARY_STATUS=0
uv run python tests/benchmarks/issue_357_compare.py summary \
  --round-1 "${OUTPUT_DIR}/round-1/comparison.json" \
  --round-2 "${OUTPUT_DIR}/round-2/comparison.json" \
  --transport-call-cap "${TRANSPORT_CALL_CAP}" \
  --json-output "${OUTPUT_DIR}/summary.json" \
  --markdown-output "${OUTPUT_DIR}/summary.md" || SUMMARY_STATUS=$?

echo "Issue #357 validation complete: ${OUTPUT_DIR}"
if ((ROUND_2_STATUS != 0 || SUMMARY_STATUS != 0)); then
  exit 1
fi
