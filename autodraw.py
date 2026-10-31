"""AutoDraw: local web UI + drawing engine. Run: .venv/bin/python autodraw.py"""
import base64
import io
import json
import os
import subprocess
import threading
import time
import urllib.request
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from PIL import Image

import mouse
import overlay
import picker

PORT = 8765
ROOT = Path(__file__).parent
PREVIEW_MAX_SIDE = 280  # default overlay size (px) for the longer image edge while picking

# ponytail: single global session, it's a one-user local tool
S = {"img": None, "quant": None, "layers": [], "state": "idle", "msg": "", "done": 0, "total": 0, "layer": "",
     "region": None, "hex_pos": None, "picking": False}  # region: {cx, cy, w, h}
STOP = threading.Event()


def load_image(src):
    if src.startswith("data:"):
        data = base64.b64decode(src.split(",", 1)[1])
    else:
        req = urllib.request.Request(src, headers={"User-Agent": "Mozilla/5.0"})
        data = urllib.request.urlopen(req, timeout=15).read()
    return Image.open(io.BytesIO(data)).convert("RGBA")


def quantize(img, colors, grid_w, grid_h):
    """Fit img into grid, reduce colors. Returns (preview RGBA, {hex: [(row, x0, x1)]}) ordered by pixel count desc."""
    # quantize before the final shrink so edge blending can't invent fringe colors
    ratio = min(grid_w / img.width, grid_h / img.height)
    w, h = max(1, round(img.width * ratio)), max(1, round(img.height * ratio))
    mid = img.resize((min(img.width, w * 4), min(img.height, h * 4)), Image.BOX)
    q = mid.convert("RGB").quantize(colors, method=Image.Quantize.MEDIANCUT, kmeans=3, dither=Image.Dither.NONE)
    q = q.resize((w, h), Image.NEAREST)
    alpha = mid.getchannel("A").resize((w, h), Image.NEAREST)
    pal = q.getpalette()
    px, a = q.load(), alpha.load()
    w, h = q.size
    layers = {}
    for y in range(h):
        x = 0
        while x < w:
            if a[x, y] < 128:
                x += 1
                continue
            c = px[x, y]
            x0 = x
            while x + 1 < w and px[x + 1, y] == c and a[x + 1, y] >= 128:
                x += 1
            hx = "%02x%02x%02x" % tuple(pal[c * 3:c * 3 + 3])
            layers.setdefault(hx, []).append((y, x0, x))
            x += 1
    preview = q.convert("RGBA")
    preview.putalpha(alpha.point(lambda v: 255 if v >= 128 else 0))
    order = sorted(layers.items(), key=lambda kv: -sum(r[2] - r[1] + 1 for r in kv[1]))
    return preview, order


def to_data_url(im, scale):
    im = im.resize((im.width * scale, im.height * scale), Image.NEAREST)
    buf = io.BytesIO()
    im.save(buf, "PNG")
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()


def _preview_png(img):
    """Downscaled copy of the loaded image, used as the overlay while picking
    the region — a rough visual guide, not the final quantized output."""
    im = img.copy()
    im.thumbnail((PREVIEW_MAX_SIDE, PREVIEW_MAX_SIDE), Image.LANCZOS)
    buf = io.BytesIO()
    im.save(buf, "PNG")
    return buf.getvalue(), im.width, im.height


def _run_pick(kind):
    try:
        if kind == "region":
            png, w0, h0 = _preview_png(S["img"])
            S["region"] = picker.pick_region(png, w0, h0) or S["region"]
        else:
            S["hex_pos"] = picker.pick_point() or S["hex_pos"]
    finally:
        S["picking"] = False


def set_color(hex_pos, hx):
    mouse.click_focus(*hex_pos)
    time.sleep(0.3)
    mouse.select_all()
    time.sleep(0.2)
    mouse.backspace()
    time.sleep(0.2)
    mouse.type_text(hx)
    time.sleep(0.2)
    mouse.enter()
    time.sleep(0.3)
    mouse.reset_failsafe()  # the game may nudge the cursor while the picker updates


