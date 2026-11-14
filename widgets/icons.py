"""The design system's line icons, as real vectors.

Industry draws every icon as a 24×24 stroked path — 1.6px, round caps, round
joins, no fill — so the icon weight matches the hairline borders around it.
Emoji can't do that: they arrive pre-coloured, pre-filled, and at whatever
weight the platform font vendor chose, which is why the old dark theme's 📊/🔑
glyphs would look pasted-on here.

Paths are lifted verbatim from the design file. `icon()` returns a QIcon and
`pixmap()` a device-pixel-ratio-correct QPixmap, both tinted to any token
colour, both cached — these get requested once per repaint of a list row."""
from __future__ import annotations
from PySide6.QtCore import QByteArray, Qt, QSize, QRectF
from PySide6.QtGui import QIcon, QPixmap, QPainter, QColor
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import QApplication
import re

import paths
import theme

# name -> list of "d" attributes, stroked.
_STROKED: dict[str, list[str]] = {
    "prism":      ["M12 3l8 9-8 9-8-9z", "M12 3v18"],
    "check":      ["M4 12l5 5L20 6"],
    "search":     ["M4 11a7 7 0 1 0 14 0 7 7 0 1 0-14 0z", "M21 21l-4.3-4.3"],
    "pencil":     ["M12 20h9", "M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4z"],
    "present":    ["M3 4h18v12H3z", "M12 16v4", "M8 20h8"],
    "chevron-down":  ["M6 9l6 6 6-6"],
    "chevron-right": ["M9 6l6 6-6 6"],
    "chevron-left":  ["M15 6l-6 6 6 6"],
    "home":       ["M4 11l8-7 8 7", "M6 10v9h12v-9"],
    "grid":       ["M4 4h7v7H4z", "M13 4h7v7h-7z", "M4 13h7v7H4z", "M13 13h7v7h-7z"],
    "clock":      ["M4 12a8 8 0 1 0 16 0 8 8 0 1 0-16 0z", "M12 8v4l3 2"],
    "sliders":    ["M4 8h9", "M17 8h3", "M13 8a2 2 0 1 0 4 0 2 2 0 1 0-4 0z",
                   "M4 16h3", "M11 16h9", "M7 16a2 2 0 1 0 4 0 2 2 0 1 0-4 0z"],
    "folder":     ["M3 6h6l2 2h10v11H3z"],
    "file":       ["M6 3h8l4 4v14H6z", "M14 3v4h4"],
    "mic":        ["M12 3a3 3 0 0 1 3 3v5a3 3 0 0 1-6 0V6a3 3 0 0 1 3-3z",
                   "M6 11a6 6 0 0 0 12 0", "M12 17v4", "M8 21h8"],
    "paperclip":  ["M20 11l-8 8a4.5 4.5 0 0 1-6.4-6.4l8.4-8.4a3 3 0 0 1 4.3 "
                   "4.3l-8.3 8.3a1.5 1.5 0 0 1-2.2-2.1l7.5-7.5"],
    "plus":       ["M12 5v14", "M5 12h14"],
    "minus":      ["M5 12h14"],
    "help":       ["M4 12a8 8 0 1 0 16 0 8 8 0 1 0-16 0z",
                   "M9.6 9.4a2.5 2.5 0 0 1 4.2-1.2c1 .9.7 2-.3 2.7-.8.5-1.5 1-1.5 2",
                   "M12 16.5h.01"],
    "mail":       ["M3 6h18v12H3z", "M3 7l9 6 9-6"],
    # A tray with mail landing in it — distinct from "mail" at 16px, which
    # matters because the two sit four rows apart in the same rail.
    "inbox":      ["M3 13h5l1.5 3h5L16 13h5", "M3 13l3-8h12l3 8v6H3z"],
    # A speech bubble with a tail — WhatsApp, and any messaging surface.
    "message":    ["M4 5h16v10H8l-4 4z"],
    "chat":       ["M4 5h16v10H8l-4 4z"],
    "message-circle": ["M4 5h16v10H8l-4 4z"],
    "film":       ["M3 4h18v12H3z", "M12 16v4", "M8 20h8"],
    "file-text":  ["M6 3h8l4 4v14H6z", "M14 3v4h4", "M9 13h6", "M9 17h4"],
    "users":      ["M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2", "M9 7a4 4 0 1 0 0-8 4 4 0 0 0 0 8z"],
    "settings":   ["M4 8h9", "M17 8h3", "M13 8a2 2 0 1 0 4 0 2 2 0 1 0-4 0z", "M4 16h3", "M11 16h9", "M7 16a2 2 0 1 0 4 0 2 2 0 1 0-4 0z"],
    "calendar":   ["M4 4h16v16H4z", "M4 9h16", "M9 2v4", "M15 2v4"],
    "headset":    ["M4 14v-3a8 8 0 0 1 16 0v3", "M18 19c0 1.1-.9 2-2 2h-1", "M4 14a2 2 0 0 1 2-2h1v5H6a2 2 0 0 1-2-2z", "M20 14a2 2 0 0 0-2-2h-1v5h1a2 2 0 0 0 2-2z"],
    "key":        ["M14 7a4 4 0 1 0 0 8 4 4 0 0 0 0-8z", "M14 11h7", "M18 11v3"],
    "book":       ["M4 5a2 2 0 0 1 2-2h12v16H6a2 2 0 0 0-2 2z", "M8 7h7"],
    "globe":      ["M4 12a8 8 0 1 0 16 0 8 8 0 1 0-16 0z", "M4 12h16",
                   "M12 4a12 12 0 0 1 0 16 12 12 0 0 1 0-16z"],
    "lock":       ["M6 11h12v9H6z", "M9 11V8a3 3 0 0 1 6 0v3"],
    "eye":        ["M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7S2 12 2 12z",
                   "M12 9a3 3 0 1 0 0 6 3 3 0 0 0 0-6z"],
    "eye-off":    ["M3 3l18 18", "M10.6 10.6a2 2 0 0 0 2.8 2.8",
                   "M9.9 5.1A10.8 10.8 0 0 1 12 5c6.5 0 10 7 10 7a15.8 15.8 0 0 1-3.1 4.1",
                   "M6.2 6.2C3.5 8 2 12 2 12s3.5 7 10 7a10 10 0 0 0 3-.5"],
    "chart":      ["M5 19V9", "M12 19V5", "M19 19v-6", "M3 21h18"],
    "archive":    ["M4 7h16v13H4z", "M3 3h18v4H3z", "M10 11h4"],
    "user":       ["M12 4a4 4 0 1 0 0 8 4 4 0 0 0 0-8z", "M5 21a7 7 0 0 1 14 0"],
    "copy":       ["M9 9h11v11H9z", "M5 15V4h11"],
    "external":   ["M14 4h6v6", "M20 4l-9 9", "M18 14v6H4V6h6"],
    "trash":      ["M4 7h16", "M9 7V4h6v3", "M6 7l1 13h10l1-13"],
    "x":          ["M6 6l12 12", "M18 6L6 18"],
    "alert":      ["M12 4l9 16H3z", "M12 10v4", "M12 17h.01"],
    # Two subpaths on purpose — body and clapper — so the dot badge the
    # dashboard paints over the top has a shoulder to sit on.
    "bell":       ["M6 8a6 6 0 0 1 12 0c0 5 2 6 2 6H4s2-1 2-6z",
                   "M10 20a2 2 0 0 0 4 0"],
    "spinner":    ["M12 4v4", "M12 16v4", "M4 12h4", "M16 12h4"],
    "bulb":       ["M12 3a6 6 0 0 1 3.5 10.9V17h-7v-3.1A6 6 0 0 1 12 3z",
                   "M10 20h4"],
    "image":      ["M3 5h18v14H3z", "M3 16l5-5 4 4 3-3 6 6",
                   "M8 9a1.3 1.3 0 1 0 2.6 0A1.3 1.3 0 0 0 8 9z"],
    "video":      ["M3 6h12v12H3z", "M15 10l6-4v12l-6-4"],
    "code":       ["M9 8l-5 4 5 4", "M15 8l5 4-5 4"],
    "list":       ["M4 7h16", "M4 12h16", "M4 17h10"],
    "arrow-right": ["M4 12h15", "M13 6l6 6-6 6"],
    "arrow-up":   ["M12 20V5", "M6 11l6-6 6 6"],
    "stop":       ["M6 6h12v12H6z"],
    "sun":        ["M12 3v2", "M12 19v2", "M4.22 4.22l1.42 1.42", "M18.36 18.36l1.42 1.42",
                   "M3 12h2", "M19 12h2", "M4.22 19.78l1.42-1.42", "M18.36 5.64l1.42-1.42",
                   "M12 7a5 5 0 1 0 0 10 5 5 0 0 0 0-10z"],
    "command":    ["M18 9a3 3 0 1 0-3-3v3h-6V6a3 3 0 1 0-3 3h3v6H6a3 3 0 1 0 3 3v-3h6v3a3 3 0 1 0 3-3h-3V9h3z"],
    "sparkles":   ["M12 3l1.9 5.8a2 2 0 0 0 1.3 1.3L21 12l-5.8 1.9a2 2 0 0 0-1.3 1.3L12 21l-1.9-5.8a2 2 0 0 0-1.3-1.3L3 12l5.8-1.9a2 2 0 0 0 1.3-1.3z"],
    "film":       ["M4 4h16a2 2 0 0 1 2 2v12a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2z",
                   "M2 8h20", "M2 16h20", "M6 4v4", "M6 16v4", "M18 4v4", "M18 16v4"],
    # Leads & Outreach (Apollo's Find People): the import cards, the person
    # panel's actions and the all-filters window.
    "users":      ["M9 11a3.5 3.5 0 1 0 0-7 3.5 3.5 0 1 0 0 7z", "M2.5 20a6.5 6.5 0 0 1 13 0",
                   "M16 4.6a3.5 3.5 0 0 1 0 6.3", "M18.5 14.2a6.5 6.5 0 0 1 3 5.8"],
    "building":   ["M5 21V4h10v17", "M15 9h4v12", "M3 21h18", "M8.5 8h.01", "M11.5 8h.01",
                   "M8.5 12h.01", "M11.5 12h.01", "M8.5 16h.01", "M11.5 16h.01"],
    "upload":     ["M12 16V4", "M7 9l5-5 5 5", "M4 16v4h16v-4"],
    "download":   ["M12 4v12", "M7 11l5 5 5-5", "M4 16v4h16v-4"],
    "phone":      ["M5 4h4l2 5-2.5 1.5a11 11 0 0 0 5 5L15 13l5 2v4a2 2 0 0 1-2 2A16 16 0 0 1 3 6a2 2 0 0 1 2-2z"],
    "calendar":   ["M4 6h16v14H4z", "M4 10h16", "M8 3v4", "M16 3v4"],
    "check-square": ["M4 4h16v16H4z", "M8 12l3 3 5-6"],
    "send":       ["M21 3L10 14", "M21 3l-7 18-4-7-7-4z"],
    "maximize":   ["M14 4h6v6", "M20 4l-7 7", "M10 20H4v-6", "M4 20l7-7"],
    "minimize":   ["M4 14h6v6", "M10 14l-7 7", "M20 10h-6V4", "M14 10l7-7"],
    "pin":        ["M9 4h6", "M10 4v6l-3 4h10l-3-4V4", "M12 14v6"],
    "linkedin":   ["M4 4h16v16H4z", "M8 10v6", "M8 7v.01", "M12 16v-6", "M12 12a2 2 0 0 1 4 0v4"],
    "list-plus":  ["M4 6h12", "M4 12h12", "M4 18h7", "M17 15v6", "M14 18h6"],
    "activity":   ["M3 12h4l3-8 4 16 3-8h4"],
    "drag":       ["M9 6h.01", "M15 6h.01", "M9 12h.01", "M15 12h.01", "M9 18h.01", "M15 18h.01"],
    "chat-dots":  ["M21 11.5a8.5 8.5 0 0 1-8.5 8.5 8.4 8.4 0 0 1-3.8-.9L3 21l1.9-5.7a8.4 8.4 0 0 1-.9-3.8A8.5 8.5 0 1 1 21 11.5z",
                   "M8.5 11.5h.01", "M12 11.5h.01", "M15.5 11.5h.01"],
    "calendar-dots": ["M4 6h16a2 2 0 0 1 2 2v12a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2z",
                      "M8 2v4", "M16 2v4", "M2 10h20",
                      "M8 15h.01", "M12 15h.01", "M16 15h.01"],
    "headphones-mic": ["M4 14v-3a8 8 0 0 1 16 0v3",
                       "M2 15a2 2 0 0 1 2-2h1a2 2 0 0 1 2 2v4a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2z",
                       "M17 15a2 2 0 0 1 2-2h1a2 2 0 0 1 2 2v4a2 2 0 0 1-2 2h-1a2 2 0 0 1-2-2z",
                       "M19 19c0 1.5-1 2.5-2.5 2.5H14"],
}

