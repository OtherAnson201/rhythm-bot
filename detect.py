import capture
from config import HUES, strip_height_for

# one lanes scan result: the runs and bar info
class LaneProfile:
    __slots__ = ("hit", "runs", "bar_px", "fills", "heads")

    # empty profile
    def __init__(self):
        self.hit = 0.0
        self.runs = []
        self.bar_px = 0
        self.fills = None
        self.heads = []

# scans the captured strip into per-lane note runs
class Scanner:

    # set up scan geometry and color tables from config
    def __init__(self, cfg, hwnd=None):
        self.cfg = cfg
        lanes = cfg["lanes"]
        hw = cfg["lane_half_width"]
        xs = [l["x"] for l in lanes]

        self.x0 = max(0, min(xs) - hw)
        self.width = (max(xs) + hw) - self.x0

        self.hit_h = max(2, cfg["hit_above"] + cfg["hit_below"])
        bottom = cfg["receptor_y"] + cfg["hit_below"]
        self.y0 = max(0, bottom - strip_height_for(cfg))
        self.height = bottom - self.y0

        self._hit_r0 = self.height - self.hit_h

        # no window means tests feeding frames straight to profile()
        if hwnd is not None:
            self.dx, self.dy = capture.client_offset(hwnd)
            self.cap = capture.WindowCapture(hwnd, self.width, self.height)
        stride = self.width * 4

        self.step = 2
        self.lanes = []
        for l in lanes:
            a = max(0, l["x"] - hw - self.x0)
            b = min(self.width, l["x"] + hw - self.x0)
            b0, b1 = a * 4, b * 4
            rows = [(r * stride + b0, r * stride + b1)
                    for r in range(0, self.height, self.step)]
            self.lanes.append({
                "name": l["name"], "key": l["key"],
                "b0": b0, "b1": b1, "rows": rows,
                "npx": max(1, (b - a) // self.step),
                "lut": self._colour_lut(l.get("hue")),
            })

        self.row_fill = cfg.get("row_fill", 0.22)
        self.gap_tol = max(1, cfg.get("bar_gap_tol", 6) // self.step)
        self.seam_drop = cfg.get("seam_drop", 0.55)
        self.min_note_px = cfg.get("min_note_px", 14)
        self.seam_abs_floor = cfg.get("seam_abs_floor", 0.12)
        self.head_peak = cfg.get("head_peak", 0.85)

    # lookup table matching a lanes arrow hue
    def _colour_lut(self, hue):
        ref = HUES.get(hue)
        tol = self.cfg.get("hue_tol_by_lane", {}).get(
            hue, self.cfg.get("hue_tol", 78))
        bmin = self.cfg.get("brightness_min", 110)
        if ref is None:
            lut = bytes(1 if v >= bmin else 0 for v in range(256))
            return lut, lut, lut, False
        r, g, b = ref
        return (bytes(1 if abs(v - b) <= tol else 0 for v in range(256)),
                bytes(1 if abs(v - g) <= tol else 0 for v in range(256)),
                bytes(1 if abs(v - r) <= tol else 0 for v in range(256)),
                True)

    # grab the raw strip pixels
    def grab(self):
        return self.cap.grab(self.x0 + self.dx, self.y0 + self.dy)

    # scan one frame into a profile per lane
    def profile(self, raw):
        step = self.step
        height = self.height
        hit_r0 = self._hit_r0
        row_fill = self.row_fill
        out = []

        for lane in self.lanes:
            lb, lg, lr, colour = lane["lut"]
            npx = float(lane["npx"])
            rows = lane["rows"]
            covered = []
            fills = []
            append_fill = fills.append
            append_cov = covered.append

            for i, (a, b) in enumerate(rows):
                seg = raw[a:b]
                cg = seg[1::8].translate(lg).count(1)
                if not cg and colour:
                    append_fill(0.0)
                    continue
                cb = seg[0::8].translate(lb).count(1)
                cr = seg[2::8].translate(lr).count(1)

                lit = (cg if colour else max(cg, cb, cr))
                if colour:
                    lit = cb if cb < lit else lit
                    lit = cr if cr < lit else lit
                lit /= npx
                append_fill(lit)

                if lit >= row_fill:
                    append_cov(i * step)

            prof = self._runs_to_profile(covered, hit_r0, height, fills)
            prof.fills = fills
            out.append(prof)
        return out

    # turn covered-row spans into a lane profile
    def _runs_to_profile(self, covered, hit_r0, height, fills):
        p = LaneProfile()
        if not covered:
            return p

        hit_rows = sum(1 for r in covered if r >= hit_r0)
        p.hit = hit_rows / max(1.0, (height - hit_r0) / self.step)

        runs = []
        start = prev = covered[0]
        for r in covered[1:]:
            if r - prev <= self.gap_tol * self.step:
                prev = r
                continue
            runs.append((start, prev))
            start = prev = r
        runs.append((start, prev))

        runs = [s for run in runs for s in self._split_on_seams(run, fills)]

        for a, b in runs:
            a = self._refine_edge(a, fills, -1)
            b = self._refine_edge(b, fills, 1)
            p.runs.append((height - b, height - a))
        p.runs.sort()
        p.heads = [self._count_heads(n, f, fills) for n, f in p.runs]

        for (near, far), heads in zip(p.runs, p.heads):
            if near > self.hit_h + self.gap_tol * self.step:
                break
            p.bar_px = 0 if heads > 1 else far - near
        return p

    # count how many note heads are in a run
    def _count_heads(self, near, far, fills):
        step = self.step
        height = len(fills) * step
        lo = max(0, int((height - far) // step))
        hi = min(len(fills) - 1, int((height - near) // step))
        if hi <= lo:
            return 0
        seg = fills[lo:hi + 1]
        peak = max(seg) if seg else 0.0
        if peak <= 0.0:
            return 0
        head_at = peak * self.head_peak
        n, inside = 0, False
        for x in seg:
            if x >= head_at:
                if not inside:
                    n += 1
                    inside = True
            else:
                inside = False
        return n

    # sharpen a runs edge using fills, side -1 for the low edge, 1 for the high
    def _refine_edge(self, row, fills, side):
        i = row // self.step
        if not 0 <= i + side < len(fills):
            return float(row)
        f_out = fills[i + side]
        spread = fills[i] - f_out
        if spread <= 1e-6:
            return float(row)
        frac = max(0.0, min(1.0, (self.row_fill - f_out) / spread))
        return row + side * self.step * (1.0 - frac)

    # split a run where a dark seam separates two notes
    def _split_on_seams(self, run, fills):
        a, b = run
        i0, i1 = a // self.step, b // self.step
        if i1 - i0 < 4:
            return [run]

        seg = fills[i0:i1 + 1]
        peak = max(seg)
        floor = min(peak * self.seam_drop, self.seam_abs_floor)
        recover_to = peak * (1.0 + self.seam_drop) / 2.0

        seams = []
        j = 1
        while j < len(seg) - 1:
            if seg[j] < floor and seg[j] <= seg[j - 1] and seg[j] <= seg[j + 1]:
                k = j
                while k < len(seg) - 1 and seg[k + 1] < floor:
                    k += 1
                before = max(seg[:j])
                after = max(seg[k + 1:]) if k + 1 < len(seg) else 0.0
                if before >= recover_to and after >= recover_to:
                    mid = (j + k) // 2
                    if (not seams
                            or (mid - seams[-1]) * self.step >= self.min_note_px):
                        seams.append(mid)
                j = k + 1
            else:
                j += 1

        if not seams:
            return [run]

        out, start = [], i0
        for s in seams:
            cut = i0 + s
            if (cut - start) * self.step >= self.min_note_px:
                out.append((start * self.step, cut * self.step))
                start = cut
        if (i1 - start) * self.step >= self.min_note_px:
            out.append((start * self.step, b))
        elif out:
            out[-1] = (out[-1][0], b)
        return out or [run]

    # readable description of the scan region
    @property
    def region_desc(self):
        return (f"client x{self.x0}..{self.x0 + self.width} "
                f"y{self.y0}..{self.y0 + self.height} "
                f"(strip {self.height}px, hit zone {self.hit_h}px)")
