# remote models

Use the local model on your PC from Hermes Agent on your laptop.

```
laptop (Hermes + tools)  --Tailscale-->  PC (Ollama + GPU)
```

Only inference runs on the PC. Hermes and the commands it executes stay on the laptop.

## Setup (2 steps)

**1. On the PC** (pick the one that matches where Ollama runs)

| Ollama runs in | Run |
|---|---|
| Linux / WSL2 | `bash pc_setup.sh` |
| Native Windows | admin PowerShell: `.\pc_setup.ps1` |

It installs and logs into Tailscale, exposes Ollama on the network, sets a long context, enables flash attention and a q8 KV cache (saves VRAM), and prints the PC's Tailscale IP. Smaller context if VRAM is tight: `CTX=32768 bash pc_setup.sh` or `.\pc_setup.ps1 -Ctx 32768`.

**2. On the laptop** (install Tailscale and log in with the same account first)

```bash
python3 laptop_setup.py                  # auto-discovers the PC
python3 laptop_setup.py --host <pc-ip>   # or point it manually
```

It finds Ollama, lets you pick a model, writes `model:` in `~/.hermes/config.yaml` (other keys are kept, a timestamped backup is made), sends a test chat, and warns if the context loaded by Ollama differs from the one Hermes expects. Then just run `hermes`.

Useful flags: `--model NAME`, `--ctx N` (must match the PC), `--check` (test only, no config changes), `--config PATH`.

## Troubleshooting

- **Can't reach the PC:** Tailscale up on both? `tailscale status` should list the other machine as online.
- **Reachable on the PC but not from the laptop (WSL2):** use `pc_setup.sh` inside WSL so WSL becomes its own Tailscale node.
- **Slow first answer:** the model is being loaded into VRAM. `OLLAMA_KEEP_ALIVE` keeps it loaded afterwards (30m by default).
- **Out of VRAM / very slow:** lower the context (`CTX=32768`) or use a smaller model/quant. Rerun `laptop_setup.py --ctx 32768` so both sides match.
- **Don't put LiteLLM or another proxy in between.** Hermes probes Ollama-style endpoints and it can hang.
- **Security:** Ollama has no auth. Keep it reachable only through Tailscale (the scripts restrict the firewall accordingly) and never port-forward 11434.
