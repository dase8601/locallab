#!/usr/bin/env python3
"""
scripts/setup_vjepa.py
One-command V-JEPA 2.1 setup for locallab.

Installs pip dependencies, clones the vjepa2 repo, and downloads the
ViT-B weights (~300 MB) to ~/.cache/locallab/vjepa/vit_b.pth.

Usage:
  source venv/bin/activate
  python scripts/setup_vjepa.py
"""
import subprocess
import sys
import urllib.request
from pathlib import Path

BASE  = Path(__file__).parent.parent
REPO  = BASE / "core" / "vjepa2"
CACHE = Path.home() / ".cache" / "locallab" / "vjepa"
URL   = "https://dl.fbaipublicfiles.com/vjepa2/vit_b_ViT-B_VJEPA2.pth"

# 1. pip dependencies
print("Installing pip dependencies…")
subprocess.check_call([sys.executable, "-m", "pip", "install",
                       "torch", "torchvision", "timm", "einops"])
print("✓ pip deps installed\n")

# 2. Clone vjepa2 repo into core/vjepa2/
if not REPO.exists():
    print("Cloning facebookresearch/vjepa2 into core/vjepa2/…")
    subprocess.check_call(["git", "clone",
                           "https://github.com/facebookresearch/vjepa2.git",
                           str(REPO)])
    print("✓ vjepa2 repo cloned\n")
else:
    print(f"✓ vjepa2 repo already present at {REPO}\n")

# 3. Download ViT-B weights (~300 MB)
CACHE.mkdir(parents=True, exist_ok=True)
dst = CACHE / "vit_b.pth"
if not dst.exists():
    print(f"Downloading ViT-B weights to {dst}  (~300 MB, may take a minute)…")
    urllib.request.urlretrieve(URL, dst)
    size_mb = dst.stat().st_size / (1024 ** 2)
    print(f"✓ Weights saved ({size_mb:.0f} MB)\n")
else:
    size_mb = dst.stat().st_size / (1024 ** 2)
    print(f"✓ Weights already at {dst}  ({size_mb:.0f} MB)\n")

print("Setup complete.")
print("V-JEPA keyframe selection is now active for video ingestion in locallab.")
print("Re-ingest any existing videos to apply the new pipeline.")
