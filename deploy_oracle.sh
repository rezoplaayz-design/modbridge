#!/usr/bin/env bash
set -e

APP_DIR="$(cd "$(dirname "$0")" && pwd)"
SERVICE_NAME="modbridge"
PYTHON_BIN="$(command -v python3)"

if [ -z "$PYTHON_BIN" ]; then
  echo "python3 not found. Install it first: sudo apt update && sudo apt install -y python3"
  exit 1
fi

sudo tee /etc/systemd/system/${SERVICE_NAME}.service >/dev/null <<EOF
[Unit]
Description=ModBridge Java-to-Bedrock Web App
After=network.target

[Service]
Type=simple
User=$USER
WorkingDirectory=$APP_DIR
Environment=HOST=0.0.0.0
Environment=PORT=8765
ExecStart=$PYTHON_BIN $APP_DIR/server.py
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable --now ${SERVICE_NAME}

echo
echo "ModBridge service installed."
echo "Status: sudo systemctl status ${SERVICE_NAME}"
echo "Logs:   journalctl -u ${SERVICE_NAME} -f"
echo
echo "Remember to allow TCP port 8765 in your Oracle Cloud VCN/Security List."
