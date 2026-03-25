"""
core/vjepa_utils.py
───────────────────
V-JEPA 2.1 keyframe selection for video ingestion.

One-time setup (optional):
  python scripts/setup_vjepa.py

If not installed, select_keyframes() silently returns a uniform subsample.
"""
from pathlib import Path

VJEPA_CACHE = Path.home() / ".cache" / "locallab" / "vjepa"
VJEPA2_REPO = Path(__file__).parent / "vjepa2"    # git clone target
VIT_B_PATH  = VJEPA_CACHE / "vit_b.pth"

_model_cache = None   # module-level singleton (loaded once per process)


def _load_model():
    """Return (model, device) or (None, None) if V-JEPA is not installed."""
    global _model_cache
    if _model_cache is not None:
        return _model_cache
    try:
        import torch
        import sys
        if not VJEPA2_REPO.exists() or not VIT_B_PATH.exists():
            _model_cache = (None, None)
            return _model_cache
        sys.path.insert(0, str(VJEPA2_REPO))
        from vision_transformer import vit_b  # from cloned vjepa2 repo
        device = ("mps" if torch.backends.mps.is_available() else
                  "cuda" if torch.cuda.is_available() else "cpu")
        model = vit_b()
        ckpt = torch.load(str(VIT_B_PATH), map_location=device, weights_only=False)
        sd = ckpt.get("model") or ckpt.get("state_dict") or ckpt
        model.load_state_dict(sd, strict=False)
        model = model.to(device).eval()
        _model_cache = (model, device)
        print(f"  [vjepa] ViT-B loaded on {device}", flush=True)
    except Exception as e:
        print(f"  [vjepa] unavailable ({e}), using uniform fallback", flush=True)
        _model_cache = (None, None)
    return _model_cache


def _embed(model, device, frame_path: Path):
    """Return a 768-d L2-normalised embedding for one frame (resized to 256x256)."""
    import torch
    import torch.nn.functional as F
    import numpy as np
    from PIL import Image

    img = Image.open(frame_path).convert("RGB").resize((256, 256))
    arr = (np.array(img, dtype=np.float32) / 255.0
           - [0.485, 0.456, 0.406]) / [0.229, 0.224, 0.225]
    t = torch.tensor(arr).permute(2, 0, 1).unsqueeze(0).float().to(device)
    with torch.no_grad():
        f = model(t)
        if f.dim() == 3:
            f = f.mean(1)   # (1, num_patches, 768) → (1, 768)
        f = F.normalize(f, dim=-1)
    return f.squeeze(0).cpu()   # (768,)


def select_keyframes(frame_paths: list, max_frames: int = 12) -> list:
    """
    Return up to max_frames paths selected for maximum visual diversity,
    using V-JEPA ViT-B farthest-point sampling on cosine distance.

    Falls back to uniform subsampling if V-JEPA is unavailable.
    Temporal order is preserved in the returned list.
    """
    if not frame_paths:
        return []

    model, device = _load_model()

    if model is None:
        step = max(1, len(frame_paths) // max_frames)
        return frame_paths[::step][:max_frames]

    import torch

    embs, valid_paths = [], []
    for fp in frame_paths:
        try:
            embs.append(_embed(model, device, fp))
            valid_paths.append(fp)
        except Exception:
            pass

    if not valid_paths:
        step = max(1, len(frame_paths) // max_frames)
        return frame_paths[::step][:max_frames]

    E = torch.stack(embs)       # (N, 768) — already L2-normalised

    # Greedy farthest-point sampling
    sel = [0]
    for _ in range(min(max_frames - 1, len(valid_paths) - 1)):
        sims = (E @ E[sel].T).max(dim=1).values   # highest similarity to any selected
        sims[sel] = 2.0                            # exclude already-selected frames
        sel.append(int(sims.argmin()))             # pick the most dissimilar frame

    sel.sort()  # restore temporal order
    return [valid_paths[i] for i in sel]
