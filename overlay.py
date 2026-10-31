"""Transparent, click-through overlay window that follows the cursor while
picking, showing either the image-to-draw (region pick) or a small crosshair
(point pick). Must be driven from the main thread (Cocoa requirement);
autodraw.py runs the HTTP server on a worker thread and pokes this module via
performSelectorOnMainThread, the standard thread-safe way to update AppKit
from elsewhere."""
from AppKit import (
    NSApplication, NSBackingStoreBuffered, NSColor, NSImage, NSMakeRect,
    NSObject, NSScreenSaverWindowLevel, NSView, NSWindow,
    NSWindowStyleMaskBorderless,
)
from Foundation import NSBezierPath, NSData, NSMakePoint

ACCENT = (0x7c / 255, 0x6c / 255, 1.0)


class _MarkerView(NSView):
    def drawRect_(self, rect):
        mode = getattr(self, "mode", None)
        if mode == "image" and getattr(self, "image", None):
            self.image.drawInRect_fromRect_operation_fraction_(rect, ((0, 0), self.image.size()), 2, 0.85)  # NSCompositingOperationSourceOver
        elif mode == "point":
            NSColor.colorWithCalibratedRed_green_blue_alpha_(*ACCENT, 0.9).setFill()
            NSBezierPath.bezierPathWithOvalInRect_(NSMakeRect(rect.size.width / 2 - 4, rect.size.height / 2 - 4, 8, 8)).fill()
        NSColor.colorWithCalibratedRed_green_blue_alpha_(*ACCENT, 0.9).setStroke()
        p = NSBezierPath.bezierPathWithRect_(NSMakeRect(1.5, 1.5, rect.size.width - 3, rect.size.height - 3))
        p.setLineWidth_(3)
        p.stroke()


class _Controller(NSObject):
    def start(self):
        self.window = NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(
            NSMakeRect(0, 0, 10, 10), NSWindowStyleMaskBorderless, NSBackingStoreBuffered, False)
        self.window.setOpaque_(False)
        self.window.setBackgroundColor_(NSColor.clearColor())
        self.window.setIgnoresMouseEvents_(True)
        self.window.setHasShadow_(False)
        self.window.setLevel_(NSScreenSaverWindowLevel)
        self.view = _MarkerView.alloc().initWithFrame_(NSMakeRect(0, 0, 10, 10))
        self.window.setContentView_(self.view)
        return self

    def apply_(self, cmd):
        cmd = dict(cmd)
        action = cmd["action"]
        if action == "hide":
            self.window.orderOut_(None)
            return
        if action == "set_image":
            data = NSData.dataWithBytes_length_(cmd["png"], len(cmd["png"]))
            self.view.image = NSImage.alloc().initWithData_(data)
            self.view.mode = "image"
            return
        if action == "set_point":
            self.view.mode = "point"
            return
        x, y, w, h = cmd["x"], cmd["y"], cmd["w"], cmd["h"]
        screen_h = self.window.screen().frame().size.height if self.window.screen() else 1080
        self.window.setFrame_display_(NSMakeRect(x, screen_h - y - h, w, h), True)
        self.view.setNeedsDisplay_(True)
        self.window.orderFrontRegardless()


_app = None
_ctl = None


def init():
    """Call once, from the main thread, before run()."""
    global _app, _ctl
    _app = NSApplication.sharedApplication()
    _ctl = _Controller.alloc().init().start()


def run():
    """Blocks forever pumping the AppKit run loop. Call from the main thread."""
    _app.run()


def _send(cmd):
    _ctl.performSelectorOnMainThread_withObject_waitUntilDone_(_ctl.apply_, cmd, False)


def set_image(png_bytes):
    _send({"action": "set_image", "png": png_bytes})


def set_point():
    _send({"action": "set_point"})


def show(x, y, w, h):
    """Thread-safe: move/resize the overlay. Coordinates match mouse.py
    (top-left origin, same as CGDisplayBounds/CGEventPost)."""
    _send({"action": "show", "x": x, "y": y, "w": w, "h": h})


def hide():
    _send({"action": "hide"})
