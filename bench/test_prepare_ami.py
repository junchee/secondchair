import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(__file__))
import prepare_ami as P  # noqa: E402
from score_text import score, tokens  # noqa: E402

NS = 'xmlns:nite="http://nite.sourceforge.net/"'


def xml(items):
    """items: (text, start, end) for a word, (".", None, None) for punctuation, ("uh", s, e, 'trunc') etc."""
    rows = []
    for i, it in enumerate(items):
        text, start, end = it[0], it[1], it[2]
        extra = ' trunc="true"' if len(it) > 3 and it[3] == "trunc" else ""
        if start is None:
            rows.append(f'<w nite:id="m.A.words{i}" punc="true">{text}</w>')
        else:
            rows.append(f'<w nite:id="m.A.words{i}" starttime="{start}" endtime="{end}"{extra}>{text}</w>')
    rows.insert(1, "<vocalsound nite:id=\"v\" starttime=\"0.0\" endtime=\"0.1\" type=\"laugh\"/>")
    return f'<?xml version="1.0"?><nite:root {NS}>' + "".join(rows) + "</nite:root>"


def write(dirpath, name, items):
    with open(os.path.join(dirpath, name), "w") as f:
        f.write(xml(items))


class Reading(unittest.TestCase):
    def test_read_skips_fillers_truncated_and_sounds(self):
        with tempfile.TemporaryDirectory() as d:
            write(d, "m.A.words.xml", [("Okay", 0.0, 0.4), ("uh", 0.5, 0.6), ("wh-", 0.7, 0.8, "trunc"),
                                       ("we", 0.9, 1.0), (".", None, None)])
            ws = P.read_words_xml(os.path.join(d, "m.A.words.xml"), "A")
            self.assertEqual([w["w"] for w in ws], ["Okay", "we", "."])
            self.assertTrue(ws[-1]["punc"])
            kept = P.read_words_xml(os.path.join(d, "m.A.words.xml"), "A", keep_fillers=True)
            self.assertIn("uh", [w["w"] for w in kept])


class Merging(unittest.TestCase):
    def two_speakers(self):
        with tempfile.TemporaryDirectory() as d:
            write(d, "m.A.words.xml", [("Hello", 0.0, 0.5), ("there", 0.5, 1.0), (".", None, None),
                                       ("Fine", 6.0, 6.5), ("thanks", 6.5, 7.0), ("Smith", 7.0, 7.5), (".", None, None)])
            write(d, "m.B.words.xml", [("Hi", 2.0, 2.3), ("Paul", 2.3, 2.8), ("?", None, None),
                                       ("Yes", 3.0, 3.5)])   # no end mark
            return {s: P.read_words_xml(os.path.join(d, f"m.{s}.words.xml"), s) for s in "AB"}

    def test_order_ends_and_key(self):
        m = P.build_meeting(self.two_speakers())
        self.assertEqual([w["w"] for w in m["words"]],
                         ["Hello", "there", "Hi", "Paul", "Yes", "Fine", "thanks", "Smith"])
        self.assertEqual(m["ends"], [1, 3, 4, 7])      # B's "Yes" has no mark but ends its run
        self.assertEqual([m["words"][i]["w"] for i in m["key"]], ["Paul", "Smith"])   # names inside a sentence

    def test_key_numbers_and_long_words(self):
        words = [{"w": w} for w in ["It", "costs", "500", "for", "reconsideration", "."]][:5]
        self.assertEqual(P.key_items(words, [4]), [2, 4])

    def test_sentence_start_capital_is_not_a_key(self):
        words = [{"w": w} for w in ["Hello", "there", "Today", "is", "fine"]]
        self.assertEqual(P.key_items(words, [1, 4]), [])


class Cutting(unittest.TestCase):
    def meeting(self):
        words, ends = [], []
        t = 0.0
        for s in range(10):                      # 10 sentences of 3 words, 3 s each word -> 9 s per sentence
            for k in range(3):
                words.append({"w": f"w{s}x{k}", "start": t, "end": t + 3.0, "spk": "A"})
                t += 3.0
            ends.append(len(words) - 1)
        return {"words": words, "ends": ends, "key": [4, 29]}

    def test_cut_at_sentence_ends(self):
        cuts = P.make_cuts(self.meeting(), cut_seconds=30.0)
        self.assertEqual([len(c["words"]) for c in cuts], [12, 12, 6])      # first end at or after 30 s: 36 s
        self.assertEqual(cuts[0]["ends"], [2, 5, 8, 11])
        self.assertEqual(sum(len(c["words"]) for c in cuts), 30)
        self.assertEqual(cuts[0]["key"], [4])
        self.assertEqual(cuts[2]["key"], [5])                                # word 29 is index 5 of the last piece
        self.assertTrue(all(c["ends"][-1] == len(c["words"]) - 1 for c in cuts))

    def test_short_meeting_is_one_piece(self):
        cuts = P.make_cuts(self.meeting(), cut_seconds=3000.0)
        self.assertEqual(len(cuts), 1)
        self.assertEqual(len(cuts[0]["words"]), 30)

    def test_piece_text_one_sentence_per_line(self):
        c = P.make_cuts(self.meeting(), cut_seconds=30.0)[0]
        lines = P.piece_text(c).strip().split("\n")
        self.assertEqual(len(lines), 4)
        self.assertEqual(lines[0], "w0x0 w0x1 w0x2")


class EndToEnd(unittest.TestCase):
    def test_prepare_writes_files_and_text_scores_perfectly_against_itself(self):
        with tempfile.TemporaryDirectory() as d:
            sub = os.path.join(d, "words")
            os.makedirs(sub)
            write(sub, "ES1.A.words.xml", [("We", 0.0, 0.3), ("meet", 0.3, 0.6), ("Paul", 0.6, 1.0), (".", None, None),
                                           ("Costs", 5.0, 5.4), ("500", 5.4, 5.9), (".", None, None)])
            write(sub, "ES1.B.words.xml", [("Right", 2.0, 2.4), (".", None, None)])
            manifest = P.prepare(d, cut_seconds=1.0)   # sentence ends at 1.0, 2.4, 5.9 s -> pieces end at 1.0 and 5.9
            self.assertEqual(len(manifest), 2)
            self.assertTrue(os.path.exists(os.path.join(d, "prepared", "manifest.json")))
            ref = json.load(open(os.path.join(d, "prepared", "ES1.ref.json")))
            self.assertEqual([w["w"] for w in ref["words"]], ["We", "meet", "Paul", "Right", "Costs", "500"])
            text = open(os.path.join(d, "prepared", "ES1.cut01.txt")).read()
            self.assertEqual(score(tokens(text), tokens(text))["MER"], 0)

    def test_no_files_exits(self):
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(SystemExit):
                P.prepare(d)


if __name__ == "__main__":
    unittest.main()
