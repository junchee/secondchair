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
        with self.t.cv:                      # nothing may fire later, in another test, through the patched function
            self.t.pending.clear()
            self.t.waiting.clear()
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

    def test_chinese_test_switch(self):
        seen = []
        translate.translate = lambda text, target, *a, **k: seen.append((target, k.get("previous"))) or "KO"
        tuning.apply({"meeting_language": "en-zh", "translate_settle_seconds": 0})
        self.line(1, 1, "First sentence.")
        time.sleep(0.2)
        self.assertEqual(seen[0][0], "Simplified Chinese")
        self.assertIn("Simplified Chinese characters", translate.build_request("x", translate.CHINESE)["messages"][0]["content"])
        self.assertNotIn("English = Korean", translate.build_request("x", translate.CHINESE)["messages"][0]["content"])
        tuning.apply({"meeting_language": "en-ko"})
        self.assertEqual(translate.target_for("en"), "Korean")
        self.assertEqual(translate.target_for("ko"), "English")   # my Korean still goes to English

    def test_meeting_language_targets(self):
        """What each meeting language translates a line into (None: already the language wanted, nothing is shown)."""
        zh, ru = "我没办法按时赶到医院了。", "Спасибо большое."
        table = {
            "en-ko": [("en", "Hello there.", "Korean"), ("ko", "안녕하세요.", "English"), ("en", zh, "Korean")],
            "en-zh": [("en", "Hello there.", translate.CHINESE), ("en", zh, "English"), ("ko", "안녕하세요.", "English"),
                      ("en", ru, "English")],
            "any-ko": [("en", "Hello there.", "Korean"), ("en", zh, "Korean"), ("ko", "안녕하세요.", "English"),
                       ("en", ru, "Korean")],
            "any-zh": [("en", "Hello there.", translate.CHINESE), ("en", zh, None), ("ko", "안녕하세요.", translate.CHINESE),
                       ("en", ru, translate.CHINESE)],
        }
        for mode, rows in table.items():
            tuning.apply({"meeting_language": mode})
            for lang, text, want in rows:
                self.assertEqual(translate.target_for(lang, text), want, (mode, text))
        tuning.apply({"meeting_language": "nonsense"})      # a bad value changes nothing
        self.assertEqual(tuning.get("meeting_language"), "any-zh")

    def test_a_line_already_in_the_target_language_shows_no_translation(self):
        tuning.apply({"meeting_language": "any-zh", "translate_settle_seconds": 0})
        self.t.submit({"id": 1, "bubble": 1, "source": "Them", "lang": "en", "text": "我没办法按时赶到医院了。", "script": "ZH"})
        time.sleep(0.2)
        self.assertEqual(self.fake.calls, [])                # no model call
        self.assertEqual([e["text"] for e in self.done()], [""])   # the page hides the empty slot

    def test_flush_translates_waiting_bubble(self):
        self.line(1, 1, "Last words.")
        self.t.flush()
        time.sleep(0.15)
        self.assertEqual([c[0] for c in self.fake.calls], ["Last words."])


if __name__ == "__main__":
    unittest.main()