def draw(cfg):
    r, hex_pos, cell = cfg["region"], cfg["hex"], cfg["spacing"]
    skip = set(cfg.get("skip", []))
    layers = [(hx, runs) for hx, runs in S["layers"] if hx not in skip]
    S.update(state="drawing", done=0, total=sum(len(r) for _, r in layers), msg="Focusing Roblox…")
    ox, oy = r["cx"] - r["w"] / 2, r["cy"] - r["h"] / 2
    mouse.STEP_PX = 1 + int(cfg.get("speed", 4))  # speed slider 1-10 -> 2-11 px per drag event
    try:
        mouse.focus_roblox()
        mouse.reset_failsafe()
        mouse.start_key_listener()
        for hx, runs in layers:
            S.update(layer=hx, msg=f"Setting color #{hx}")
            set_color(hex_pos, hx)
            S["msg"] = f"Drawing #{hx}"
            flip = False
            last_row = None
            for row, x0, x1 in runs:  # serpentine per row to cut travel
                if STOP.is_set():
                    raise mouse.Abort("stopped")
                if row != last_row:
                    flip, last_row = not flip, row
                a, b = (x1, x0) if flip else (x0, x1)
                y = oy + (row + 0.5) * cell
                mouse.move(ox + (a + 0.5) * cell, y)
                mouse.down()
                mouse.drag_to(ox + (b + 0.5) * cell + (0 if a != b else 1), y)
                mouse.up()
                S["done"] += 1
        S.update(state="idle", msg="Finished ✓", layer="")
    except mouse.Abort as e:
        S.update(state="idle", msg=f"Stopped: {e}", layer="")
    except Exception as e:
        S.update(state="idle", msg=f"Error: {e}", layer="")
    finally:
        mouse.reset_failsafe()


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, code, body, ctype="application/json"):
        data = body if isinstance(body, bytes) else json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if self.path == "/":
            return self._send(200, (ROOT / "index.html").read_bytes(), "text/html; charset=utf-8")
        if self.path == "/api/status":
            return self._send(200, {k: S[k] for k in ("state", "msg", "done", "total", "layer")})
        if self.path == "/api/pick_status":
            return self._send(200, {"picking": S["picking"], "region": S["region"], "hex": S["hex_pos"]})
        self._send(404, {"error": "not found"})

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
        try:
            if self.path == "/api/load":
                S["img"] = load_image(body["src"])
                return self._send(200, {"w": S["img"].width, "h": S["img"].height})
            if self.path == "/api/process":
                if S["img"] is None:
                    return self._send(400, {"error": "Load an image first"})
                gw, gh = max(1, int(body["gw"])), max(1, int(body["gh"]))
                preview, S["layers"] = quantize(S["img"], int(body["colors"]), gw, gh)
                scale = max(1, min(8, 480 // max(preview.size)))
                return self._send(200, {
                    "preview": to_data_url(preview, scale),
                    "size": preview.size,
                    "layers": [{"hex": hx, "strokes": len(r), "pixels": sum(b - a + 1 for _, a, b in r)} for hx, r in S["layers"]],
                })
            if self.path == "/api/start_pick":
                if S["picking"]:
                    return self._send(409, {"error": "Already picking"})
                kind = body.get("kind")
                if kind == "region" and S["img"] is None:
                    return self._send(400, {"error": "Load an image first"})
                S["picking"] = True
                threading.Thread(target=_run_pick, args=(kind,), daemon=True).start()
                return self._send(200, {"ok": True})
            if self.path == "/api/cancel_pick":
                # best-effort: the picker only reacts to Esc/Enter, so this just
                # reports whatever is going on; used if the browser tab closes mid-pick
                return self._send(200, {"picking": S["picking"]})
            if self.path == "/api/draw":
                if S["state"] == "drawing":
                    return self._send(409, {"error": "Already drawing"})
                if not S["layers"]:
                    return self._send(400, {"error": "Process an image first"})
                STOP.clear()
                threading.Thread(target=draw, args=(body,), daemon=True).start()
                return self._send(200, {"ok": True})
            if self.path == "/api/stop":
                STOP.set()
                return self._send(200, {"ok": True})
            self._send(404, {"error": "not found"})
        except Exception as e:
            self._send(400, {"error": str(e)})


def _selfcheck():
    im = Image.new("RGBA", (4, 2), (255, 0, 0, 255))
    im.putpixel((2, 0), (0, 0, 255, 255))
    im.putpixel((3, 1), (0, 0, 0, 0))
    _, layers = quantize(im, 2, 4, 2)
    runs = [r for _, r in layers]  # hex values vary with median cut, runs must not
    assert runs == [[(0, 0, 1), (0, 3, 3), (1, 0, 2)], [(0, 2, 2)]], layers


def _kill_stale_server():
    """A previous run of this script may still be holding the port; free it
    rather than making the user hunt it down every restart."""
    pids = subprocess.run(["lsof", "-ti", f"tcp:{PORT}"], capture_output=True, text=True).stdout.split()
    for pid in pids:
        if int(pid) != os.getpid():
            subprocess.run(["kill", "-9", pid])
    if pids:
        time.sleep(0.3)


if __name__ == "__main__":
    _selfcheck()
    _kill_stale_server()
    srv = ThreadingHTTPServer(("127.0.0.1", PORT), H)
    url = f"http://127.0.0.1:{PORT}"
    print(f"AutoDraw running at {url}  (Ctrl+C to quit)")
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    webbrowser.open(url)
    overlay.init()
    overlay.run()  # blocks on the main thread; AppKit requires this
