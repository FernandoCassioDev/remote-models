#!/usr/bin/env python3
"""
laptop_setup.py  -  run on the LAPTOP.

Finds your PC's Ollama server (via Tailscale or a host you give it), lets you
pick a model, writes the Hermes Agent config, and verifies the whole chain
with a real chat request.  No third-party dependencies.

Usage:
    python3 laptop_setup.py                       # auto-discover over Tailscale
    python3 laptop_setup.py --host 100.101.102.103
    python3 laptop_setup.py --host my-pc --model qwen2.5-coder:14b --ctx 65536
    python3 laptop_setup.py --check               # only test, don't write config
"""
import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path

PORT = 11434


# ---------- tiny HTTP helpers ----------
def http_json(url, payload=None, timeout=5):
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode())


def ollama_alive(host, timeout=2):
    try:
        http_json(f"http://{host}:{PORT}/api/tags", timeout=timeout)
        return True
    except Exception:
        return False


# ---------- discovery ----------
def tailscale_peers():
    """Return [(name, ip)] of online Tailscale peers."""
    if not shutil.which("tailscale"):
        return []
    try:
        out = subprocess.run(["tailscale", "status", "--json"], capture_output=True, text=True, timeout=10)
        data = json.loads(out.stdout)
    except Exception:
        return []
    peers = []
    for p in (data.get("Peer") or {}).values():
        if not p.get("Online"):
            continue
        ips = [ip for ip in p.get("TailscaleIPs", []) if "." in ip]  # IPv4
        if ips:
            peers.append((p.get("HostName", "?"), ips[0]))
    return peers


def discover():
    peers = tailscale_peers()
    if not peers:
        return None
    print(f"[..] Probing {len(peers)} Tailscale peer(s) for Ollama on :{PORT}")
    found = []
    for name, ip in peers:
        ok = ollama_alive(ip)
        print(f"     {name:<20} {ip:<16} {'OLLAMA OK' if ok else '-'}")
        if ok:
            found.append((name, ip))
    if not found:
        return None
    if len(found) == 1:
        return found[0][1]
    for i, (n, ip) in enumerate(found, 1):
        print(f"  {i}) {n} ({ip})")
    choice = input("Which one? [1] ").strip() or "1"
    return found[int(choice) - 1][1]


# ---------- model selection ----------
def list_models(host):
    try:
        tags = http_json(f"http://{host}:{PORT}/api/tags")
        return [m["name"] for m in tags.get("models", [])]
    except Exception:
        data = http_json(f"http://{host}:{PORT}/v1/models")
        return [m["id"] for m in data.get("data", [])]


def pick_model(models, wanted):
    if wanted:
        if wanted not in models:
            sys.exit(f"[!!] Model '{wanted}' not on the PC. Available: {', '.join(models)}")
        return wanted
    if len(models) == 1:
        return models[0]
    print("Models on the PC:")
    for i, m in enumerate(models, 1):
        print(f"  {i}) {m}")
    choice = input("Pick one [1] ").strip() or "1"
    return models[int(choice) - 1]


# ---------- Hermes config ----------
def render_model_block(model, base_url, ctx):
    return (
        "model:\n"
        f"  default: {model}\n"
        "  provider: custom\n"
        f"  base_url: {base_url}\n"
        f"  context_length: {ctx}\n"
    )


def write_config(path, block):
    """Replace the top-level `model:` block, keep everything else. Backs up first."""
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        path.write_text(block)
        return None
    backup = path.with_name(f"{path.name}.bak-{datetime.now():%Y%m%d-%H%M%S}")
    shutil.copy2(path, backup)

    lines = path.read_text().splitlines(keepends=True)
    start = next((i for i, l in enumerate(lines) if re.match(r"^model\s*:", l)), None)
    if start is None:
        sep = "" if (not lines or lines[-1].endswith("\n")) else "\n"
        path.write_text("".join(lines) + sep + "\n" + block)
        return backup
    end = start + 1
    while end < len(lines):
        l = lines[end]
        # block continues while lines are indented, blank, or comments
        if l.strip() == "" or l.startswith((" ", "\t", "#")):
            end += 1
        else:
            break
    lines[start:end] = [block]
    path.write_text("".join(lines))
    return backup


# ---------- verification ----------
def loaded_context(host, model):
    """Context Ollama actually loaded for the model (newer Ollama versions report it)."""
    try:
        ps = http_json(f"http://{host}:{PORT}/api/ps")
        for m in ps.get("models", []):
            if m.get("name") == model or m.get("model") == model:
                return m.get("context_length")
    except Exception:
        pass
    return None


def verify_chat(base_url, model):
    t0 = time.time()
    try:
        r = http_json(
            f"{base_url}/chat/completions",
            {"model": model, "messages": [{"role": "user", "content": "Reply with the single word: ready"}],
             "max_tokens": 16, "stream": False},
            timeout=300,  # first call may need to load the model into VRAM
        )
        text = r["choices"][0]["message"]["content"].strip()
        return True, text, time.time() - t0
    except Exception as e:
        return False, str(e), time.time() - t0


# ---------- main ----------
def main():
    ap = argparse.ArgumentParser(description="Point Hermes Agent at the Ollama server on your PC.")
    ap.add_argument("--host", help="PC Tailscale IP or MagicDNS name (auto-discovered if omitted)")
    ap.add_argument("--model", help="Model name (asks if omitted)")
    ap.add_argument("--ctx", type=int, default=65536, help="context_length for Hermes (default 65536)")
    ap.add_argument("--config", default=os.path.join(os.environ.get("HERMES_HOME", Path.home() / ".hermes"), "config.yaml"),
                    help="Hermes config path (default ~/.hermes/config.yaml)")
    ap.add_argument("--check", action="store_true", help="only test connectivity, don't touch the config")
    a = ap.parse_args()

    host = a.host or discover()
    if not host:
        sys.exit("[!!] Couldn't auto-discover the PC. Is Tailscale up on both machines?\n"
                 "     Run again with --host <pc-tailscale-ip>.")
    if not ollama_alive(host, timeout=5):
        sys.exit(f"[!!] Can't reach http://{host}:{PORT}. Check on the PC: Ollama running, "
                 "OLLAMA_HOST=0.0.0.0:11434, firewall, Tailscale connected (run pc_setup first).")
    print(f"[ok] Ollama reachable at {host}:{PORT}")

    models = list_models(host)
    if not models:
        sys.exit("[!!] Ollama is up but has no models. On the PC: ollama pull <model>")
    model = pick_model(models, a.model)
    base_url = f"http://{host}:{PORT}/v1"

    if not a.check:
        backup = write_config(Path(a.config), render_model_block(model, base_url, a.ctx))
        print(f"[ok] Wrote Hermes config -> {a.config}")
        if backup:
            print(f"     (previous config backed up to {backup})")

    print(f"[..] Test chat with {model} (first call loads the model, can take a while)")
    ok, text, secs = verify_chat(base_url, model)
    if not ok:
        sys.exit(f"[!!] Chat request failed: {text}")
    print(f"[ok] Model answered in {secs:.1f}s: {text!r}")

    ctx = loaded_context(host, model)
    if ctx and ctx != a.ctx:
        print(f"[!!] Ollama loaded context_length={ctx} but Hermes is set to {a.ctx}.\n"
              f"     Fix on the PC: set OLLAMA_CONTEXT_LENGTH={a.ctx} and restart Ollama "
              "(pc_setup does this), or rerun this script with --ctx matching.")
    elif ctx:
        print(f"[ok] Context matches on both sides ({ctx})")

    print("\nDone. Start it with:  hermes")


if __name__ == "__main__":
    main()
