import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from textclean import strip_inline_labels  # noqa: E402


class InlineLabels(unittest.TestCase):
    def test_label_inside_a_line(self):
        self.assertEqual(strip_inline_labels("so [typing] we go"), ("so we go", 1))

    def test_several_kinds(self):
        text = "[ Silence ] okay (laughs) then [BLANK_AUDIO] bye"
        self.assertEqual(strip_inline_labels(text), ("okay then bye", 3))

    def test_korean_brackets(self):
        self.assertEqual(strip_inline_labels("네 （웃음） 그렇죠"), ("네 그렇죠", 1))

    def test_only_a_label_leaves_nothing(self):
        self.assertEqual(strip_inline_labels("[MUSIC]"), ("", 1))

    def test_no_label_is_unchanged(self):
        self.assertEqual(strip_inline_labels("it costs 5 (or so) pounds"), ("it costs 5 pounds", 1))   # a short remark in brackets is also removed
        self.assertEqual(strip_inline_labels("plain text, no brackets."), ("plain text, no brackets.", 0))

    def test_long_remark_is_kept(self):
        long = "(" + "x" * 60 + ")"
        self.assertEqual(strip_inline_labels("a " + long + " b"), ("a " + long + " b", 0))


if __name__ == "__main__":
    unittest.main()
