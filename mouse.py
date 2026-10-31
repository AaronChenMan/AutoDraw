"""Mouse/keyboard control for Roblox on macOS via Quartz CGEvents posted at the HID tap.
Roblox ignores bare cursor warps while a button is held, so drags send
kCGEventLeftMouseDragged in small steps with short sleeps between them.
Failsafe: if the real cursor drifts from where we last put it, the user grabbed
the mouse -> raise Abort."""
import subprocess
import sys
import time

import Quartz as Q

STEP_PX = 4         # max pixels per drag event; raise for speed, lower if Roblox skips
STEP_DELAY = 0.004  # seconds between events; Roblox drops events if too fast
PRESS_DELAY = 0.05  # hold after down/before up so Roblox registers the click
FAILSAFE_PX = 25    # cursor this far from expected = user took over
FAILSAFE_STRIKES = 3  # consecutive deviations required before aborting (debounces jitter)


class Abort(Exception):
    pass


_last = None
_strikes = 0

# Keyboard emergency stop: any keypress aborts immediately. Uses the same HID
# tap Quartz already uses for mouse posting, so no new dependency/permission.
_key_pressed = False
_key_tap = None


def _on_key(proxy, event_type, event, refcon):
    global _key_pressed
    if event_type == Q.kCGEventKeyDown:
        _key_pressed = True
    return event


def start_key_listener():
    """Call once before a drawing run. Any keypress will make _check() abort."""
    global _key_tap, _key_pressed
    _key_pressed = False
    if _key_tap is not None:
        return
    _key_tap = Q.CGEventTapCreate(
        Q.kCGHIDEventTap, Q.kCGHeadInsertEventTap, Q.kCGEventTapOptionListenOnly,
        Q.CGEventMaskBit(Q.kCGEventKeyDown), _on_key, None)
    if _key_tap is None:
        print("warning: could not create key-listener tap (grant Input Monitoring) "
              "-- keyboard emergency stop disabled", file=sys.stderr)
        return
    source = Q.CFMachPortCreateRunLoopSource(None, _key_tap, 0)
    Q.CFRunLoopAddSource(Q.CFRunLoopGetMain(), source, Q.kCFRunLoopCommonModes)
    Q.CGEventTapEnable(_key_tap, True)


def focus_roblox():
    subprocess.run(["osascript", "-e", 'tell application "Roblox" to activate'], check=False)
    time.sleep(0.5)


_roblox_pid = None


def roblox_pid():
    """Cached: fetched once, since it doesn't change while Roblox stays open."""
    global _roblox_pid
    if _roblox_pid is None:
        out = subprocess.run(
            ["osascript", "-e", 'tell application "System Events" to get unix id of first process whose name is "RobloxPlayer"'],
            capture_output=True, text=True, check=True)
        _roblox_pid = int(out.stdout.strip())
    return _roblox_pid


def position():
    return Q.CGEventGetLocation(Q.CGEventCreate(None))


def _check():
    global _strikes
    # Pump the run loop briefly so the key tap's callback actually fires
    # (autodraw's drawing loop never otherwise runs a CFRunLoop).
    if _key_tap is not None:
        Q.CFRunLoopRunInMode(Q.kCFRunLoopDefaultMode, 0, False)
    if _key_pressed:
        raise Abort("key pressed by user")

    if _last is None:
        return
    x, y = position()
    if abs(x - _last[0]) > FAILSAFE_PX or abs(y - _last[1]) > FAILSAFE_PX:
        _strikes += 1
        if _strikes >= FAILSAFE_STRIKES:
            raise Abort("mouse moved by user")
    else:
        _strikes = 0


def _post(kind, x, y):
    global _last
    Q.CGEventPost(Q.kCGHIDEventTap, Q.CGEventCreateMouseEvent(None, kind, (x, y), Q.kCGMouseButtonLeft))
    _last = (x, y)


def reset_failsafe():
    global _last, _strikes
    _last = None
    _strikes = 0


