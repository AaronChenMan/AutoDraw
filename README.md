# AutoDraw

A local tool for macOS that turns an image into a set of pixel-art strokes and draws them into a Roblox canvas by driving the mouse and keyboard.

You load an image in a browser UI, choose a grid size and color count, calibrate where the drawing area and the color hex box are on screen, and press Draw. AutoDraw then selects each color and paints it row by row with drag strokes.

> **Heads up:** this automates mouse and keyboard input. Check the rules of any game you use it with before running it.

## How it works

1. **Load** an image (file, URL, or data URL) through the local web UI.
2. **Process**: the image is fit into a grid, reduced to N colors with median-cut quantization, and split into horizontal runs of identical pixels per color.
3. **Calibrate**: a transparent overlay follows your cursor so you can position and resize the drawing region (and click the color hex box) without guessing coordinates.
4. **Draw**: for each color, AutoDraw sets the hex value, then drags across each run in serpentine order to cut travel time.

A failsafe aborts the run if your real cursor moves away from where the script last put it, and any keypress stops the run.

## Files

| File | Purpose |
| --- | --- |
| `autodraw.py` | Entry point. Local HTTP server, image processing, drawing loop. |
| `index.html` | The browser UI, served by `autodraw.py`. |
| `mouse.py` | Mouse and keyboard control through Quartz CGEvents. Includes the failsafe and keypress stop. |
| `picker.py` | Live calibration: tracks the cursor and listens for +/-, Enter, Esc, and click. |
| `overlay.py` | Transparent, click-through AppKit window that shows the picker preview. |
| `test_keystop.py` | Standalone check that the keyboard event tap receives key presses. |

## Requirements

- macOS (uses Quartz, AppKit, and System Events)
- Python 3.10 or newer
- Roblox installed and running
- Terminal (or the Python app you run from) granted **Accessibility** and **Input Monitoring** in System Settings > Privacy & Security

Python packages:

- `pillow`
- `pyobjc-framework-Quartz`
- `pyobjc-framework-Cocoa` (provides `AppKit` and `Foundation`)

## Setup

```bash
python3 -m venv .venv
.venv/bin/pip install pillow pyobjc-framework-Quartz pyobjc-framework-Cocoa
```

## Usage

```bash
.venv/bin/python autodraw.py
```

This starts a server at `http://127.0.0.1:8765` and opens it in your browser. The server only listens on localhost.

Steps in the UI:

1. Load an image.
2. Set the grid size and number of colors, then process.
3. Pick the drawing region and the hex box. Use `+` and `-` to resize the region, Enter to confirm, Esc to cancel.
4. Adjust speed and press Draw. Press any key to stop.

To check that keyboard detection works:

```bash
.venv/bin/python test_keystop.py
```

## Notes

- Only one session runs at a time. State is held in memory in a single global object.
- Speed is controlled by the step size and delays in `mouse.py` (`STEP_PX`, `STEP_DELAY`). Raising the speed can make Roblox skip input.
- Keyboard input is sent directly to the Roblox process by PID, which was the only method that reliably reached Roblox in testing.

## License

No license has been chosen yet.