# The preview's own glyphs (index.html <symbol id="i-*">), 24x24, drawn at 1.7px
# with round caps and joins. They replace the older drawings of the same name
# so every screen shows one icon set; the sidebar's add-on tiles use the new
# names sheet / chip / cube / box.
def _circle(cx: float, cy: float, r: float) -> str:
    return (f"M{cx - r:g} {cy:g}a{r:g} {r:g} 0 1 0 {2 * r:g} 0 "
            f"{r:g} {r:g} 0 1 0-{2 * r:g} 0z")


def _rect(x: float, y: float, w: float, h: float, r: float) -> str:
    return (f"M{x + r:g} {y:g}h{w - 2 * r:g}a{r:g} {r:g} 0 0 1 {r:g} {r:g}v{h - 2 * r:g}"
            f"a{r:g} {r:g} 0 0 1-{r:g} {r:g}h-{w - 2 * r:g}a{r:g} {r:g} 0 0 1-{r:g}-{r:g}"
            f"v-{h - 2 * r:g}a{r:g} {r:g} 0 0 1 {r:g}-{r:g}z")


_SHEET = "M14 3.5H7a2 2 0 0 0-2 2v13a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8.5z"
_CHAT = ["M20.5 12a8.3 8.3 0 0 1-12.3 7.3L3.5 20.5l1.3-4.4A8.3 8.3 0 1 1 20.5 12z",
         "M9 10.5h6M9 13.5h4"]
