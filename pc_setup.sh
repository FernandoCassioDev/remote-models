#!/usr/bin/env bash
# pc_setup.sh  -  run on the PC if Ollama lives in Linux / WSL2.
# Installs Tailscale, makes Ollama listen on the network, sets a long context.
#
#   bash pc_setup.sh                 # defaults: ctx 65536
#   CTX=32768 bash pc_setup.sh       # smaller context if VRAM is tight
set -euo pipefail

CTX="${CTX:-65536}"
KEEP_ALIVE="${KEEP_ALIVE:-30m}"

say() { printf '\033[1;32m[ok]\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m[!!]\033[0m %s\n' "$*"; }

# 1) Tailscale -------------------------------------------------------------
if ! command -v tailscale >/dev/null; then
  say "Installing Tailscale"
  curl -fsSL https://tailscale.com/install.sh | sh
fi
if ! tailscale ip -4 >/dev/null 2>&1; then
  say "Logging into Tailscale (follow the link it prints)"
  sudo tailscale up
fi
TS_IP="$(tailscale ip -4 | head -n1)"
say "Tailscale IP of this machine: $TS_IP"

# 2) Ollama env ------------------------------------------------------------
command -v ollama >/dev/null || { warn "ollama not found - install it first: https://ollama.com"; exit 1; }

# FLASH_ATTENTION + q8_0 KV cache roughly halve the VRAM used by a long context.
ENV_LINES=(
  "OLLAMA_HOST=0.0.0.0:11434"
  "OLLAMA_CONTEXT_LENGTH=$CTX"
  "OLLAMA_KEEP_ALIVE=$KEEP_ALIVE"
  "OLLAMA_FLASH_ATTENTION=1"
  "OLLAMA_KV_CACHE_TYPE=q8_0"
)

if [ -d /run/systemd/system ] && systemctl list-unit-files 2>/dev/null | grep -q '^ollama.service'; then
  say "Configuring the ollama systemd service"
  sudo mkdir -p /etc/systemd/system/ollama.service.d
  {
    echo "[Service]"
    for l in "${ENV_LINES[@]}"; do echo "Environment=\"$l\""; done
  } | sudo tee /etc/systemd/system/ollama.service.d/remote.conf >/dev/null
  sudo systemctl daemon-reload
  sudo systemctl restart ollama
  say "Ollama restarted with remote access"
else
  warn "No ollama systemd service (normal on WSL without systemd). Starting it in the background."
  pkill -x ollama 2>/dev/null || true
  sleep 1
  env "${ENV_LINES[@]}" nohup ollama serve >/tmp/ollama-remote.log 2>&1 &
  say "ollama serve started (log: /tmp/ollama-remote.log)"
  warn "It won't auto-start after reboot. To make it permanent, add this to ~/.bashrc:"
  printf '    pgrep -x ollama >/dev/null || (env %s nohup ollama serve >/tmp/ollama-remote.log 2>&1 &)\n' "${ENV_LINES[*]}"
fi

# 3) Firewall (only if ufw is active) --------------------------------------
if command -v ufw >/dev/null && sudo ufw status 2>/dev/null | grep -q "Status: active"; then
  sudo ufw allow in on tailscale0 to any port 11434 proto tcp >/dev/null
  say "ufw: allowed 11434 on the tailscale0 interface only"
fi

# 4) Self-test -------------------------------------------------------------
sleep 2
if curl -fsS "http://$TS_IP:11434/api/tags" >/dev/null; then
  say "Ollama answers on http://$TS_IP:11434"
else
  warn "Ollama didn't answer on $TS_IP:11434 - check: journalctl -u ollama (or /tmp/ollama-remote.log)"
fi

cat <<EOF

Next, on the LAPTOP (with Tailscale installed + logged into the same account):
    python3 laptop_setup.py --host $TS_IP

WSL2 note: this makes the WSL instance its own Tailscale node, so the laptop talks
straight to WSL - no Windows port-forwarding or .wslconfig tweaks needed.
EOF
