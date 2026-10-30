"""addons/boq/cad_render.py -- item 32: turning a DWG/DXF/PDF into
something a vision-capable AI can actually look at.

Every DXF here is built in memory with ezdxf, never a client's real
file (CLAUDE.md's own rule -- reconstruct a synthetic fixture).
"""
from __future__ import annotations

import base64
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from addons.boq import cad_render as R                             # noqa: E402


def _synthetic_dxf(path: str):
    import ezdxf
    doc = ezdxf.new()
    msp = doc.modelspace()
    msp.add_line((0, 0), (10, 0))
    msp.add_line((10, 0), (10, 10))
    msp.add_circle((5, 5), 2)
    doc.saveas(path)
    return path


class RenderDxfToPngProducesARealPictureNotABlankOne(unittest.TestCase):
    """30 Oct 2026: the first version of this function called
    ax.set_axis_off(), which silently blanked the whole render -- ezdxf's
    own background patch is tied to the axes' patch visibility, which
    that call also hides. Found by actually opening the output image,
    not by the code running without error. This checks it stays fixed by
    looking at the PIXELS, not just that a file got written."""

    def test_the_output_file_is_not_blank(self):
        from PIL import Image
        with tempfile.TemporaryDirectory() as d:
            dxf_path = _synthetic_dxf(os.path.join(d, "x.dxf"))
            png_path = os.path.join(d, "x.png")
            R.render_dxf_to_png(dxf_path, png_path)
            img = Image.open(png_path).convert("RGB")
            colors = img.getcolors(maxcolors=1_000_000)
        # A blank render is exactly one colour across every pixel; real
        # geometry (a background plus drawn lines/a circle) is at least
        # two.
        self.assertIsNotNone(colors)
        self.assertGreater(len(colors), 1,
                           "render has only one colour -- looks blank")

    def test_an_already_open_drawing_renders_the_same_as_a_file_path(self):
        """prepare_for_ai hands dwg_to_drawing's own in-memory Drawing
        straight to this function, never round-tripping through a second
        file -- this is what makes that path work."""
        import ezdxf
        from PIL import Image
        with tempfile.TemporaryDirectory() as d:
            dxf_path = _synthetic_dxf(os.path.join(d, "x.dxf"))
            doc = ezdxf.readfile(dxf_path)
            png_path = os.path.join(d, "from_doc.png")
            R.render_dxf_to_png(doc, png_path)
            colors = Image.open(png_path).convert("RGB").getcolors(maxcolors=1_000_000)
        self.assertGreater(len(colors), 1)

    def test_a_corrupt_dxf_raises_cadrendererror_not_a_bare_traceback(self):
        with tempfile.TemporaryDirectory() as d:
            bad_path = os.path.join(d, "bad.dxf")
            with open(bad_path, "w") as f:
                f.write("not a real dxf file")
            with self.assertRaises(R.CadRenderError):
                R.render_dxf_to_png(bad_path, os.path.join(d, "out.png"))


class DwgToDrawingNamesTheRealReasonWhenTheConverterIsMissing(unittest.TestCase):
    def test_converter_not_installed_raises_a_plain_actionable_message(self):
        with mock.patch("ezdxf.addons.odafc.is_installed", return_value=False):
            with self.assertRaises(R.CadRenderError) as cm:
                R.dwg_to_drawing("/x/whatever.dwg")
        self.assertIn("ODA File Converter", str(cm.exception))

    def test_converter_installed_but_the_file_fails_still_raises_cadrendererror(self):
        with mock.patch("ezdxf.addons.odafc.is_installed", return_value=True), \
                mock.patch("ezdxf.addons.odafc.readfile",
                          side_effect=RuntimeError("bad DWG version")):
            with self.assertRaises(R.CadRenderError):
                R.dwg_to_drawing("/x/whatever.dwg")

    def test_converter_installed_and_working_returns_whatever_it_gives_back(self):
        sentinel = object()
        with mock.patch("ezdxf.addons.odafc.is_installed", return_value=True), \
                mock.patch("ezdxf.addons.odafc.readfile", return_value=sentinel):
            out = R.dwg_to_drawing("/x/whatever.dwg")
        self.assertIs(out, sentinel)


class PrepareForAiDispatchesByExtension(unittest.TestCase):
    def test_a_pdf_is_sent_as_is_never_rendered(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "x.pdf")
            with open(path, "wb") as f:
                f.write(b"%PDF-1.4 fake pdf bytes")
            with mock.patch.object(R, "render_dxf_to_png") as render:
                block = R.prepare_for_ai(path)
        self.assertFalse(render.called)
        self.assertEqual(block["kind"], "pdf")
        self.assertEqual(block["mime"], "application/pdf")
        self.assertEqual(base64.b64decode(block["b64"]), b"%PDF-1.4 fake pdf bytes")

    def test_a_dxf_is_rendered_to_an_image_block(self):
        with tempfile.TemporaryDirectory() as d:
            dxf_path = _synthetic_dxf(os.path.join(d, "x.dxf"))
            block = R.prepare_for_ai(dxf_path, tmp_dir=d)
        self.assertEqual(block["kind"], "image")
        self.assertEqual(block["mime"], "image/png")
        self.assertTrue(block["b64"])

    def test_a_dwg_goes_through_conversion_then_rendering(self):
        import ezdxf
        synth = ezdxf.new()
        synth.modelspace().add_line((0, 0), (1, 1))
        with tempfile.TemporaryDirectory() as d:
            dwg_path = os.path.join(d, "x.dwg")
            with open(dwg_path, "wb") as f:
                f.write(b"fake dwg bytes")
            with mock.patch.object(R, "dwg_to_drawing", return_value=synth) as conv:
                block = R.prepare_for_ai(dwg_path, tmp_dir=d)
        self.assertTrue(conv.called)
        self.assertEqual(block["kind"], "image")

    def test_an_unsupported_extension_raises_rather_than_guessing(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "x.docx")
            with open(path, "w") as f:
                f.write("not a drawing")
            with self.assertRaises(R.CadRenderError):
                R.prepare_for_ai(path, tmp_dir=d)


if __name__ == "__main__":
    unittest.main()
