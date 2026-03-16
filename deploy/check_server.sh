#!/usr/bin/env bash
set -euo pipefail

ENV_FILE="${ENV_FILE:-/etc/sre-agent.env}"
PYTHON_BIN="${PYTHON_BIN:-python3}"

echo "Checking Python"
"${PYTHON_BIN}" --version

echo "Checking Docker"
docker --version

echo "Checking env file"
if [ ! -f "${ENV_FILE}" ]; then
  echo "Missing ${ENV_FILE}"
  exit 1
fi

echo "Checking service configuration values"
grep '^APP_CONTAINER_NAME=' "${ENV_FILE}" || true
grep '^APP_CONTAINER_NAMES=' "${ENV_FILE}" || true
grep '^WEBHOOK_URL=' "${ENV_FILE}" || true
grep '^GRAPH_ENABLE_AUTONOMOUS_LOOP=' "${ENV_FILE}" || true
grep '^PROMETHEUS_BASE_URL=' "${ENV_FILE}" || true
grep '^CODEBASE_PATH=' "${ENV_FILE}" || true

echo "Checking container access"
container_names="$(grep '^APP_CONTAINER_NAMES=' "${ENV_FILE}" | cut -d'=' -f2- | tr -d '"' || true)"
if [ -z "${container_names}" ]; then
  container_names="$(grep '^APP_CONTAINER_NAME=' "${ENV_FILE}" | cut -d'=' -f2- | tr -d '"' || true)"
fi

IFS=',' read -r -a container_array <<< "${container_names}"
for raw_name in "${container_array[@]}"; do
  container_name="${raw_name// /}"
  if [ -z "${container_name}" ]; then
    continue
  fi
  docker inspect "${container_name}" >/dev/null 2>&1 && echo "Container found: ${container_name}" || echo "Container not found: ${container_name}"
done

echo "Running deployment readiness report"
PYTHONPATH=src "${PYTHON_BIN}" -m sre_agent.cli.main check-deploy || true

echo "Running one diagnosis cycle"
PYTHONPATH=src "${PYTHON_BIN}" -m sre_agent.run || true

echo "Server check complete"