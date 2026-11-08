"""Translator: a growing bubble is translated once it settles, a new bubble releases the earlier one, no streaming."""
import time
import unittest

import translate
import tuning


class Fake:
    def __init__(self):
        self.calls = []

    def __call__(self, text, target, context, _x, client, on_text=None, model=None, previous=None):
        self.calls.append((text, on_text is not None))
        return "KO:" + text


class Settle(unittest.TestCase):
    def setUp(self):
        self.fake = Fake()
        self._orig = translate.translate
        translate.translate = self.fake
        self.events = []
        self.t = translate.Translator(self.events.append)
        tuning.apply({"translate_settle_seconds": 0.3, "translate_cut_wait_seconds": 1.0})

    def tearDown(self):
        translate.translate = self._orig
        tuning.reset("all")

    def line(self, i, bubble, text):
        self.t.submit({"id": i, "bubble": bubble, "source": "Them", "lang": "en", "text": text})

    def done(self):
        return [e for e in self.events if e["type"] == "translation"]

    def test_growing_bubble_is_translated_once(self):
        self.line(1, 1, "First sentence.")
        self.line(2, 1, "Second sentence.")
        time.sleep(0.2)
        self.assertEqual(self.fake.calls, [])                    # still settling
        time.sleep(0.5)
        self.assertEqual(self.fake.calls, [("First sentence. Second sentence.", False)])   # once, whole, not streamed
        self.assertEqual(len(self.done()), 1)

    def test_new_bubble_releases_the_earlier_one_at_once(self):
        self.line(1, 1, "First sentence.")
        self.line(2, 2, "Next speaker.")
        time.sleep(0.15)
        self.assertEqual([c[0] for c in self.fake.calls], ["First sentence."])

    def test_cut_sentence_waits_longer(self):
        self.line(1, 1, "He will help to develop and to")
        time.sleep(0.6)
        self.assertEqual(self.fake.calls, [])
        self.line(2, 1, "deliver those goals.")
        time.sleep(0.6)
        self.assertEqual([c[0] for c in self.fake.calls], ["He will help to develop and to deliver those goals."])

    def test_flush_translates_waiting_bubble(self):
        self.line(1, 1, "Last words.")
        self.t.flush()
        time.sleep(0.15)
        self.assertEqual([c[0] for c in self.fake.calls], ["Last words."])


if __name__ == "__main__":
    unittest.main()
