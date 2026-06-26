# ONNX int8 export — runbook (run on a machine with ≥ ~6GB free RAM)

One-time job: produces `sidecars/model_server/models/bge-m3-int8.onnx` (the int8
artifact the server loads / ships to prod). It OOMs on RAM-tight boxes (needs
~4–5GB peak: FP32 model + ONNX graph in memory at once). Run it once anywhere
with headroom; reuse the resulting file everywhere. **Slow CPU is fine — it runs once.**

> This machine has **no cached model** — the first run downloads bge-m3 (~2.3GB)
> into `models/` (local to the sidecar folder; gitignored). So do **NOT** set
> `HF_HUB_OFFLINE` here.

## Prereqs
- git, Python 3.12, and `uv` (`pip install uv` if missing).

## Steps

```bash
# 1. Clone
git clone https://github.com/saran-cks/eaiplatform
cd eaiplatform/sidecars/model_server

# 2. Create venv + install export deps (torch + transformers come via FlagEmbedding)
uv venv
uv pip install -p .venv FlagEmbedding onnxruntime onnx onnxscript

# 3. Run the export FROM THE REPO ROOT (first run downloads bge-m3 ~2.3GB)
cd ../..        # back to repo root
```

Then, **Windows (PowerShell):**
```powershell
$env:PYTHONPATH="."; $env:PYTHONIOENCODING="utf-8"
sidecars/model_server/.venv/Scripts/python.exe -m sidecars.model_server.scripts.export_quantize
```

**Linux / macOS:**
```bash
PYTHONPATH=. PYTHONIOENCODING=utf-8 \
  sidecars/model_server/.venv/bin/python -m sidecars.model_server.scripts.export_quantize
```

## Expected
Logs: download → export (opset 18, dynamo, optimize=False) → dynamic int8 quantize →
per-query `dense=… sparse=…` cosines → `PASS — both heads preserved within tolerance.`
Artifact: `sidecars/model_server/models/bge-m3-int8.onnx` (~560MB). Gate is
dense cosine ≥ 0.999, sparse cosine ≥ 0.99 vs the FP32 FlagEmbedding reference.

## Bring the artifact back
`models/` is gitignored, so git will **not** carry it. Copy
`bge-m3-int8.onnx` to the target machine's `sidecars/model_server/models/`
via cloud drive / USB / scp. (A proper artifact store can come later.)

## If it still OOMs
Free RAM, or set the env `EMBED_USE_FP16=true` is **not** enough on its own —
the export script controls precision; ping for the fp16-export variant if needed.