_STROKED.update({
    "home":    ["M3.5 10.5 12 3.5l8.5 7V20a1 1 0 0 1-1 1H15v-6H9v6H4.5a1 1 0 0 1-1-1z"],
    "clock":   [_circle(12, 12, 8.5), "M12 7.5V12l3 2"],
    "folder":  ["M3.5 7a2 2 0 0 1 2-2h3.8l2 2.2h7.2a2 2 0 0 1 2 2V17a2 2 0 0 1-2 2h-13a2 2 0 0 1-2-2z"],
    "inbox":   ["M3.5 13 6 5.5h12l2.5 7.5V18a1 1 0 0 1-1 1h-15a1 1 0 0 1-1-1z",
                "M3.5 13H8l1.5 2.5h5L16 13h4.5"],
    "sheet":   [_SHEET, "M14 3.5v5h5M8.5 12.5h7M8.5 16h7M12 12.5V16"],
    "file":    [_SHEET, "M14 3.5v5h5"],
    "chip":    [_rect(7, 7, 10, 10, 1.6),
                "M10 3.5V7M14 3.5V7M10 17v3.5M14 17v3.5M3.5 10H7M3.5 14H7M17 10h3.5M17 14h3.5"],
    "cube":    ["M12 3.2 19.8 7.6v8.8L12 20.8l-7.8-4.4V7.6z", "M4.2 7.6 12 12l7.8-4.4M12 12v8.8"],
    "mail":    [_rect(3.5, 5.5, 17, 13, 2), "M4 7.5l8 5.5 8-5.5"],
    "user":    [_circle(12, 8.5, 3.8), "M4.8 20.5a7.2 7.2 0 0 1 14.4 0"],
    "message": _CHAT, "chat": _CHAT, "message-circle": _CHAT,
    "box":     [_rect(4, 4, 7, 7, 1.5), _rect(13, 4, 7, 7, 1.5), _rect(4, 13, 7, 7, 1.5),
                "M14.5 16.5h4M16.5 14.5v4"],
    "grid":    [_rect(4, 4, 6.5, 6.5, 1.4), _rect(13.5, 4, 6.5, 6.5, 1.4),
                _rect(4, 13.5, 6.5, 6.5, 1.4), _rect(13.5, 13.5, 6.5, 6.5, 1.4)],
    "search":  [_circle(11, 11, 6.5), "M20 20l-4.2-4.2"],
    "trash":   ["M4.5 7h15M9.5 7V4.5h5V7M6.5 7l.9 12.5a1 1 0 0 0 1 .9h7.2a1 1 0 0 0 1-.9L17.5 7"],
    "x":       ["M6.5 6.5l11 11M17.5 6.5l-11 11"],
    "chevron-left":  ["m14.5 6-6 6 6 6"],
    "chevron-down":  ["m6 9.5 6 6 6-6"],
    "chevron-right": ["m9.5 6 6 6-6 6"],
    "check":   ["m5.5 12.5 4.2 4.2L18.5 8"],
    "sliders": ["M4 7h9M17 7h3M4 17h3M11 17h9", _circle(15, 7, 2), _circle(9, 17, 2)],
    "settings": ["M4 7h9M17 7h3M4 17h3M11 17h9", _circle(15, 7, 2), _circle(9, 17, 2)],
    "help":    [_circle(12, 12, 8.5), "M9.6 9.5a2.5 2.5 0 1 1 3.4 2.3c-.6.3-1 .8-1 1.5v.4",
                _circle(12, 16.8, .6)],
    "list":    ["M5 7h14M5 12h14M5 17h9"],
    "key":     [_circle(8, 15, 3.8), "M10.8 12.2l8.7-8.7M16 6.5l2.5 2.5M13.5 9l2 2"],
    "external": ["M14 4.5h5.5V10M19.5 4.5 11 13M18 14v4.5a1 1 0 0 1-1 1H5.5a1 1 0 0 1-1-1V7a1 1 0 0 1 1-1H10"],
    "lock":    [_rect(5, 10.5, 14, 10, 2), "M8.5 10.5V8a3.5 3.5 0 0 1 7 0v2.5"],
    "pencil":  ["M15.5 4.5l4 4L9 19H5v-4z", "M13.5 6.5l4 4"],
    "eye":     ["M2.5 12S6 5.5 12 5.5 21.5 12 21.5 12 18 18.5 12 18.5 2.5 12 2.5 12z",
                _circle(12, 12, 2.8)],
    "mic":     [_rect(9, 3.5, 6, 11, 3), "M5.5 11.5a6.5 6.5 0 0 0 13 0M12 18v2.5"],
    "video":   [_rect(3.5, 6.5, 12, 11, 2), "M15.5 10.5l5-3v9l-5-3"],
    "paperclip": ["m20 11.5-8 8a5 5 0 0 1-7-7l8.5-8.5a3.3 3.3 0 0 1 4.7 4.7L9.6 17.3a1.7 1.7 0 0 1-2.4-2.4L15 7"],
    "chart":   ["M6 19V11M12 19V5M18 19v-6"],
    "arrow-right": ["M5 12h14M13.5 6.5 19 12l-5.5 5.5"],
})

