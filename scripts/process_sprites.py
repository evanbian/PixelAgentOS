#!/usr/bin/env python3
"""
Sprite post-processor: AI-powered background removal (rembg), smart bounding-box
detection, crop to 64×64 frames, assemble into horizontal spritesheets for Phaser 3.

Usage:
    # Process all sprites
    python process_sprites.py

    # Process only a specific role (matched against output name prefix)
    python process_sprites.py --only pm
    python process_sprites.py --only developer
    python process_sprites.py --only writer

Requires:
    pip install rembg pillow numpy
    (rembg will auto-download the U2Net ONNX model on first run ~170 MB)

Venv python:
    /Users/evanbian/agent_company/pixel-agent-os/backend/.venv/bin/python
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

import numpy as np
from PIL import Image
from rembg import remove

# ── Paths ─────────────────────────────────────────────────────────────────────
ROOT      = Path(__file__).resolve().parent.parent
GENERATED = ROOT / "frontend" / "public" / "assets" / "sprites" / "generated"
OUTPUT    = ROOT / "frontend" / "public" / "assets" / "sprites"

# ── Output geometry ───────────────────────────────────────────────────────────
FRAME_SIZE    = 64   # final character frame (pixels)
EMOTE_SIZE    = 24   # final emote icon frame (pixels)
FRAME_PADDING = 2    # reserved padding per side inside each frame (pixels)

# Bounding-box column scan: gaps narrower than this are treated as intra-character
# noise and merged into one region rather than split into two.
MERGE_GAP_PX = 8

# Alpha threshold – pixels whose alpha is at or below this value are considered
# transparent / background for bounding-box purposes.
ALPHA_THRESHOLD = 20

# ── Input → Output mapping ────────────────────────────────────────────────────
# Format: (source_filename, output_filename, frame_count, top_row_only)
#   source_filename  – file inside GENERATED/
#   output_filename  – file written to OUTPUT/
#   frame_count      – number of character frames expected in the strip
#   top_row_only     – True  → crop to the top half before processing
#                      (PM sheet has two rows; only the walking row is used)
ROLE_SPRITES: list[tuple[str, str, int, bool]] = [
    ("dev_sprites.png",          "developer_sheet.png",  4, False),
    ("researcher_sprites-1.jpg", "researcher_sheet.png", 4, False),
    ("analyst_sprites-1.jpg",    "analyst_sheet.png",    4, False),
    ("writer_sprites-1.jpg",     "writer_sheet.png",     4, False),
    ("designer_sprites.png",     "designer_sheet.png",   4, False),
    ("pm_sprites_v2-1.jpg",      "pm_sheet.png",         4, True),   # 2 rows, use top
    ("default_sprites.png",      "default_sheet.png",    4, False),
]

# Emotes are a separate horizontal strip of small icons
EMOTE_ENTRY: tuple[str, str, int] = ("emotes_v2-1.jpg", "emotes_sheet.png", 8)


# ── Background removal ────────────────────────────────────────────────────────

def chroma_key_green(img: Image.Image, tolerance: int = 80) -> Image.Image:
    """Remove green-screen background using colour distance.

    Works well for graphics / icons where the foreground doesn't contain
    significant amounts of green.  For character sprites with green clothing
    use remove_background() (rembg) instead.
    """
    rgba = img.convert("RGBA")
    arr = np.array(rgba, dtype=np.float32)
    r, g, b = arr[:, :, 0], arr[:, :, 1], arr[:, :, 2]
    # Distance from pure green (#00FF00)
    dist = np.sqrt(r ** 2 + (g - 255) ** 2 + b ** 2)
    # Soft edge: pixels very close to green → fully transparent,
    # pixels near the tolerance boundary → partially transparent
    alpha = np.clip((dist - tolerance * 0.4) / (tolerance * 0.6) * 255, 0, 255).astype(np.uint8)
    result = np.array(rgba)
    result[:, :, 3] = np.minimum(result[:, :, 3], alpha)
    return Image.fromarray(result, "RGBA")


def remove_background(img: Image.Image) -> Image.Image:
    """Use rembg (U2Net) to remove the background and return an RGBA image.

    rembg.remove() accepts a PIL Image and returns a PIL Image whose alpha
    channel encodes the foreground mask produced by the neural network.  This
    is far more robust than chroma-keying because it handles:
      - Non-green backgrounds
      - Complex hair / clothing edges
      - JPEG compression artefacts
    """
    # rembg expects RGB or RGBA; ensure we hand it a clean RGB image.
    rgb = img.convert("RGB")
    result: Image.Image = remove(rgb)          # returns RGBA
    return result.convert("RGBA")


# ── Bounding-box detection ────────────────────────────────────────────────────

def find_character_bboxes(
    img: Image.Image,
    expected_count: int,
) -> list[tuple[int, int, int, int]]:
    """Locate the bounding boxes of foreground characters by column scanning.

    Algorithm:
    1. Examine each column: does it contain any pixel with alpha > ALPHA_THRESHOLD?
    2. Collect contiguous runs of "content" columns as candidate regions.
    3. Merge adjacent regions whose gap is < MERGE_GAP_PX (handles small holes
       caused by thin limbs or transparent shirt patches).
    4. If the result count does not match expected_count, fall back to even
       equal-width splitting so we always return exactly expected_count boxes.
    5. For each accepted horizontal region, scan rows to tighten the vertical
       bounds (so we don't carry large amounts of empty top/bottom space).

    Returns a list of (x1, y1, x2, y2) tuples in image-pixel coordinates,
    ordered left to right.
    """
    arr   = np.array(img)
    alpha = arr[:, :, 3]

    # Step 1 – which columns contain at least one foreground pixel?
    col_has_content: np.ndarray = np.any(alpha > ALPHA_THRESHOLD, axis=0)

    # Step 2 – collect contiguous runs of content columns
    raw_regions: list[tuple[int, int]] = []
    in_region = False
    start = 0
    width = len(col_has_content)

    for x in range(width):
        if col_has_content[x] and not in_region:
            start = x
            in_region = True
        elif not col_has_content[x] and in_region:
            raw_regions.append((start, x))
            in_region = False
    if in_region:
        raw_regions.append((start, width))

    # Step 3 – merge regions separated by a gap narrower than MERGE_GAP_PX
    merged: list[tuple[int, int]] = []
    for region in raw_regions:
        if merged and (region[0] - merged[-1][1]) < MERGE_GAP_PX:
            merged[-1] = (merged[-1][0], region[1])
        else:
            merged.append(list(region))  # type: ignore[arg-type]

    # Convert nested lists back to tuples
    merged_tuples: list[tuple[int, int]] = [tuple(r) for r in merged]  # type: ignore[misc]

    # Step 4 – reconcile region count with expected_count
    if len(merged_tuples) < expected_count:
        # Detection found too few regions – fall back to even splitting
        print(
            f"    WARNING: detected {len(merged_tuples)} region(s), "
            f"expected {expected_count}. Using even split."
        )
        cell_w = img.width // expected_count
        merged_tuples = [
            (i * cell_w, (i + 1) * cell_w) for i in range(expected_count)
        ]

    elif len(merged_tuples) > expected_count:
        # Detection found too many regions – keep the widest ones (most likely
        # to be full characters rather than stray background fragments).
        merged_tuples.sort(key=lambda r: r[1] - r[0], reverse=True)
        merged_tuples = sorted(merged_tuples[:expected_count], key=lambda r: r[0])

    # Step 5 – tighten vertical bounds per horizontal region
    bboxes: list[tuple[int, int, int, int]] = []
    for x1, x2 in merged_tuples:
        col_slice = alpha[:, x1:x2]
        row_has_content = np.any(col_slice > ALPHA_THRESHOLD, axis=1)
        rows = np.where(row_has_content)[0]
        if len(rows) > 0:
            y1 = int(rows[0])
            y2 = int(rows[-1]) + 1
        else:
            y1, y2 = 0, img.height
        bboxes.append((int(x1), y1, int(x2), y2))

    return bboxes


# ── Frame composition ─────────────────────────────────────────────────────────

def crop_and_fit(
    img: Image.Image,
    bbox: tuple[int, int, int, int],
    size: int,
) -> Image.Image:
    """Crop a character from *img* and fit it into a *size* × *size* RGBA frame.

    Layout rules:
    - FRAME_PADDING pixels are reserved on every edge (prevents Phaser edge
      clipping artefacts when the spritesheet is rendered at non-integer scales).
    - The character is scaled uniformly to fill the remaining inner area.
    - Horizontally centred.
    - Bottom-aligned so all characters stand on the same baseline regardless of
      their individual heights.
    - LANCZOS resampling preserves soft edges produced by rembg's alpha matte.
    """
    x1, y1, x2, y2 = bbox
    cropped = img.crop((x1, y1, x2, y2))

    inner = size - 2 * FRAME_PADDING          # usable area after padding
    cw, ch = cropped.size

    # Uniform scale-to-fit
    scale = min(inner / max(cw, 1), inner / max(ch, 1))
    new_w = max(1, int(cw * scale))
    new_h = max(1, int(ch * scale))

    resized = cropped.resize((new_w, new_h), Image.LANCZOS)

    frame = Image.new("RGBA", (size, size), (0, 0, 0, 0))

    # Centre horizontally, bottom-align vertically inside the padded region
    ox = FRAME_PADDING + (inner - new_w) // 2
    oy = FRAME_PADDING + (inner - new_h)   # bottom-aligned

    frame.paste(resized, (ox, oy), resized)
    return frame


# ── Per-file processors ───────────────────────────────────────────────────────

def process_role_sprite(
    src_name: str,
    out_name: str,
    frame_count: int,
    top_row_only: bool,
) -> bool:
    """Process a single role sprite file into a horizontal spritesheet.

    Steps:
    1. Load source image.
    2. Optionally crop to the top half (PM sheet has two rows).
    3. Remove background with rembg.
    4. Detect character bounding boxes.
    5. Crop + fit each character into a FRAME_SIZE × FRAME_SIZE frame.
    6. Assemble frames into a horizontal spritesheet and save.
    """
    src_path = GENERATED / src_name
    if not src_path.exists():
        print(f"  SKIP: {src_name} not found in {GENERATED}")
        return False

    print(f"  Processing {src_name} -> {out_name}")

    img = Image.open(src_path).convert("RGB")
    print(f"    Source size: {img.size}")

    # PM sprite sheet has two rows of animations; only the top row (walking
    # cycle) is used in the game.
    if top_row_only:
        img = img.crop((0, 0, img.width, img.height // 2))
        print(f"    Cropped to top row: {img.size}")

    # AI background removal – replaces the old chroma-key logic
    print("    Removing background (rembg)…")
    img_rgba = remove_background(img)

    # Locate character regions within the strip
    bboxes = find_character_bboxes(img_rgba, frame_count)
    print(f"    Detected {len(bboxes)} region(s): {bboxes}")

    # Crop and fit each character into its own square frame
    frames: list[Image.Image] = []
    for i, bbox in enumerate(bboxes):
        frame = crop_and_fit(img_rgba, bbox, FRAME_SIZE)
        frames.append(frame)

    # Assemble horizontal spritesheet
    sheet_w = FRAME_SIZE * len(frames)
    sheet = Image.new("RGBA", (sheet_w, FRAME_SIZE), (0, 0, 0, 0))
    for i, frame in enumerate(frames):
        sheet.paste(frame, (i * FRAME_SIZE, 0), frame)

    out_path = OUTPUT / out_name
    sheet.save(out_path, "PNG")
    print(f"    Saved: {out_path}  ({sheet_w}×{FRAME_SIZE})")
    return True


def process_emotes(src_name: str, out_name: str, icon_count: int) -> bool:
    """Process an emote strip into a horizontal spritesheet of EMOTE_SIZE icons.

    The emote strip is processed the same way as role sprites but each icon is
    fitted into a smaller EMOTE_SIZE × EMOTE_SIZE frame.
    """
    src_path = GENERATED / src_name
    if not src_path.exists():
        print(f"  SKIP: {src_name} not found in {GENERATED}")
        return False

    print(f"  Processing emotes: {src_name} -> {out_name}")

    img = Image.open(src_path).convert("RGB")
    print(f"    Source size: {img.size}")

    print("    Removing green background (chroma key)…")
    img_rgba = chroma_key_green(img)

    bboxes = find_character_bboxes(img_rgba, icon_count)
    print(f"    Detected {len(bboxes)} icon(s)")

    frames: list[Image.Image] = []
    for bbox in bboxes:
        frame = crop_and_fit(img_rgba, bbox, EMOTE_SIZE)
        frames.append(frame)

    sheet_w = EMOTE_SIZE * len(frames)
    sheet = Image.new("RGBA", (sheet_w, EMOTE_SIZE), (0, 0, 0, 0))
    for i, frame in enumerate(frames):
        sheet.paste(frame, (i * EMOTE_SIZE, 0), frame)

    out_path = OUTPUT / out_name
    sheet.save(out_path, "PNG")
    print(f"    Saved: {out_path}  ({sheet_w}×{EMOTE_SIZE})")
    return True


# ── CLI ───────────────────────────────────────────────────────────────────────

def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Process raw sprite images into Phaser 3 spritesheets.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  python process_sprites.py              # process everything\n"
            "  python process_sprites.py --only pm    # only the PM sheet\n"
            "  python process_sprites.py --only writer\n"
            "  python process_sprites.py --only emotes\n"
        ),
    )
    parser.add_argument(
        "--only",
        metavar="ROLE",
        default=None,
        help=(
            "Process only the role whose output filename starts with ROLE "
            "(case-insensitive).  Use 'emotes' to process only the emote strip."
        ),
    )
    return parser


def _role_matches(out_name: str, only: str) -> bool:
    """Return True when *out_name* matches the --only filter."""
    return out_name.lower().startswith(only.lower())


# ── Entry point ───────────────────────────────────────────────────────────────

def main() -> int:
    parser = _build_arg_parser()
    args = parser.parse_args()
    only: str | None = args.only

    print("=== Sprite Post-Processor (rembg edition) ===\n")
    print(f"Source : {GENERATED}")
    print(f"Output : {OUTPUT}")
    if only:
        print(f"Filter : --only {only!r}")
    print()

    os.makedirs(OUTPUT, exist_ok=True)

    success = 0
    attempted = 0

    # ── Role sprites ──────────────────────────────────────────────────────────
    for src, out, count, top_only in ROLE_SPRITES:
        if only and not _role_matches(out, only):
            continue
        attempted += 1
        if process_role_sprite(src, out, count, top_only):
            success += 1
        print()

    # ── Emotes ────────────────────────────────────────────────────────────────
    emote_src, emote_out, emote_count = EMOTE_ENTRY
    if only is None or _role_matches(emote_out, only):
        attempted += 1
        if process_emotes(emote_src, emote_out, emote_count):
            success += 1
        print()

    # ── Summary ───────────────────────────────────────────────────────────────
    print(f"Done: {success}/{attempted} processed successfully")

    # List all generated sheets for a quick sanity check
    sheets = sorted(OUTPUT.glob("*_sheet.png"))
    if sheets:
        print("\n=== Output Files ===")
        for f in sheets:
            img = Image.open(f)
            print(f"  {f.name}: {img.size[0]}×{img.size[1]}")

    return 0 if success == attempted else 1


if __name__ == "__main__":
    sys.exit(main())
