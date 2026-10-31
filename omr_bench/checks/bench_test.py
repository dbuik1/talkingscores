"""Checks for the bench's scoring, reader runner and set loader.

Run in the bench environment:
    python -m unittest discover -s omr_bench/checks -p "*_test.py" -t .
"""

import sys
import tempfile
import unittest
from pathlib import Path

from music21 import corpus, converter, dynamics

from omr_bench.engines import Engine, extract_music, run
from omr_bench.score import score_item
from omr_bench.sets import Item, load_items


def write_lindenbaum(path, bars=8):
    corpus.parse("schubert/Lindenbaum.xml").measures(1, bars).write("musicxml", fp=str(path))


class ScoringTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.folder = tempfile.TemporaryDirectory()
        cls.truth = Path(cls.folder.name) / "truth.musicxml"
        write_lindenbaum(cls.truth)

    @classmethod
    def tearDownClass(cls):
        cls.folder.cleanup()

    def test_identical_scores_have_no_error_and_every_marking(self):
        row = score_item(self.truth, self.truth)
        self.assertEqual(row["omr_ned"], 0.0)
        self.assertEqual(row["omr_ned_notes"], 0.0)
        self.assertGreater(row["dynamics_expected"], 0)
        self.assertEqual(row["dynamics_found"], row["dynamics_expected"])
        self.assertEqual(row["lyrics_found"], row["lyrics_expected"])

    def test_wrong_pitches_and_lost_dynamics_are_counted(self):
        wrong = Path(self.folder.name) / "wrong.musicxml"
        score = converter.parse(self.truth)
        for note in list(score.recurse().notes)[:6]:
            note.transpose(2, inPlace=True)
        for dynamic in list(score.recurse().getElementsByClass(dynamics.Dynamic)):
            dynamic.activeSite.remove(dynamic)
        score.write("musicxml", fp=str(wrong))
        row = score_item(wrong, self.truth)
        self.assertGreater(row["omr_ned_notes"], 0.0)
        self.assertGreater(row["omr_ned"], 0.0)
        self.assertEqual(row["dynamics_found"], 0)
        self.assertEqual(row["lyrics_found"], row["lyrics_expected"])

    def test_missing_output_scores_as_nothing_right(self):
        row = score_item(None, self.truth)
        self.assertEqual(row["omr_ned"], 1.0)
        self.assertEqual(row["dynamics_found"], 0)


class RunnerTest(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        root = Path(self.folder.name)
        self.image = root / "page.png"
        self.image.write_bytes(b"not really an image")
        self.item = Item("page-1", "page-1", "clean", "piano", self.image, None, root / "truth.musicxml")
        self.out = root / "out"

    def tearDown(self):
        self.folder.cleanup()

    def engine(self, script, **options):
        return Engine(name="stand-in", command=[sys.executable, "-c", script, "{image}"], **options)

    def test_file_output_is_kept_under_the_page_name(self):
        script = "import sys, pathlib; p = pathlib.Path(sys.argv[1]); p.with_suffix('.musicxml').write_text('<score/>')"
        result = run(self.engine(script, output="*.musicxml"), self.item, self.out)
        self.assertTrue(result.ok, result.error)
        self.assertEqual(result.output.name, "page-1.musicxml")
        self.assertEqual(result.output.read_text(), "<score/>")

    def test_printed_kern_drops_progress_lines(self):
        script = "print('loading weights'); print('**kern'); print('4c'); print('*-')"
        result = run(self.engine(script, suffix=".krn", extract="kern"), self.item, self.out)
        self.assertTrue(result.ok, result.error)
        self.assertEqual(result.output.read_text(), "**kern\n4c\n*-\n")

    def test_a_crashing_reader_is_recorded_not_raised(self):
        result = run(self.engine("raise SystemExit(3)"), self.item, self.out)
        self.assertFalse(result.ok)
        self.assertIn("exit 3", result.error)

    def test_a_reader_that_writes_nothing_fails(self):
        result = run(self.engine("pass", output="*.mxl"), self.item, self.out)
        self.assertFalse(result.ok)
        self.assertIn("wrote no file", result.error)

    def test_abc_starts_at_the_tune_header(self):
        self.assertEqual(extract_music("step 1\nX:1\nK:C\nC", "abc"), "X:1\nK:C\nC\n")
        self.assertEqual(extract_music("no music here", "kern"), "")


class SetTest(unittest.TestCase):
    def test_photos_join_the_set_with_the_clean_page_answer(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "photos").mkdir()
            (root / "photos" / "bach.jpg").write_bytes(b"")
            (root / "photos" / "notes.txt").write_text("")
            (root / "manifest.csv").write_text(
                "id,kind,texture,image,pdf,truth,bars\n"
                "bach,clean,piano,pages/bach.png,pages/bach.pdf,truth/bach.musicxml,4\n"
                "haydn,clean,quartet,pages/haydn.png,,truth/haydn.musicxml,4\n")
            items = load_items(root)
        self.assertEqual([item.key for item in items], ["bach", "bach.photo", "haydn"])
        self.assertEqual(items[1].truth, items[0].truth)
        self.assertEqual(items[1].kind, "photo")
        self.assertIsNone(items[2].pdf)


if __name__ == "__main__":
    unittest.main()