# The preview's glyphs that the Home page uses and no other screen did yet. New
# names, so nothing that already draws "film", "command" or "sparkles" changes.
_STROKED.update({
    "cmd":      ["M9 6.5a2.5 2.5 0 1 0-2.5 2.5h11A2.5 2.5 0 1 0 15 6.5v11a2.5 2.5 0 1 0 2.5-2.5"
                 "h-11A2.5 2.5 0 1 0 9 17.5z"],
    "spark":    ["M12 4v4M12 16v4M4 12h4M16 12h4M7 7l1.8 1.8M15.2 15.2 17 17M17 7l-1.8 1.8"
                 "M8.8 15.2 7 17"],
    "bars":     ["M6 19V11M12 19V5M18 19v-6"],
    "film-box": [_rect(3.5, 4.5, 17, 15, 2),
                 "M7.5 4.5v15M16.5 4.5v15M3.5 9.5h4M3.5 14.5h4M16.5 9.5h4M16.5 14.5h4"],
    "more-dots": [_circle(6, 12, .9), _circle(12, 12, .9), _circle(18, 12, .9)],
})

# Icons the design fills rather than strokes.
_FILLED: dict[str, list[str]] = {
    "play": ["M7 5l12 7-12 7z"],
    "send-plane": ["M22 2L15 22l-4-9-9-4 22-9z"],
    "more-horizontal": [
        "M12 10.5a1.5 1.5 0 1 0 0 3 1.5 1.5 0 0 0 0-3z "
        "M19 10.5a1.5 1.5 0 1 0 0 3 1.5 1.5 0 0 0 0-3z "
        "M5 10.5a1.5 1.5 0 1 0 0 3 1.5 1.5 0 0 0 0-3z",
    ],
}

