import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(__file__))
from score_text import align, score, tokens, tokens_with_ends  # noqa: E402


class Tokens(unittest.TestCase):
    def test_english(self):
        self.assertEqual(tokens("Hello, World! It's 3.5 o’clock."), ["hello", "world", "it's", "3", "5", "o'clock"])

    def test_korean_by_character(self):
        self.assertEqual(tokens("파기 환송!"), ["파", "기", "환", "송"])

    def test_mixed(self):
        self.assertEqual(tokens("Anne은 good"), ["anne", "은", "good"])

    def test_ends(self):
        words, ends = tokens_with_ends("One two. Three? Four five six")
        self.assertEqual(words, ["one", "two", "three", "four", "five", "six"])
        self.assertEqual(ends, [1, 2, 5])

    def test_decimal_point_is_not_an_end(self):
        _, ends = tokens_with_ends("It costs 3.5 pounds. Done.")
        self.assertEqual(ends, [4, 5])


class Scoring(unittest.TestCase):
    def test_identical(self):
        r = score(["a", "b", "c"], ["a", "b", "c"])
        self.assertEqual((r["S"], r["D"], r["I"], r["MER"]), (0, 0, 0, 0))

    def test_one_of_each(self):
        ref = "the quick brown fox jumps".split()
        hyp = "the quick red fox jumps over".split()   # brown->red (S), over inserted (I)
        r = score(ref, hyp)
        self.assertEqual((r["S"], r["D"], r["I"]), (1, 0, 1))
        self.assertAlmostEqual(r["MER"], 2 / 5)
        self.assertAlmostEqual(r["Wrong"], 1 / 5)
        self.assertAlmostEqual(r["Invented"], 1 / 5)

    def test_missing(self):
        r = score("a b c d".split(), "a d".split())
        self.assertEqual((r["S"], r["D"], r["I"]), (0, 2, 0))
        self.assertAlmostEqual(r["Missing"], 0.5)

    def test_empty_hyp(self):
        r = score("a b".split(), [])
        self.assertEqual(r["D"], 2)
        self.assertAlmostEqual(r["MER"], 1.0)

    def test_empty_ref_does_not_divide_by_zero(self):
        r = score([], ["x"])
        self.assertEqual(r["I"], 1)

    def test_korean_characters(self):
        r = score(tokens("파기환송"), tokens("파기환승"))
        self.assertEqual((r["S"], r["N"]), (1, 4))

    def test_key(self):
        ref = "we pay 500 pounds to smith".split()
        hyp = "we pay 50 pounds to smyth".split()
        r = score(ref, hyp, key=[2, 3, 5])
        self.assertAlmostEqual(r["Key"], 1 / 3)       # only "pounds" is right

    def test_key_none_when_not_given(self):
        self.assertIsNone(score(["a"], ["a"])["Key"])

    def test_align_ops(self):
        ops = align(["a", "b"], ["a", "c", "b"])
        self.assertEqual([o for o, _, _ in ops], ["M", "I", "M"])

    def test_sentence_f1_perfect(self):
        ref, re_ = tokens_with_ends("One two three. Four five six.")
        r = score(ref, ref, ref_ends=re_, hyp_ends=re_)
        self.assertAlmostEqual(r["SentF1"], 1.0)

    def test_sentence_f1_missed_end(self):
        ref, re_ = tokens_with_ends("One two three. Four five six. Seven eight nine.")
        hyp, he_ = tokens_with_ends("One two three. Four five six Seven eight nine.")
        r = score(ref, hyp, ref_ends=re_, hyp_ends=he_)
        # the only inner end found is 1 of 2 -> precision 1, recall 0.5
        self.assertAlmostEqual(r["SentF1"], 2 / 3)

    def test_sentence_f1_extra_end(self):
        ref, re_ = tokens_with_ends("One two three four five six.")
        hyp, he_ = tokens_with_ends("One two three. Four five six.")
        r = score(ref, hyp, ref_ends=re_, hyp_ends=he_)
        self.assertAlmostEqual(r["SentF1"], 0.0)

    def test_sentence_f1_tolerance(self):
        ref, re_ = tokens_with_ends("One two three. Four five six.")
        hyp, he_ = tokens_with_ends("One two. Three four five six.")   # end one word early
        self.assertAlmostEqual(score(ref, hyp, ref_ends=re_, hyp_ends=he_, tol=1)["SentF1"], 1.0)
        self.assertAlmostEqual(score(ref, hyp, ref_ends=re_, hyp_ends=he_, tol=0)["SentF1"], 0.0)


if __name__ == "__main__":
    unittest.main()
