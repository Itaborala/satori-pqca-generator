#!/usr/bin/env python
"""
Visualize a PQCA dataset (the JSON produced by generate-pqca-dataset.py).

Each frame is a flat list of 0/1 of length prod(system_size), in the same
C-order the tessellation uses, so it reshapes straight back to the lattice.
The view is chosen by the effective dimensionality:

    1D ([L] or [L, 1])  -> spacetime diagram PNG (time down, space across)
    2D ([R, C])         -> animated GIF, one grid per step
    3D ([X, Y, Z])      -> voxel GIF, the live cells per step

Usage:
    python visualize.py data-dante/ex0.json
    python visualize.py data-dante/ex0.json --out ex0.gif --fps 12
    python visualize.py data-dante/ex0.json --gif        # also animate a 1D run

Importable:
    from visualize import render
    render("data-dante/ex0.json")        # call at the end of collect, if you like
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import matplotlib
matplotlib.use("Agg")                       # headless: write files, don't open windows
import matplotlib.pyplot as plt
import matplotlib.animation as animation


def _load(dataset_path):
    data = json.loads(Path(dataset_path).read_text())
    size = list(data["metadata"]["system_size"])
    frames = [np.asarray(f, dtype=int).reshape(size) for f in data["frames"]]
    return data.get("name", Path(dataset_path).stem), size, frames


def _effective_dims(size):
    """Axes with extent > 1, so [L, 1] reads as 1D and [R, C] as 2D."""
    return [d for d in size if d > 1]


def render_spacetime(name, frames, out, cmap):
    """1D: stack frames into a (time x space) image."""
    spacetime = np.array([f.reshape(-1) for f in frames])      # (T, L)
    t, l = spacetime.shape
    fig, ax = plt.subplots(figsize=(max(4, l / 6), max(3, t / 6)))
    ax.imshow(spacetime, cmap=cmap, vmin=0, vmax=1,
              interpolation="nearest", aspect="auto")
    ax.set_xlabel("site")
    ax.set_ylabel("time step")
    ax.set_title(name)
    fig.tight_layout()
    fig.savefig(out, dpi=150)
    plt.close(fig)
    return out


def render_gif_2d(name, frames, out, fps, cmap):
    """2D: animate one grid per step."""
    fig, ax = plt.subplots()
    im = ax.imshow(frames[0], cmap=cmap, vmin=0, vmax=1, interpolation="nearest")
    ax.set_xticks([]); ax.set_yticks([])
    title = ax.set_title(f"{name}   t = 0")

    def update(t):
        im.set_data(frames[t])
        title.set_text(f"{name}   t = {t}")
        return [im, title]

    ani = animation.FuncAnimation(fig, update, frames=len(frames), blit=False)
    ani.save(out, writer=animation.PillowWriter(fps=fps))
    plt.close(fig)
    return out


def render_gif_3d(name, frames, out, fps):
    """3D: animate live voxels per step."""
    fig = plt.figure()
    ax = fig.add_subplot(projection="3d")
    nx, ny, nz = frames[0].shape

    def update(t):
        ax.clear()
        ax.voxels(frames[t].astype(bool), facecolors="tab:blue",
                  edgecolor="k", linewidth=0.2, alpha=0.85)
        ax.set_xlim(0, nx); ax.set_ylim(0, ny); ax.set_zlim(0, nz)
        ax.set_xticks([]); ax.set_yticks([]); ax.set_zticks([])
        ax.set_title(f"{name}   t = {t}")

    ani = animation.FuncAnimation(fig, update, frames=len(frames), blit=False)
    ani.save(out, writer=animation.PillowWriter(fps=fps))
    plt.close(fig)
    return out


def render(dataset_path, out=None, fps=10, cmap="gray", gif=False):
    """Render the dataset; returns the output path. Dimensionality is auto-detected."""
    name, size, frames = _load(dataset_path)
    dims = _effective_dims(size)
    stem = Path(dataset_path).with_suffix("")

    if len(dims) <= 1:
        flat = [f.reshape(-1) for f in frames]
        if gif:                              # optional 1D reveal animation
            out = out or f"{stem}.gif"
            grids = [np.array(flat[: i + 1]) for i in range(len(flat))]
            # pad each partial stack to full height so the frame size is stable
            full = np.zeros((len(flat), flat[0].size))
            fig, ax = plt.subplots()
            im = ax.imshow(full, cmap=cmap, vmin=0, vmax=1,
                           interpolation="nearest", aspect="auto")
            ax.set_xlabel("site"); ax.set_ylabel("time step"); ax.set_title(name)

            def update(t):
                buf = np.full_like(full, np.nan)
                buf[: t + 1] = np.array(flat[: t + 1])
                im.set_data(buf)
                return [im]

            animation.FuncAnimation(fig, update, frames=len(flat), blit=False) \
                     .save(out, writer=animation.PillowWriter(fps=fps))
            plt.close(fig)
            return out
        out = out or f"{stem}_spacetime.png"
        return render_spacetime(name, frames, out, cmap)

    if len(dims) == 2:
        squeezed = [f.reshape(dims) for f in frames]
        out = out or f"{stem}.gif"
        return render_gif_2d(name, squeezed, out, fps, cmap)

    if len(dims) == 3:
        out = out or f"{stem}_3d.gif"
        return render_gif_3d(name, frames, out, fps)

    raise ValueError(f"cannot visualize a {len(dims)}-D lattice: {size}")


def main():
    p = argparse.ArgumentParser(description="Visualize a PQCA dataset.")
    p.add_argument("dataset", help="path to a dataset JSON")
    p.add_argument("--out", default=None, help="output path (extension picks format)")
    p.add_argument("--fps", type=float, default=10, help="frames per second for GIFs (lower = slower; fractional ok, e.g. 0.5)")
    p.add_argument("--cmap", default="gray", help="matplotlib colormap (0=black, 1=white)")
    p.add_argument("--gif", action="store_true", help="for 1D, animate the reveal instead of a static PNG")
    args = p.parse_args()
    out = render(args.dataset, out=args.out, fps=args.fps, cmap=args.cmap, gif=args.gif)
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
