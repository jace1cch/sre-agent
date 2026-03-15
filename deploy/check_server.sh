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
grep '^WEBHOOK_URL=' "${ENV_FILE}" || true

echo "Checking container access"
container_name="$(grep '^APP_CONTAINER_NAME=' "${ENV_FILE}" | cut -d'=' -f2- | tr -d '"' || true)"
if [ -n "${container_name}" ]; then
  docker inspect "${container_name}" >/dev/null 2>&1 && echo "Container found: ${container_name}" || echo "Container not found: ${container_name}"
fi

echo "Running one diagnosis cycle"
PYTHONPATH=src "${PYTHON_BIN}" -m sre_agent.run || true

echo "Server check complete"
