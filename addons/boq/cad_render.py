"""Turn a DWG/DXF/PDF drawing into something a vision-capable AI can
actually look at (BOQ-CHANGES-TODO.md item 32).

Three different formats are three different problems, not one:

  - **PDF**: already something a vision-capable model (Claude, on
    OpenRouter) can read directly as a real document -- no conversion,
    just the right content-block shape in the API call.
  - **DXF**: real, exact vector geometry -- but it is TEXT (coordinates
    and codes), not a picture, so a vision model cannot "look" at it
    as-is. Rendered to a PNG here with ezdxf's own drawing add-on
    (already a hard dependency for the measuring side of this add-on;
    no new library) -- the same geometry `core/boq.py`'s own measurer
    already trusts, read once, not a second, different parse of the
    file for a second purpose.
  - **DWG**: Autodesk's closed, proprietary binary format. No library,
    no AI, nothing but Autodesk's own tooling (or a reverse-engineered
    convert) opens it at all. `ezdxf.addons.odafc` wraps the free "ODA
    File Converter" -- a SEPARATE desktop program, not a pip package --
    to turn it into a DXF `Drawing` first; from there it is the same
    DXF->PNG path above. If that program is not installed, this says so
    plainly rather than guessing or silently doing nothing.

Nothing here decides WHETHER a drawing may be sent anywhere at all --
that is, unchanged, `addons/boq/dialog.py`'s own `_drawing_consent()`
gate, asked before any of this ever runs.
"""
from __future__ import annotations

import base64
import os


class CadRenderError(Exception):
    """A drawing could not be turned into something an AI can look at.
    Always carries a plain, actionable reason, never a bare traceback."""


def odafc_installed() -> bool:
    from ezdxf.addons import odafc
    return odafc.is_installed()


def dwg_to_drawing(dwg_path: str):
    """A DWG file -> an ezdxf Drawing, via the ODA File Converter. Raises
    CadRenderError with a real, actionable reason -- the converter isn't
    installed, or the file itself couldn't be read -- never a bare
    traceback from the add-on."""
    from ezdxf.addons import odafc
    if not odafc.is_installed():
        raise CadRenderError(
            "Reading a .dwg file needs the free ODA File Converter "
            "installed on this machine (odaconverter.com) — Prism does not "
            "bundle it. Export the drawing as .dxf instead, or install the "
            "converter and try again.")
    try:
        return odafc.readfile(dwg_path)
    except Exception as e:                                  # noqa: BLE001
        raise CadRenderError(
            f"Couldn't convert {os.path.basename(dwg_path)}: {e}") from e


def render_dxf_to_png(source, out_path: str, *, dpi: int = 200) -> str:
    """`source` is a DXF file path, or an already-open ezdxf Drawing
    (dwg_to_drawing's own return value) — rendered to a PNG with
    ezdxf's own drawing add-on (matplotlib backend)."""
    import ezdxf
    from ezdxf.addons.drawing import RenderContext, Frontend
    from ezdxf.addons.drawing.matplotlib import MatplotlibBackend
    import matplotlib
    matplotlib.use("Agg")                                   # no display needed, ever
    import matplotlib.pyplot as plt

    try:
        doc = source if hasattr(source, "modelspace") else ezdxf.readfile(source)
    except Exception as e:                                  # noqa: BLE001
        raise CadRenderError(
            f"Couldn't read {os.path.basename(str(source))} as a DXF "
            f"drawing: {e}") from e
    msp = doc.modelspace()
    fig = plt.figure()
    ax = fig.add_axes((0, 0, 1, 1))
    # NOT ax.set_axis_off() -- found live, 30 Oct 2026: it silently blanks
    # the whole render. ezdxf's own Frontend/MatplotlibBackend paints its
    # background as a patch tied to the axes' own patch visibility, which
    # set_axis_off() also hides -- the geometry was always being drawn
    # (confirmed via ax.get_xlim() showing the real data bounds both ways),
    # just onto a patch matplotlib was never asked to show. ezdxf draws its
    # own background colour regardless of savefig's facecolor= (a dark
    # patch over the ENTIRE axes, confirmed by direct comparison) -- ticks/
    # spines are left on rather than risk the same trap a second way for a
    # cosmetic-only change an AI reading the image does not need anyway.
    ctx = RenderContext(doc)
    backend = MatplotlibBackend(ax)
    Frontend(ctx, backend).draw_layout(msp, finalize=True)
    os.makedirs(os.path.dirname(os.path.abspath(out_path)) or ".", exist_ok=True)
    fig.savefig(out_path, dpi=dpi)
    plt.close(fig)
    return out_path


def prepare_for_ai(path: str, *, tmp_dir: str = "") -> dict:
    """path -> a content block a vision-capable OpenRouter model can
    actually look at:
      {"kind": "image", "mime": "image/png", "b64": "...", "name": "..."}
      {"kind": "pdf", "mime": "application/pdf", "b64": "...", "name": "..."}
    A PDF is sent AS-IS, never rendered to an image first — Claude reads
    a real PDF document natively (every page, any real text in it too);
    rasterising it first would throw that away for no benefit. DXF/DWG
    have no such native path, so they ARE rendered, via the functions
    above. Raises CadRenderError for anything else, or if rendering
    itself fails — never a silent empty result."""
    ext = os.path.splitext(path)[1].lower()
    tmp_dir = tmp_dir or os.path.dirname(os.path.abspath(path))
    stem = os.path.splitext(os.path.basename(path))[0]

    if ext == ".pdf":
        with open(path, "rb") as f:
            data = f.read()
        return {"kind": "pdf", "mime": "application/pdf",
                "b64": base64.b64encode(data).decode("ascii"),
                "name": os.path.basename(path)}

    if ext == ".dxf":
        png_path = os.path.join(tmp_dir, f"{stem}_render.png")
        render_dxf_to_png(path, png_path)
    elif ext == ".dwg":
        doc = dwg_to_drawing(path)
        png_path = os.path.join(tmp_dir, f"{stem}_render.png")
        render_dxf_to_png(doc, png_path)
    else:
        raise CadRenderError(
            f"Don't know how to show a {ext or 'this'} file to an AI — "
            "only .pdf, .dxf and .dwg are supported.")

    with open(png_path, "rb") as f:
        data = f.read()
    return {"kind": "image", "mime": "image/png",
            "b64": base64.b64encode(data).decode("ascii"),
            "name": os.path.basename(png_path)}
