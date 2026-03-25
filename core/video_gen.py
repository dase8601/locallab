"""
locallab · core/video_gen.py
─────────────────────────────
Text-to-video generation subprocess. Runs independently from Flask so
the heavy torch/diffusers memory footprint stays isolated.

Called by ui/app.py via subprocess.Popen:
  python core/video_gen.py --prompt "..." --output /path/out.mp4 --duration 5

Prints JSON lines to stdout for SSE progress streaming:
  {"type": "progress", "message": "Loading model..."}
  {"type": "done",     "output": "/path/out.mp4"}
  {"type": "error",    "message": "...", "install": "pip install ..."}

Requirements (optional — install separately):
  pip install diffusers torch transformers accelerate imageio[ffmpeg]

Model: Lightricks/LTX-Video (~8GB download on first run)
  - MPS (Apple Silicon), CUDA, or CPU (slow)
  - Generates ~5-second clips at 512x288 @ 8fps
"""

import argparse
import json
import sys
from pathlib import Path


def _emit(data: dict):
    print(json.dumps(data), flush=True)


def generate(prompt: str, output_path: str, duration_seconds: int, model_id: str,
             fps: int, width: int, height: int):
    # ── Check dependencies ─────────────────────────────────────────
    try:
        import torch
    except ImportError:
        _emit({"type": "error",
               "message": "torch is not installed.",
               "install": "pip install diffusers torch transformers accelerate imageio[ffmpeg]"})
        sys.exit(1)

    try:
        from diffusers import LTXPipeline, CogVideoXPipeline
    except ImportError:
        _emit({"type": "error",
               "message": "diffusers is not installed.",
               "install": "pip install diffusers torch transformers accelerate imageio[ffmpeg]"})
        sys.exit(1)

    try:
        import imageio
    except ImportError:
        _emit({"type": "error",
               "message": "imageio is not installed.",
               "install": "pip install imageio[ffmpeg]"})
        sys.exit(1)

    # ── Device selection ───────────────────────────────────────────
    if torch.cuda.is_available():
        device = "cuda"
        dtype  = torch.float16
    elif hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
        device = "mps"
        dtype  = torch.bfloat16
    else:
        device = "cpu"
        dtype  = torch.float32

    _emit({"type": "progress", "message": f"Using device: {device}"})

    # ── Load pipeline ──────────────────────────────────────────────
    _emit({"type": "progress",
           "message": f"Loading model {model_id} (first run downloads ~8GB)…"})

    try:
        if "LTX" in model_id or "ltx" in model_id.lower():
            pipe = LTXPipeline.from_pretrained(model_id, torch_dtype=dtype)
        else:
            pipe = CogVideoXPipeline.from_pretrained(model_id, torch_dtype=dtype)
        pipe = pipe.to(device)
    except Exception as e:
        _emit({"type": "error", "message": f"Failed to load model: {e}"})
        sys.exit(1)

    # ── Generate ───────────────────────────────────────────────────
    num_frames = duration_seconds * fps
    _emit({"type": "progress",
           "message": f"Generating {duration_seconds}s clip ({num_frames} frames)…"})

    try:
        result = pipe(
            prompt=prompt,
            num_frames=num_frames,
            width=width,
            height=height,
            guidance_scale=3.0,
        )
        frames = result.frames[0]
    except Exception as e:
        _emit({"type": "error", "message": f"Generation failed: {e}"})
        sys.exit(1)

    # ── Save ───────────────────────────────────────────────────────
    _emit({"type": "progress", "message": "Saving video…"})
    output_path = str(Path(output_path).resolve())
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)

    try:
        with imageio.get_writer(output_path, fps=fps, codec="libx264",
                                quality=7, macro_block_size=1) as writer:
            for frame in frames:
                import numpy as np
                if hasattr(frame, "numpy"):
                    frame = frame.numpy()
                writer.append_data(np.array(frame))
    except Exception as e:
        _emit({"type": "error", "message": f"Failed to save video: {e}"})
        sys.exit(1)

    _emit({"type": "done", "output": output_path})


if __name__ == "__main__":
    p = argparse.ArgumentParser(description="locallab text-to-video generation")
    p.add_argument("--prompt",   required=True,  help="Text prompt for video")
    p.add_argument("--output",   required=True,  help="Output .mp4 path")
    p.add_argument("--duration", type=int, default=5,   help="Duration in seconds")
    p.add_argument("--model",    default="Lightricks/LTX-Video", help="HuggingFace model ID")
    p.add_argument("--fps",      type=int, default=8,   help="Frames per second")
    p.add_argument("--width",    type=int, default=512, help="Video width")
    p.add_argument("--height",   type=int, default=288, help="Video height")
    args = p.parse_args()

    generate(
        prompt=args.prompt,
        output_path=args.output,
        duration_seconds=args.duration,
        model_id=args.model,
        fps=args.fps,
        width=args.width,
        height=args.height,
    )