_cache: dict[tuple, QPixmap] = {}


def _svg_color_attrs(color: str, prop: str) -> str:
    """Return the SVG colour attribute(s) for *prop* ('stroke' or 'fill').

    QtSvg does not parse CSS3 rgba(…) syntax inside attribute values — the
    renderer silently ignores the attribute and the icon becomes invisible.
    When the colour carries an alpha channel we emit the separate
    ``stroke-opacity`` / ``fill-opacity`` attribute instead, which QtSvg
    does understand at every version.
    """
    color_s = (color or "").strip()
    if color_s.startswith("rgba(") and color_s.endswith(")"):
        m = re.match(r"rgba\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*,\s*([\d\.]+)\s*\)", color_s)
        if m:
            r, g, b, a = m.groups()
            return f'{prop}="rgb({r},{g},{b})" {prop}-opacity="{a}"'
    qc = QColor(color)
    if not qc.isValid():
        # Fallback: let the theme string through and hope for the best.
        return f'{prop}="{color}"'
    if qc.alpha() < 255:
        r, g, b = qc.red(), qc.green(), qc.blue()
        a = f"{qc.alphaF():.3f}"
        return f'{prop}="rgb({r},{g},{b})" {prop}-opacity="{a}"'
    return f'{prop}="{color}"'


def _svg(name: str, color: str, stroke: float) -> bytes:
    # Every multi-part icon (sliders, home, grid, clock, …) used to render as
    # N sibling <path> elements under one <svg>. On macOS's QtSvg, only one of
    # those siblings would paint — a 6-stroke "sliders" icon came out as a
    # single flat dash, a 4-square "grid" as one square. Linux/Windows never
    # showed it, so it went undetected until a real Mac ran the packaged app.
    # A single <path> with multiple "M …" subpaths is standard SVG and has no
    # siblings for a renderer to selectively drop — same pixels everywhere.
    if name in _FILLED:
        d = " ".join(_FILLED[name])
        fill_attr = _svg_color_attrs(color, "fill")
        body = f'<path d="{d}" {fill_attr} stroke="none" fill-rule="evenodd"/>'
    else:
        paths = _STROKED.get(name)
        if paths is None:
            paths = _STROKED.get("chevron-right", ["M9 6l6 6-6 6"])
        d = " ".join(paths)
        stroke_attr = _svg_color_attrs(color, "stroke")
        body = (f'<path d="{d}" fill="none" {stroke_attr} stroke-width="{stroke}" '
                f'stroke-linecap="round" stroke-linejoin="round"/>')
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" '
            f'width="24" height="24">{body}</svg>').encode()


def pixmap(name: str, size: int = 18, color: str = theme.TEXT,
           stroke: float = 1.7) -> QPixmap:
    app = QApplication.instance()
    dpr = app.devicePixelRatio() if app else 1.0
    key = (name, size, color, stroke, dpr)
    hit = _cache.get(key)
    if hit is not None:
        return hit

    px = QPixmap(int(size * dpr), int(size * dpr))
    px.setDevicePixelRatio(dpr)
    px.fill(Qt.transparent)
    painter = QPainter(px)
    painter.setRenderHint(QPainter.Antialiasing)
    # render(painter) with NO target rect maps the SVG using the *physical*
    # pixmap size, not the dpr-scaled logical size set above — on a Retina
    # display (dpr=2) that mismatch made QSvgRenderer paint only the first
    # subpath of a multi-M path, scaled and cropped, with the rest silently
    # clipped away. An explicit logical-size rect fixes the mapping for any dpr.
    QSvgRenderer(QByteArray(_svg(name, color, stroke))).render(painter, QRectF(0, 0, size, size))
    painter.end()
    _cache[key] = px
    return px


def icon(name: str, size: int = 18, color: str = theme.TEXT,
         stroke: float = 1.7) -> QIcon:
    return QIcon(pixmap(name, size, color, stroke))


def icon_gapped(name: str, size: int = 14, color: str = theme.TEXT,
                gap: float = 3, stroke: float = 1.7) -> QIcon:
    """An icon with `gap` extra transparent px on its right. Qt puts a fixed
    4px between a button's icon and its text; the preview has ~6.6px, and the
    only handle on that is a wider icon."""
    app = QApplication.instance()
    dpr = app.devicePixelRatio() if app else 1.0
    base = pixmap(name, size, color, stroke)
    px = QPixmap(int((size + gap) * dpr + .5), int(size * dpr + .5))
    px.setDevicePixelRatio(dpr)
    px.fill(Qt.transparent)
    p = QPainter(px)
    p.drawPixmap(0, 0, base)
    p.end()
    return QIcon(px)


def button_icon(btn, name: str, size: int = 16, color: str = theme.TEXT,
                stroke: float = 1.7):
    """Set an icon on a button at its true pixel size (Qt otherwise scales to
    a 16px default that softens the 1.6px strokes)."""
    btn.setIcon(icon(name, size, color, stroke))
    btn.setIconSize(QSize(size, size))
    return btn


