"""No cursor Qt has to DRAW from an image (2026-09-29).

The Mac app crashed natively at 11:05 that day — EXC_BREAKPOINT in
QImage::toCGImage, reached from QWindowPrivate::setCursor on a mouse enter.
Qt's macOS plugin builds a few cursor shapes from bundled PNGs
(libqcocoa.dylib carries sizeallcursor.png, waitcursor.png, spincursor.png)
and converting one to a CGImage is what failed; the only such shape the app
used was SizeAllCursor, on the Tasks drag handle. The rest are native
NSCursors. An exception handler cannot catch a native crash, so the rule is
simply: none of the image-drawn shapes, anywhere in the app.
"""

import pathlib
import re

#: Shapes Qt's cocoa plugin draws from images rather than NSCursor.
IMAGE_DRAWN = ("SizeAllCursor", "WaitCursor", "BusyCursor", "WhatsThisCursor",
               "SizeFDiagCursor", "SizeBDiagCursor", "BlankCursor", "BitmapCursor")


def test_no_image_drawn_cursor_anywhere():
    root = pathlib.Path(__file__).resolve().parents[2] / "assistant"
    found = []
    for f in root.rglob("*.py"):
        for n, line in enumerate(f.read_text(errors="ignore").splitlines(), 1):
            if re.search(r"CursorShape\.(%s)\b" % "|".join(IMAGE_DRAWN), line):
                found.append(f"{f.relative_to(root.parent)}:{n}: {line.strip()}")
    assert not found, "image-drawn cursors crash the Mac app natively:\n" + "\n".join(found)
