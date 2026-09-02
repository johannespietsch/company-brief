#!/usr/bin/env python3
"""Re-measure the renderer's page-estimate constants against headless Chrome.

Run this after changing render.CSS; it prints measured box heights in mm for a
set of probe documents, and checks estimate_pages against real printed page
counts. The constants in render.py were read off this output.

    python3 tools/measure.py path/to/brief.json [more.json ...]
"""

from __future__ import annotations

import json
import math
import re
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import render  # noqa: E402

CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
PROBE_CSS = ("\nbody{background:#fff}\n.sheet{max-width:none;margin:0;padding:0;"
             "box-shadow:none;width:178mm}\n")


def _chrome(*args: str) -> str:
    return subprocess.run([CHROME, "--headless", "--disable-gpu", *args],
                          capture_output=True, text=True).stdout


def flow_mm(data: dict, tmp: Path) -> float:
    """Total flow height in mm, ignoring pagination."""
    html = render.render(data).replace("</style>", PROBE_CSS + "</style>")
    html = html.replace(
        "<article",
        '<div id="mmp" style="height:100mm;position:absolute;visibility:hidden"></div><article',
    ).replace(
        "</body>",
        "<script>document.title='MM='+(document.querySelector('.sheet')"
        ".getBoundingClientRect().height/(document.getElementById('mmp')"
        ".getBoundingClientRect().height/100)).toFixed(1);</script></body>",
    )
    probe = tmp / "probe.html"
    probe.write_text(html, encoding="utf-8")
    out = _chrome("--virtual-time-budget=1500", "--dump-dom", probe.as_uri())
    m = re.search(r"MM=([0-9.]+)", out)
    return float(m.group(1)) if m else float("nan")


def printed_pages(data: dict, tmp: Path) -> int:
    html = tmp / "print.html"
    pdf = tmp / "print.pdf"
    html.write_text(render.render(data), encoding="utf-8")
    _chrome("--no-pdf-header-footer", f"--print-to-pdf={pdf}", html.as_uri())
    return len(re.findall(rb"/Type\s*/Page[^s]", pdf.read_bytes()))


def main(paths: list[str]) -> int:
    if not Path(CHROME).exists():
        print(f"Chrome not found at {CHROME}", file=sys.stderr)
        return 1
    hdr = f"{'FILE':22} {'EST_MM':>8} {'FLOW_MM':>8} {'RATIO':>6} {'PRED':>5} {'REAL':>5}"
    print(hdr)
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        for path in paths:
            data = json.loads(Path(path).read_text(encoding="utf-8"))
            est = render.estimate_mm(data)
            flow = flow_mm(data, tmp)
            pred = math.ceil(render.estimate_pages(data))
            real = printed_pages(data, tmp)
            flag = "" if pred == real else "  <-- off"
            print(f"{Path(path).name:22} {est:8.1f} {flow:8.1f} {flow / est:6.3f} "
                  f"{pred:5d} {real:5d}{flag}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:] or []))