# ── brand mark ──────────────────────────────────────────────────────────────
# The logo is the one graphic that keeps its own colours: it is artwork, not an
# interface icon, so it is read from assets/ instead of being stroked out of the
# table above and tinted to a token. It is also taller than it is wide, so it is
# sized by height and the width follows the artboard's aspect.
_LOGO_PATH = paths.resource("assets", "prism-logo.svg")

_logo_cache: dict[tuple, QPixmap] = {}


def logo_pixmap(height: int = 24) -> QPixmap:
    app = QApplication.instance()
    dpr = app.devicePixelRatio() if app else 1.0
    key = (height, dpr)
    hit = _logo_cache.get(key)
    if hit is not None:
        return hit

    renderer = QSvgRenderer(_LOGO_PATH)
    box = renderer.defaultSize()
    width = max(1, round(height * box.width() / box.height())) if box.height() else height

    px = QPixmap(round(width * dpr), round(height * dpr))
    px.setDevicePixelRatio(dpr)
    px.fill(Qt.transparent)
    painter = QPainter(px)
    painter.setRenderHint(QPainter.Antialiasing)
    renderer.render(painter, QRectF(0, 0, width, height))
    painter.end()
    _logo_cache[key] = px
    return px


# The AlphaKore "AK" mark (preview/alphakore-reskin/img/ak-mark.svg), a single
# filled outline on a 789x480 artboard, for the "BY AlphaKore" byline.
_AK_PATH = ("M0,479 L295,480 L366,374 L330,312 L260,418 L106,417 L282,126 L387,302 "
            "L486,480 L789,480 L653,240 L787,18 L499,18 L420,134 L463,185 L531,75 "
            "L680,76 L577,245 L682,419 L521,417 L374,153 L283,0Z")


def ak_mark_pixmap(width: float, color: str = theme.INK) -> QPixmap:
    app = QApplication.instance()
    dpr = app.devicePixelRatio() if app else 1.0
    key = ("ak", width, color, dpr)
    hit = _logo_cache.get(key)
    if hit is not None:
        return hit
    height = width * 480 / 789
    px = QPixmap(round(width * dpr) + 1, round(height * dpr) + 1)
    px.setDevicePixelRatio(dpr)
    px.fill(Qt.transparent)
    svg = (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 789 480">'
           f'<path fill="{color}" fill-rule="evenodd" d="{_AK_PATH}"/></svg>').encode()
    painter = QPainter(px)
    painter.setRenderHint(QPainter.Antialiasing)
    QSvgRenderer(QByteArray(svg)).render(painter, QRectF(0, 0, width, height))
    painter.end()
    _logo_cache[key] = px
    return px


def logo_icon(height: int = 256) -> QIcon:
    """The mark as a QIcon — for setWindowIcon / taskbar, where Qt scales one
    large pixmap down to whatever the platform asks for."""
    return QIcon(logo_pixmap(height))


