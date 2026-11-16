"""ArtifactsPanel — one row per task subfolder alongside loose files, both
in the same newest-first, grouped-by-day list. See widgets/artifacts_panel.py
and core.config.artifact_task_dir().
"""
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import core_bridge  # noqa: F401,E402  (puts prism_terminal/core on sys.path)

from PySide6.QtWidgets import QApplication  # noqa: E402

_app = QApplication.instance() or QApplication([])


def _widgets(col):
    return [col.itemAt(i).widget() for i in range(col.count())
           if col.itemAt(i).widget() is not None]


class TaskFoldersAlongsideLooseFiles(unittest.TestCase):

    def setUp(self):
        import core_bridge as CB
        from widgets.artifacts_panel import ArtifactsPanel
        self.CB = CB
        self.Panel = ArtifactsPanel
        self._real_dir = CB.config.ARTIFACTS_DIR
        self._tmp = tempfile.TemporaryDirectory()
        CB.config.ARTIFACTS_DIR = self._tmp.name
        self._src = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
        self._src.write(b"fake image bytes")
        self._src.close()

    def tearDown(self):
        self.CB.config.ARTIFACTS_DIR = self._real_dir
        self._tmp.cleanup()
        os.unlink(self._src.name)

    def _names(self, panel):
        # Rows now sit inside one Card per day, so look through the cards too.
        from widgets.controls import FileItem
        return [w._name for w in panel._col.parentWidget().findChildren(FileItem)]

    def test_a_task_folder_gets_its_own_row(self):
        self.CB.config.save_artifact(self._src.name, "a poster", kind="visual",
                                     task="the nova launch")
        panel = self.Panel()
        panel.build()
        names = self._names(panel)
        self.assertTrue(any(n and "the nova launch" in n for n in names))

    def test_each_run_of_a_task_is_its_own_card(self):
        """Two runs of the same words: two cards, each named for the task
        and its time — the Artifacts screen showed them as one."""
        self.CB.config.begin_run("the nova launch")
        self.CB.config.save_artifact(self._src.name, "a poster", kind="visual",
                                     task="the nova launch")
        second = self.CB.config.begin_run("the nova launch")
        self.CB.config.save_artifact(self._src.name, "a poster", kind="visual",
                                     task="the nova launch")
        panel = self.Panel()
        panel.build()
        cards = [n for n in self._names(panel) if n and "the nova launch" in n]
        self.assertEqual(len(cards), 2, cards)
        self.assertTrue(all("·" in n for n in cards), cards)
        from widgets.artifacts_panel import _run_time
        self.assertIn(_run_time(second), cards[0] + cards[1])

    def test_the_about_file_is_not_counted(self):
        from widgets.artifacts_panel import _folder_stats
        folder = self.CB.config.begin_run("a described run")
        self.CB.config.save_artifact(self._src.name, "one", kind="visual",
                                     task="a described run")
        count, _ = _folder_stats(folder)
        self.assertEqual(count, 1)

    def test_a_loose_file_still_gets_its_own_row_too(self):
        self.CB.config.save_artifact(self._src.name, "a poster", kind="visual")
        panel = self.Panel()
        panel.build()
        names = self._names(panel)
        self.assertTrue(any(n and "poster" in n.lower() for n in names))

    def test_the_folder_row_reports_how_many_files_it_holds(self):
        from widgets.artifacts_panel import _folder_stats
        task_dir = self.CB.config.artifact_task_dir("a busy task")
        self.CB.config.save_artifact(self._src.name, "one", kind="visual",
                                     task="a busy task")
        self.CB.config.save_artifact(self._src.name, "two", kind="visual",
                                     task="a busy task")
        count, size = _folder_stats(task_dir)
        self.assertEqual(count, 2)
        self.assertTrue(size)

    def test_folder_stats_walks_into_nested_subfolders(self):
        """Gerber's cleaned-copy output keeps its own previews/ subfolder —
        the count must not stop at the first level."""
        from widgets.artifacts_panel import _folder_stats
        task_dir = self.CB.config.artifact_task_dir("a gerber job")
        nested = os.path.join(task_dir, "cleaned", "previews")
        os.makedirs(nested, exist_ok=True)
        with open(os.path.join(task_dir, "cleaned", "report.txt"), "w") as f:
            f.write("x")
        with open(os.path.join(nested, "a.svg"), "w") as f:
            f.write("<svg/>")
        count, _size = _folder_stats(task_dir)
        self.assertEqual(count, 2)

    def test_a_link_sidecar_is_not_counted_as_a_file(self):
        from widgets.artifacts_panel import _folder_stats
        task_dir = self.CB.config.artifact_task_dir("a chat task")
        dest = self.CB.config.save_artifact(
            self._src.name, "a poster", kind="visual", task="a chat task",
            link="https://chatgpt.com/c/abc")
        self.assertTrue(os.path.isfile(dest + ".link.txt"))
        count, _size = _folder_stats(task_dir)
        self.assertEqual(count, 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
