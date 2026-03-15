#!/usr/bin/env bash
set -euo pipefail

INSTALL_DIR="${INSTALL_DIR:-/opt/sre-agent}"
ENV_FILE="${ENV_FILE:-/etc/sre-agent.env}"
SERVICE_FILE="${SERVICE_FILE:-/etc/systemd/system/sre-agent.service}"
PYTHON_BIN="${PYTHON_BIN:-python3}"
ENV_TEMPLATE="${ENV_TEMPLATE:-deploy/examples/tencent-cloud-cvm-2c2g.env}"

echo "[1/6] Preparing install directory: ${INSTALL_DIR}"
mkdir -p "${INSTALL_DIR}"

echo "[2/6] Creating virtual environment"
cd "${INSTALL_DIR}"
if [ ! -d ".venv" ]; then
  "${PYTHON_BIN}" -m venv .venv
fi

echo "[3/6] Installing package"
.venv/bin/pip install --upgrade pip
.venv/bin/pip install .

echo "[4/6] Preparing environment file"
if [ ! -f "${ENV_FILE}" ]; then
  cp "${ENV_TEMPLATE}" "${ENV_FILE}"
  echo "Created ${ENV_FILE}. Please edit it before starting the service."
fi

echo "[5/6] Installing systemd service"
cat > "${SERVICE_FILE}" <<EOF
[Unit]
Description=SRE Agent Monitor Service
After=network-online.target docker.service
Wants=network-online.target

[Service]
Type=simple
User=root
WorkingDirectory=${INSTALL_DIR}
Environment=PYTHONPATH=${INSTALL_DIR}/src
EnvironmentFile=${ENV_FILE}
ExecStart=${INSTALL_DIR}/.venv/bin/python -m sre_agent.cli.main monitor
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

echo "[6/6] Reloading systemd"
systemctl daemon-reload

echo "Install complete. Next steps:"
echo "  1. Edit ${ENV_FILE}"
echo "  2. Run: systemctl enable sre-agent"
echo "  3. Run: systemctl start sre-agent"
echo "  4. Run: journalctl -u sre-agent -f"