# ── tool brand logos ────────────────────────────────────────────────────────
_TOOL_SVGS: dict[str, str] = {
    "email": (
        '<svg viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">'
        '<path d="M3 6.5C3 5.12 4.12 4 5.5 4H7V13L3 10V6.5Z" fill="#4285F4"/>'
        '<path d="M21 6.5C21 5.12 19.88 4 18.5 4H17V13L21 10V6.5Z" fill="#34A853"/>'
        '<path d="M17 4L12 8L7 4H5.5C4.67 4 4 4.67 4 5.5V6.8L12 12.8L20 6.8V5.5C20 4.67 19.33 4 18.5 4H17Z" fill="#EA4335"/>'
        '<path d="M3 10V18.5C3 19.88 4.12 21 5.5 21H7V13L3 10Z" fill="#4285F4"/>'
        '<path d="M21 10V18.5C21 19.88 19.88 21 18.5 21H17V13L21 10Z" fill="#34A853"/>'
        '<path d="M7 13V21H17V13L12 9.2L7 13Z" fill="#FBBC04"/>'
        '</svg>'
    ),
    "gmail": "email",
    "boq": (
        '<svg viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">'
        '<path d="M14 2H6C4.9 2 4 2.9 4 4V20C4 21.1 4.9 22 6 22H18C19.1 22 20 21.1 20 20V8L14 2Z" fill="#10B981" fill-opacity="0.12" stroke="#10B981" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/>'
        '<path d="M14 2V8H20" stroke="#10B981" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/>'
        '<path d="M8 12H16M8 15H16M8 18H13" stroke="#059669" stroke-width="1.8" stroke-linecap="round"/>'
        '<rect x="7.5" y="11.5" width="9" height="7" rx="0.5" stroke="#10B981" stroke-width="1.2" stroke-opacity="0.4"/>'
        '</svg>'
    ),
    "gerber": (
        '<svg viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">'
        '<rect x="5" y="5" width="14" height="14" rx="2.5" fill="#064E3B" stroke="#10B981" stroke-width="1.8"/>'
        '<rect x="8.5" y="8.5" width="7" height="7" rx="1.5" fill="#10B981"/>'
        '<path d="M8.5 2V5M12 2V5M15.5 2V5" stroke="#F59E0B" stroke-width="1.5" stroke-linecap="round"/>'
        '<path d="M8.5 19V22M12 19V22M15.5 19V22" stroke="#F59E0B" stroke-width="1.5" stroke-linecap="round"/>'
        '<path d="M2 8.5H5M2 12H5M2 15.5H5" stroke="#F59E0B" stroke-width="1.5" stroke-linecap="round"/>'
        '<path d="M19 8.5H22M19 12H22M19 15.5H22" stroke="#F59E0B" stroke-width="1.5" stroke-linecap="round"/>'
        '</svg>'
    ),
    "step": (
        '<svg viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">'
        '<path d="M12 2.5L20.5 7.4V16.6L12 21.5L3.5 16.6V7.4L12 2.5Z" stroke="#0284C7" stroke-width="1.5" stroke-linejoin="round"/>'
        '<path d="M12 2.5L20.5 7.4L12 12.3L3.5 7.4L12 2.5Z" fill="#38BDF8"/>'
        '<path d="M3.5 7.4L12 12.3V21.5L3.5 16.6V7.4Z" fill="#0284C7"/>'
        '<path d="M20.5 7.4L12 12.3V21.5L20.5 16.6V7.4Z" fill="#0369A1"/>'
        '<path d="M12 12.3V21.5M12 12.3L20.5 7.4M12 12.3L3.5 7.4" stroke="#BAE6FD" stroke-width="1.2" stroke-linejoin="round"/>'
        '</svg>'
    ),
    "slack": (
        '<svg viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">'
        '<path d="M5.04 14.28C5.04 15.11 4.37 15.78 3.54 15.78C2.71 15.78 2.04 15.11 2.04 14.28C2.04 13.45 2.71 12.78 3.54 12.78H5.04V14.28Z" fill="#36C5F0"/>'
        '<path d="M6.54 14.28C6.54 13.45 7.21 12.78 8.04 12.78C8.87 12.78 9.54 13.45 9.54 14.28V18.78C9.54 19.61 8.87 20.28 8.04 20.28C7.21 20.28 6.54 19.61 6.54 18.78V14.28Z" fill="#36C5F0"/>'
        '<path d="M9.72 5.04C8.89 5.04 8.22 4.37 8.22 3.54C8.22 2.71 8.89 2.04 9.72 2.04C10.55 2.04 11.22 2.71 11.22 3.54V5.04H9.72Z" fill="#2EB67D"/>'
        '<path d="M9.72 6.54C10.55 6.54 11.22 7.21 11.22 8.04C11.22 8.87 10.55 9.54 9.72 9.54H5.22C4.39 9.54 3.72 8.87 3.72 8.04C3.72 7.21 4.39 6.54 5.22 6.54H9.72Z" fill="#2EB67D"/>'
        '<path d="M18.96 9.72C18.96 8.89 19.63 8.22 20.46 8.22C21.29 8.22 21.96 8.89 21.96 9.72C21.96 10.55 21.29 11.22 20.46 11.22H18.96V9.72Z" fill="#E01E5A"/>'
        '<path d="M17.46 9.72C17.46 10.55 16.79 11.22 15.96 11.22C15.13 11.22 14.46 10.55 14.46 9.72V5.22C14.46 4.39 15.13 3.72 15.96 3.72C16.79 3.72 17.46 4.39 17.46 5.22V9.72Z" fill="#E01E5A"/>'
        '<path d="M14.28 18.96C15.11 18.96 15.78 19.63 15.78 20.46C15.78 21.29 15.11 21.96 14.28 21.96C13.45 21.96 12.78 21.29 12.78 20.46V18.96H14.28Z" fill="#ECB22E"/>'
        '<path d="M14.28 17.46C13.45 17.46 12.78 16.79 12.78 15.96C12.78 15.13 13.45 14.46 14.28 14.46H18.78C19.61 14.46 20.28 15.13 20.28 15.96C20.28 16.79 19.61 17.46 18.78 17.46H14.28Z" fill="#ECB22E"/>'
        '</svg>'
    ),
    "notion": (
        '<svg viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">'
        '<rect x="3" y="3" width="18" height="18" rx="4" fill="#18181B"/>'
        '<path d="M7 7.5L14.5 7.5L16.5 16.5M7 7.5V16.5M7 7.5L14.5 16.5H16.5" stroke="#FFFFFF" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>'
        '</svg>'
    ),
    "chatgpt": (
        '<svg viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">'
        '<circle cx="12" cy="12" r="10" fill="#10A37F"/>'
        '<path d="M12 7V17M7 12H17M8.5 8.5L15.5 15.5M15.5 8.5L8.5 15.5" stroke="#FFFFFF" stroke-width="2" stroke-linecap="round"/>'
        '</svg>'
    ),
    "claude": (
        '<svg viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">'
        '<circle cx="12" cy="12" r="10" fill="#D97706"/>'
        '<path d="M12 4L13.8 9.5L19 12L13.8 14.5L12 20L10.2 14.5L5 12L10.2 9.5L12 4Z" fill="#FFFFFF"/>'
        '</svg>'
    ),
    "perplexity": (
        '<svg viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">'
        '<circle cx="12" cy="12" r="10" fill="#00A8A8"/>'
        '<rect x="8" y="8" width="8" height="8" rx="2" stroke="#FFFFFF" stroke-width="2"/>'
        '<path d="M12 5V19M5 12H19" stroke="#FFFFFF" stroke-width="1.8"/>'
        '</svg>'
    ),
    "inquiry": (
        '<svg viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">'
        '<rect x="2.5" y="4" width="19" height="15" rx="3" fill="#6366F1" fill-opacity="0.15" stroke="#6366F1" stroke-width="1.8"/>'
        '<path d="M3 6.5L12 12.5L21 6.5" stroke="#6366F1" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/>'
        '<circle cx="18" cy="18" r="5" fill="#4F46E5"/>'
        '<path d="M18 14.5L16 17.5H18.5L18 21L20.5 17.5H18.5L18 14.5Z" fill="#FBBF24"/>'
        '</svg>'
    ),
    "email inquiry": "inquiry",
    "email inquiry automati...": "inquiry",
    "email inquiry automation": "inquiry",
    "bom": (
        '<svg viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">'
        '<rect x="3" y="3" width="8" height="8" rx="2" fill="#F59E0B" fill-opacity="0.2" stroke="#F59E0B" stroke-width="1.6"/>'
        '<rect x="13" y="3" width="8" height="8" rx="2" fill="#D97706" fill-opacity="0.2" stroke="#D97706" stroke-width="1.6"/>'
        '<rect x="3" y="13" width="8" height="8" rx="2" fill="#B45309" fill-opacity="0.2" stroke="#B45309" stroke-width="1.6"/>'
        '<rect x="13" y="13" width="8" height="8" rx="2" fill="#FBBF24" fill-opacity="0.2" stroke="#FBBF24" stroke-width="1.6"/>'
        '<path d="M5.5 7H8.5M7 5.5V8.5" stroke="#D97706" stroke-width="1.5" stroke-linecap="round"/>'
        '<path d="M15.5 7H18.5" stroke="#B45309" stroke-width="1.5" stroke-linecap="round"/>'
        '<path d="M5.5 17H8.5" stroke="#B45309" stroke-width="1.5" stroke-linecap="round"/>'
        '<path d="M15.5 17H18.5M17 15.5V18.5" stroke="#D97706" stroke-width="1.5" stroke-linecap="round"/>'
        '</svg>'
    ),
    "bom & stock": "bom",
    "leads": (
        '<svg viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">'
        '<circle cx="10" cy="8" r="4" fill="#8B5CF6" fill-opacity="0.25" stroke="#8B5CF6" stroke-width="1.8"/>'
        '<path d="M3 19C3 15.5 6.5 14 10 14C13.5 14 17 15.5 17 19" stroke="#8B5CF6" stroke-width="1.8" stroke-linecap="round"/>'
        '<circle cx="18" cy="8" r="2.5" fill="#06B6D4" stroke="#06B6D4" stroke-width="1.5"/>'
        '<path d="M18 13C19.5 13 21.5 13.8 22 15.5" stroke="#06B6D4" stroke-width="1.5" stroke-linecap="round"/>'
        '</svg>'
    ),
    "leads & outreach": "leads",
    "motion": (
        '<svg viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">'
        '<rect x="3" y="3" width="18" height="18" rx="4" fill="#7C3AED" fill-opacity="0.15" stroke="#7C3AED" stroke-width="1.6"/>'
        '<path d="M5 14C7.5 9 10 7 12 12C14 17 16.5 15 19 10" stroke="#0284C7" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"/>'
        '<circle cx="19" cy="10" r="2" fill="#F43F5E"/>'
        '</svg>'
    ),
    "motion graphics": "motion",
    "reel / studio": "reel",
    "reel": (
        '<svg viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">'
        '<rect x="3" y="4" width="18" height="16" rx="3" fill="#EC4899"/>'
        '<path d="M10 8.5L16 12L10 15.5V8.5Z" fill="#FFFFFF"/>'
        '<path d="M3 8H21" stroke="#FFFFFF" stroke-width="1.5" stroke-opacity="0.6"/>'
        '</svg>'
    ),
}

