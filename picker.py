"""Live, no-countdown calibration picker. Focuses Roblox, tracks the real
cursor with an overlay, and listens for +/-/Enter/Esc/click as GLOBAL input
events (a Quartz event tap) because Roblox, not this script, has keyboard
focus while the user is positioning things.

Needs Accessibility + Input Monitoring permission for the terminal/python
process (same permission class as mouse.py's mouse control)."""
import threading
import time

import Quartz as Q

import mouse
import overlay

TRACK_HZ = 30
RESIZE_STEP = 1.06  # multiplicative per keypress, feels smooth without being twitchy
PLUS_CODES = {24, 69}   # '=' (plus w/o shift) and numpad plus
MINUS_CODES = {27, 78}  # '-' and numpad minus
RETURN_CODE = 36
ESCAPE_CODE = 53


def pick_point():
    """Follow the cursor with a crosshair; Enter confirms, Esc cancels.
    Returns {x, y} or None."""
    return _pick(mode="point")


def pick_region(png_bytes, w0, h0):
    """Follow the cursor with the image, resizable via +/-; Enter confirms,
    Esc cancels. Returns {cx, cy, w, h} or None."""
    return _pick(mode="image", png_bytes=png_bytes, w0=w0, h0=h0)


def _pick(mode, png_bytes=None, w0=100, h0=100):
    mouse.focus_roblox()
    state = {"w": w0, "h": h0, "confirmed": False}
    if mode == "image":
        overlay.set_image(png_bytes)
    else:
        overlay.set_point()

    stop = threading.Event()

    def track():
        while not stop.is_set():
            x, y = mouse.position()
            overlay.show(x - state["w"] / 2, y - state["h"] / 2, state["w"], state["h"])
            time.sleep(1 / TRACK_HZ)

    threading.Thread(target=track, daemon=True).start()

    loop = Q.CFRunLoopGetCurrent()
    tap_box = {}

    def on_key(proxy, etype, event, refcon):
        if etype in (Q.kCGEventTapDisabledByTimeout, Q.kCGEventTapDisabledByUserInput):
            Q.CGEventTapEnable(tap_box["tap"], True)  # macOS pauses slow/idle taps; keep it alive
            return event
        if etype == Q.kCGEventLeftMouseDown:
            state["confirmed"] = True
            Q.CFRunLoopStop(loop)
            return None  # swallow so the click doesn't also paint in Roblox
        if etype != Q.kCGEventKeyDown:
            return event
        code = Q.CGEventGetIntegerValueField(event, Q.kCGKeyboardEventKeycode)
        if mode == "image" and code in PLUS_CODES:
            state["w"] *= RESIZE_STEP
            state["h"] *= RESIZE_STEP
            return None
        if mode == "image" and code in MINUS_CODES:
            state["w"] = max(20, state["w"] / RESIZE_STEP)
            state["h"] = max(20, state["h"] / RESIZE_STEP)
            return None
        if code == RETURN_CODE:
            state["confirmed"] = True
            Q.CFRunLoopStop(loop)
            return None
        if code == ESCAPE_CODE:
            state["confirmed"] = False
            Q.CFRunLoopStop(loop)
            return None
        return event  # not ours: let it through so normal typing still works

    mask = Q.CGEventMaskBit(Q.kCGEventKeyDown) | Q.CGEventMaskBit(Q.kCGEventLeftMouseDown)
    tap = Q.CGEventTapCreate(
        Q.kCGSessionEventTap, Q.kCGHeadInsertEventTap, Q.kCGEventTapOptionDefault, mask, on_key, None)
    if not tap:
        stop.set()
        overlay.hide()
        raise RuntimeError("Could not listen for keys/clicks — grant Input Monitoring/Accessibility to this terminal")
    tap_box["tap"] = tap
    src = Q.CFMachPortCreateRunLoopSource(None, tap, 0)
    Q.CFRunLoopAddSource(loop, src, Q.kCFRunLoopCommonModes)
    Q.CGEventTapEnable(tap, True)

    Q.CFRunLoopRun()  # blocks until Enter/Esc calls CFRunLoopStop

    stop.set()
    overlay.hide()
    if not state["confirmed"]:
        return None
    x, y = mouse.position()
    if mode == "point":
        return {"x": round(x), "y": round(y)}
    return {"cx": round(x), "cy": round(y), "w": round(state["w"]), "h": round(state["h"])}
