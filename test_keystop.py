"""Standalone test: detect a keypress (any key) while 'automation' runs, via a
Quartz CGEventTap listening at the HID tap — same layer mouse.py already uses,
so no new dependency (pynput needs its own accessibility permission prompt;
this reuses the Input Monitoring grant Quartz mouse posting already needs).

Run: .venv/bin/python test_keystop.py
Then tap any key on the keyboard within 15s.
"""
import time

import Quartz as Q

_keydown_count = 0


def _tap_callback(proxy, event_type, event, refcon):
    global _keydown_count
    if event_type == Q.kCGEventKeyDown:
        _keydown_count += 1
        keycode = Q.CGEventGetIntegerValueField(event, Q.kCGKeyboardEventKeycode)
        print(f"keydown #{_keydown_count} keycode={keycode}")
    return event


def main():
    tap = Q.CGEventTapCreate(
        Q.kCGHIDEventTap,
        Q.kCGHeadInsertEventTap,
        Q.kCGEventTapOptionListenOnly,
        Q.CGEventMaskBit(Q.kCGEventKeyDown),
        _tap_callback,
        None,
    )
    if tap is None:
        print("Failed to create event tap — grant Input Monitoring to this terminal/python "
              "in System Settings > Privacy & Security > Input Monitoring.")
        return

    run_loop_source = Q.CFMachPortCreateRunLoopSource(None, tap, 0)
    Q.CFRunLoopAddSource(Q.CFRunLoopGetCurrent(), run_loop_source, Q.kCFRunLoopCommonModes)
    Q.CGEventTapEnable(tap, True)

    print("Listening for keypresses for 15s... press any key.")
    end = time.time() + 15
    while time.time() < end:
        Q.CFRunLoopRunInMode(Q.kCFRunLoopDefaultMode, 0.1, False)

    print(f"Done. Total keydowns detected: {_keydown_count}")


if __name__ == "__main__":
    main()