_tool_logo_cache: dict[tuple, QPixmap] = {}


def tool_logo(tool_name: str, size: int = 26) -> QPixmap:
    """Authentic full-colour brand logo for a tool or add-on."""
    app = QApplication.instance()
    dpr = app.devicePixelRatio() if app else 1.0
    k = tool_name.lower().strip()
    key = (k, size, dpr)
    hit = _tool_logo_cache.get(key)
    if hit is not None:
        return hit

    svg_data = _TOOL_SVGS.get(k, "")
    if isinstance(svg_data, str) and svg_data in _TOOL_SVGS:
        svg_data = _TOOL_SVGS[svg_data]

    if not svg_data:
        # Fallback to stroked icon
        return pixmap(k, size, theme.TEXT)

    px = QPixmap(round(size * dpr), round(size * dpr))
    px.setDevicePixelRatio(dpr)
    px.fill(Qt.transparent)
    painter = QPainter(px)
    painter.setRenderHint(QPainter.Antialiasing)
    painter.setRenderHint(QPainter.SmoothPixmapTransform)
    renderer = QSvgRenderer(QByteArray(svg_data.encode("utf-8")))
    renderer.render(painter, QRectF(0, 0, size, size))
    painter.end()
    _tool_logo_cache[key] = px
    return px
