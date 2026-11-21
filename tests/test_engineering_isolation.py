"""Engineering must not depend on Sales (work packages E3 and E3b).

Prism Engineering ships boq, bom, step and gerber WITHOUT the Sales add-ons
(inquiry, leads, whatsapp, email) and without the code only they need. These
tests parse the source with `ast` (so a function-local import counts, and no
dependency has to be installed) and fail on any import edge that would make an
Engineering bundle break, or silently drag a Sales module into it.

E3  : the GUI side, addons/{boq,bom,step,gerber}.
E3b : the engine side (the symlinked engine repo), checked transitively over
      the engine's own `core` modules. A test, not a change: if it fails, the
      ENGINE needs the fix, and the failure names the chain.

Pure source reading: no Qt window, no ~/.prism, no network. The one runtime
check (pricing without a `cfg["inquiry"]`) builds a widget, offscreen.
"""
from __future__ import annotations

import ast
import os
import sys
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

ENGINEERING_ADDONS = ("boq", "bom", "step", "gerber")

# Top-level names an Engineering add-on may never import. `addons.<x>` is
# matched on its second part; the rest on the first part.
SALES_ADDONS = {"inquiry", "leads", "whatsapp", "email", "reel", "motion"}
SALES_ROOT_MODULES = {"prospector", "inquiry_config", "email_config",
                      "send_ledger", "selenium", "undetected_chromedriver"}

ENGINE_CORE = os.path.join(ROOT, "prism_terminal", "core")
ENGINE_ENTRY = ("boq", "bom", "boq_price", "gerber", "gerber_clean",
                "gerber_form", "stepfile", "ocr", "quoting", "register")
ENGINE_SALES = {"automation", "mailer", "inbox", "triage", "mailflow",
                "drafting"}


def _py_files(folder):
    for base, _dirs, names in os.walk(folder):
        if "__pycache__" in base:
            continue
        for n in sorted(names):
            if n.endswith(".py"):
                yield os.path.join(base, n)


def _dotted_imports(path, package):
    """Every module this file imports, as absolute dotted names, anywhere in
    the file (top level, in a function, under try). `package` is the dotted
    package the file lives in, to resolve `from . import x` / `from ..a import`.
    `from pkg import name` also yields `pkg.name` (name may be a module)."""
    with open(path, encoding="utf-8") as fh:
        tree = ast.parse(fh.read(), path)
    found = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found += [(a.name, node.lineno) for a in node.names]
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                parts = package.split(".") if package else []
                parts = parts[:len(parts) - (node.level - 1)] if node.level > 1 else parts
                base = ".".join(parts + ([node.module] if node.module else []))
            else:
                base = node.module or ""
            found.append((base, node.lineno))
            found += [(base + "." + a.name if base else a.name, node.lineno)
                      for a in node.names]
    return found


def _sales_edge(dotted):
    parts = dotted.split(".")
    if parts[0] in SALES_ROOT_MODULES:
        return True
    return parts[0] == "addons" and len(parts) > 1 and parts[1] in SALES_ADDONS


class EngineeringAddonsDoNotImportSales(unittest.TestCase):

    def test_the_four_packages_exist_and_have_sources(self):
        for key in ENGINEERING_ADDONS:
            files = list(_py_files(os.path.join(ROOT, "addons", key)))
            self.assertTrue(files, "addons/%s has no python files" % key)

    def test_no_engineering_file_imports_a_sales_module(self):
        bad = []
        for key in ENGINEERING_ADDONS:
            for path in _py_files(os.path.join(ROOT, "addons", key)):
                rel = os.path.relpath(path, ROOT)
                pkg = os.path.dirname(rel).replace(os.sep, ".")
                for dotted, line in _dotted_imports(path, pkg):
                    if _sales_edge(dotted):
                        bad.append("%s:%d imports %s" % (rel, line, dotted))
        self.assertEqual(bad, [], "Engineering -> Sales import edges:\n"
                         + "\n".join(bad))

    def test_the_checker_really_catches_a_bad_edge(self):
        # Guard the guard: the same walker must flag each forbidden shape.
        import tempfile
        src = ("import selenium\n"
               "from addons.inquiry import board\n"
               "from addons import leads\n"
               "def f():\n    import inquiry_config\n"
               "    from ..email import x\n")
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "x.py")
            with open(p, "w") as fh:
                fh.write(src)
            hits = {n for n, _l in _dotted_imports(p, "addons.boq")
                    if _sales_edge(n)}
        self.assertTrue({"selenium", "addons.inquiry", "addons.leads",
                         "inquiry_config", "addons.email"} <= hits, hits)

    def test_pricing_works_when_the_config_has_no_inquiry_section(self):
        from PySide6.QtWidgets import QApplication
        _app = QApplication.instance() or QApplication([])
        from addons.boq import pricing
        for cfg in (None, {}, {"unrelated": 1}, {"inquiry": None}):
            self.assertEqual(pricing.rate_list_path(cfg), "")
        t = pricing.PricingTable({"unrelated": 1})
        t.set_quantities({"unit": "meters", "unit_code": 6,
                          "unit_confirmed": True,
                          "lengths_by_layer": {"WALL": 10.0},
                          "areas_by_layer": {}, "block_counts": {},
                          "block_layers": {}, "layers": ["WALL"],
                          "entity_count": 1})
        self.assertEqual(len(t.rows()), 1)


@unittest.skipUnless(os.path.isdir(ENGINE_CORE),
                     "engine not present at prism_terminal/core "
                     "(the symlinked engine repo)")
class EngineeringEngineModulesDoNotImportSalesModules(unittest.TestCase):

    @staticmethod
    def _core_imports(name):
        """Sibling `core` modules and forbidden names one module imports."""
        path = os.path.join(ENGINE_CORE, name + ".py")
        return [(d, l) for d, l in _dotted_imports(path, "core")]

    def test_entry_modules_exist(self):
        missing = [m for m in ENGINE_ENTRY
                   if not os.path.isfile(os.path.join(ENGINE_CORE, m + ".py"))]
        self.assertEqual(missing, [])

    def test_no_sales_engine_module_is_reachable(self):
        """Walk imports transitively through core.* from each Engineering
        module; report the first chain that reaches a Sales module."""
        problems = []
        for entry in ENGINE_ENTRY:
            seen = {entry}
            todo = [(entry, [entry])]
            while todo:
                mod, chain = todo.pop()
                for dotted, line in self._core_imports(mod):
                    parts = dotted.split(".")
                    leaf = parts[1] if parts[0] == "core" and len(parts) > 1 \
                        else None
                    if leaf is None:
                        continue
                    if leaf in ENGINE_SALES:
                        problems.append("%s.py:%d  %s -> %s" % (
                            mod, line, " -> ".join(chain), leaf))
                    elif leaf not in seen and os.path.isfile(
                            os.path.join(ENGINE_CORE, leaf + ".py")):
                        seen.add(leaf)
                        todo.append((leaf, chain + [leaf]))
        self.assertEqual(problems, [],
                         "engine Engineering modules reach Sales modules "
                         "(fix belongs in the engine repo):\n"
                         + "\n".join(problems))


if __name__ == "__main__":
    unittest.main()
