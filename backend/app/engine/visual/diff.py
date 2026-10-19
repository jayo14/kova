import io
from typing import Any
import numpy as np
from PIL import Image


def compute_pixel_diff(baseline_bytes: bytes, current_bytes: bytes) -> dict[str, Any]:
    """Compute pixel-level diff between two screenshots.

    Returns: {
        "diff_percentage": float,    # 0..100
        "diff_image_bytes": bytes,   # visual diff overlay PNG
        "regions": list[dict],       # bounding boxes of significant diffs
    }
    """
    baseline_img = Image.open(io.BytesIO(baseline_bytes)).convert("RGB")
    current_img = Image.open(io.BytesIO(current_bytes)).convert("RGB")

    baseline = np.array(baseline_img)
    current = np.array(current_img)

    if baseline.shape != current.shape:
        h, w = current.shape[:2]
        return {
            "diff_percentage": 100.0,
            "diff_image_bytes": current_bytes,
            "regions": [{"x": 0, "y": 0, "width": w, "height": h}],
        }

    # Per-channel diff
    diff = np.abs(baseline.astype(int) - current.astype(int))
    # Per-pixel diff sum > 30 (out of 765 total across 3 channels) is "significant"
    significant = diff.sum(axis=2) > 30
    total_pixels = significant.size
    sig_count = int(significant.sum())
    diff_percentage = float((sig_count / total_pixels) * 100.0) if total_pixels > 0 else 0.0

    # Cluster significant regions into bounding boxes
    regions = _cluster_regions(significant)

    # Generate diff overlay (highlight differing pixels in vivid red)
    diff_overlay = current.copy()
    diff_overlay[significant] = [255, 0, 0]
    diff_image = Image.fromarray(diff_overlay)
    buf = io.BytesIO()
    diff_image.save(buf, format="PNG")

    return {
        "diff_percentage": round(diff_percentage, 2),
        "diff_image_bytes": buf.getvalue(),
        "regions": regions,
    }


def _cluster_regions(significant: np.ndarray, block_size: int = 32) -> list[dict[str, int]]:
    """Cluster adjacent significant pixels into bounding boxes using a block grid."""
    h, w = significant.shape
    if h == 0 or w == 0 or not significant.any():
        return []

    # Downsample by checking each block_size x block_size grid cell
    grid_h = (h + block_size - 1) // block_size
    grid_w = (w + block_size - 1) // block_size
    grid = np.zeros((grid_h, grid_w), dtype=bool)

    for gy in range(grid_h):
        y0 = gy * block_size
        y1 = min(y0 + block_size, h)
        for gx in range(grid_w):
            x0 = gx * block_size
            x1 = min(x0 + block_size, w)
            block = significant[y0:y1, x0:x1]
            # If at least 3 pixels in block differ, mark block as active
            if block.sum() >= 3:
                grid[gy, gx] = True

    visited = np.zeros_like(grid, dtype=bool)
    regions: list[dict[str, int]] = []

    # Flood fill / connected components on the block grid
    for gy in range(grid_h):
        for gx in range(grid_w):
            if grid[gy, gx] and not visited[gy, gx]:
                # BFS to find connected component of blocks
                queue = [(gy, gx)]
                visited[gy, gx] = True
                min_gy, max_gy = gy, gy
                min_gx, max_gx = gx, gx

                while queue:
                    curr_y, curr_x = queue.pop(0)
                    min_gy = min(min_gy, curr_y)
                    max_gy = max(max_gy, curr_y)
                    min_gx = min(min_gx, curr_x)
                    max_gx = max(max_gx, curr_x)

                    for dy, dx in [(-1, 0), (1, 0), (0, -1), (0, 1)]:
                        ny, nx = curr_y + dy, curr_x + dx
                        if 0 <= ny < grid_h and 0 <= nx < grid_w:
                            if grid[ny, nx] and not visited[ny, nx]:
                                visited[ny, nx] = True
                                queue.append((ny, nx))

                bx = min_gx * block_size
                by = min_gy * block_size
                bw = min((max_gx - min_gx + 1) * block_size, w - bx)
                bh = min((max_gy - min_gy + 1) * block_size, h - by)

                regions.append({"x": int(bx), "y": int(by), "width": int(bw), "height": int(bh)})

    return regions
