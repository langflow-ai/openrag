"""Waves animation widget for command modals."""

import math
import random
from dataclasses import dataclass
from typing import List

from textual import events
from textual.reactive import reactive
from textual.widgets import Static


@dataclass
class Wavelet:
    x: float
    lane: int  # 0 or 1
    speed: float  # chars/frame
    phase: float  # for subtle vertical bob / color cycle
    hue: int  # index in palette


class Waves(Static):
    """Animated waves widget that displays moving wavelets around the border."""

    can_focus = False
    fps = 24
    paused = reactive(False)
    show_help = reactive(False)

    def on_mount(self):
        self.palette = ["#93c5fd", "#60a5fa", "#38bdf8", "#a78bfa", "#f472b6"]
        self.wavelets: List[Wavelet] = []
        # Start with a few wavelets
        for _ in range(3):
            self._add_wavelet()
        self.set_interval(1 / self.fps, self._tick)

    def _offset_for_lane(self, lane: int, width: int, height: int) -> int:
        max_offset = max(1, min(width, height) // 2 - 1)
        return min(1 + lane, max_offset)

    def _build_path(
        self, width: int, height: int, offset: int
    ) -> List[tuple[int, int]]:
        left = offset
        right = max(offset, width - offset - 1)
        top = offset
        bottom = max(offset, height - offset - 1)
        if right < left or bottom < top:
            return [(max(0, left), max(0, top))]

        path: List[tuple[int, int]] = []
        # Top edge
        for x in range(left, right + 1):
            path.append((x, top))
        # Right edge (excluding corners already added)
        for y in range(top + 1, bottom):
            path.append((right, y))
        # Bottom edge (if distinct from top)
        if bottom != top:
            for x in range(right, left - 1, -1):
                path.append((x, bottom))
        # Left edge (excluding corners)
        if right != left:
            for y in range(bottom - 1, top, -1):
                path.append((left, y))
        return path or [(left, top)]

    def _path_for_lane(
        self, width: int, height: int, lane: int
    ) -> List[tuple[int, int]]:
        offset = self._offset_for_lane(lane, width, height)
        path = self._build_path(width, height, offset)
        if not path and offset > 1:
            offset = 1
            path = self._build_path(width, height, offset)
        return path

    def _add_wavelet(self):
        w = max(10, self.size.width)
        self.wavelets.append(
            Wavelet(
                x=0,
                lane=random.choice([0, 1]),
                speed=0.25 + random.random() * 0.35,  # slow & smooth
                phase=random.random() * math.tau,
                hue=random.randrange(len(self.palette)),
            )
        )
        # Initialize position once we know the current perimeter
        h = max(6, self.size.height)
        path = self._path_for_lane(w, h, self.wavelets[-1].lane)
        if path:
            self.wavelets[-1].x = random.uniform(0, len(path))

    def set_throughput(self, bytes_per_sec: float):
        """Modulate wavelet speed based on download throughput."""
        boost = min(1.8, 1.0 + math.log10(bytes_per_sec + 1) / 6.0)
        for w in self.wavelets:
            w.speed = min(1.2, w.speed * 0.7 + (0.25 * boost))

    def _tick(self):
        if self.paused:
            self.refresh()
            return
        width = max(10, self.size.width)
        height = max(6, self.size.height)
        for w in self.wavelets:
            path = self._path_for_lane(width, height, w.lane)
            if not path:
                continue
            perimeter = len(path)
            if perimeter <= 0:
                continue
            w.x %= perimeter
            new_pos = w.x + w.speed
            wrapped = new_pos >= perimeter
            w.x = new_pos % perimeter
            if wrapped:
                # Tiny color/phase change on wrap
                w.hue = (w.hue + 1) % len(self.palette)
                w.phase = random.random() * math.tau
        self.refresh()

    def render(self) -> str:
        W = max(10, self.size.width)
        H = max(6, self.size.height)
        buf = [[" "] * W for _ in range(H)]

        # Draw wavelets moving around the border
        for wv in self.wavelets:
            path = self._path_for_lane(W, H, wv.lane)
            if not path:
                continue
            perimeter = len(path)
            if perimeter <= 0:
                continue
            idx = int(wv.x) % perimeter
            x, y = path[idx]
            if 0 <= x < W and 0 <= y < H:
                col = self.palette[wv.hue]
                buf[y][x] = f"[{col}]≈[/]"

        # No border - just wavelets on empty background

        return "\n".join("".join(r) for r in buf)