def _path(x, y, kind):
    _check()
    sx, sy = position()
    n = max(1, int(max(abs(x - sx), abs(y - sy)) / STEP_PX))
    for i in range(1, n + 1):
        _post(kind, sx + (x - sx) * i / n, sy + (y - sy) * i / n)
        time.sleep(STEP_DELAY)


def move(x, y):
    _path(x, y, Q.kCGEventMouseMoved)


def down():
    _check()
    _post(Q.kCGEventLeftMouseDown, *position())
    time.sleep(PRESS_DELAY)


def up():
    time.sleep(PRESS_DELAY)
    _post(Q.kCGEventLeftMouseUp, *position())


def drag_to(x, y):
    _path(x, y, Q.kCGEventLeftMouseDragged)


def click(x, y):
    move(x, y)
    down()
    up()


# Roblox's UI is custom-rendered (no real AXUIElements), and it only updates
# which widget is "hovered" from an actual mouseMoved stream — a teleport
# straight to a target and click can land before that hover state updates,
# so a plain click never focuses the hex box. Confirmed via test_hover_click.py:
# nudge away, walk back in small steps, dwell briefly, then click.
FOCUS_DWELL = 0.12


def click_focus(x, y):
    """Click meant to grab keyboard focus on a UI element (e.g. Roblox's hex
    box), not just to press a spot on the canvas — use click() for that."""
    ox, oy = x - 40, y - 40
    _post(Q.kCGEventMouseMoved, ox, oy)  # teleport near the box, skip animating the long approach
    _path(x, y, Q.kCGEventMouseMoved)    # then walk the short final stretch so hover state updates
    time.sleep(FOCUS_DWELL)
    down()
    up()


# Real per-character virtual keycodes (US ANSI layout). Roblox reads raw
# keycodes (HID/SDL-style), not the "fake keycode + unicode string override"
# trick — confirmed by test_typing.py. Plain keycode events (method B) only
# landed ~10% of the time; attaching an explicit HID event source (method C)
# was reliable, so events are built from a shared source below.
HEX_KEYCODE = {
    "0": 29, "1": 18, "2": 19, "3": 20, "4": 21, "5": 23, "6": 22, "7": 26, "8": 28, "9": 25,
    "a": 0, "b": 11, "c": 8, "d": 2, "e": 14, "f": 3,
}

# Posting keys via the HID tap only reached Roblox unreliably. Posting
# directly to Roblox's process (CGEventPostToPid) is the one method that
# worked end-to-end in testing, so keyboard events go straight there.
def _key(code, flags=0):
    for is_down in (True, False):
        e = Q.CGEventCreateKeyboardEvent(None, code, is_down)
        if flags:
            Q.CGEventSetFlags(e, flags)
        Q.CGEventPostToPid(roblox_pid(), e)
        time.sleep(0.15)  # slow: Roblox seems to miss keys sent back-to-back


def select_all():
    _key(0, Q.kCGEventFlagMaskCommand)  # cmd+A


def backspace():
    _key(51)


def type_text(s):
    for ch in s.lower():
        _key(HEX_KEYCODE[ch])
        time.sleep(0.15)


def enter():
    _key(36)


if __name__ == "__main__":
    focus_roblox()
    w, h = Q.CGDisplayPixelsWide(Q.CGMainDisplayID()), Q.CGDisplayPixelsHigh(Q.CGMainDisplayID())
    cx, cy = w / 2, h / 2
    print("move test: square around screen center")
    for px, py in [(cx - 100, cy - 100), (cx + 100, cy - 100), (cx + 100, cy + 100), (cx - 100, cy + 100)]:
        move(px, py)
    time.sleep(0.5)
    if "--drag" in sys.argv:
        print("drag test: held stroke, square + diagonal")
        move(cx - 100, cy - 100)
        down()
        for px, py in [(cx + 100, cy - 100), (cx + 100, cy + 100), (cx - 100, cy + 100), (cx - 100, cy - 100), (cx + 100, cy + 100)]:
            drag_to(px, py)
        up()
    print("done")
