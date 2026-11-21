"""The ten cases of 2026-11-08 for bubbles, grey drafts and translation timing, run through the real RemoteEngine with scripted events.

Rules that must hold:
 R1 a grey draft and the line that confirms it name the same bubble (the only exception: a speaker change marked late);
 R2 a bubble keeps its id; a new bubble's id is reserved when its first draft appears;
 R3 a dropped line or a cleared draft leaves no trace in the grouping;
 R4 a bubble's translation is not sent while a draft is growing in it.
"""
import time
import unittest

import events
import remote
import translate
import tuning


VOCAB = "alpha bravo charlie delta echo foxtrot golf hotel india juliet kilo lima mike november oscar papa quebec romeo sierra tango uniform victor whiskey xray yankee zulu".split()


def words(n, first="Word"):
    # varied words: the app's repeat filter would cut "word word word"
    return " ".join([first] + [VOCAB[i % len(VOCAB)] + ("s" * (i // len(VOCAB))) for i in range(n - 1)]) + "."


class Rig(unittest.TestCase):
    def setUp(self):
        tuning.reset("all")
        self.out = []
        self.engine = remote.RemoteEngine(settings=events.Settings(), emit=self.out.append)
        self.engine.translator = None
        self.engine.state = "running"

    def draft(self, text, gap=0.3, turn=False, source="SYSTEM", lang="en"):
        self.engine.submit_line({"partial": True, "source": source, "lang": lang, "text": text, "gap": gap, "turn": turn})
        return [e for e in self.out if e["type"] == "partial" and not e.get("clear")][-1]

    def line(self, text, gap=0.3, turn=False, source="SYSTEM", lang="en", level=0.5):
        n = len([e for e in self.out if e["type"] == "line"])
        self.engine.submit_line({"source": source, "lang": lang, "text": text, "gap": gap, "turn": turn, "level": level, "language_share": 1})
        new = [e for e in self.out if e["type"] == "line"]
        return new[-1] if len(new) > n else None

    def clear(self, source="SYSTEM"):
        self.engine.submit_line({"partial": True, "source": source, "clear": True})


class Cases(Rig):
    def test_1_join_the_open_bubble(self):
        a = self.line(words(10))
        d = self.draft("Next")
        self.assertEqual((d["bubble"], d["new"]), (a["bubble"], False))
        self.assertEqual(self.draft("Next sentence is longer now")["bubble"], a["bubble"])
        self.assertEqual(self.line("Next sentence is longer now.")["bubble"], a["bubble"])        # R1

    def test_2_new_bubble_decided_at_the_first_draft(self):
        for name, first, gap, lang in (("long previous", words(30), 0.3, "en"), ("long pause", words(5), 3.0, "en"), ("question", "Is it right?", 1.2, "en"), ("language", words(5), 0.3, "ko")):
            with self.subTest(name):
                self.setUp()
                a = self.line(first)
                d = self.draft("Another sentence" if lang == "en" else "안녕하세요", gap=gap, lang=lang)
                self.assertTrue(d["new"])
                self.assertNotEqual(d["bubble"], a["bubble"])
                d2 = self.draft("Another sentence goes on and on", gap=gap, lang=lang)
                self.assertEqual(d2["bubble"], d["bubble"])                                   # R2
                final = self.line("Another sentence goes on and on." if lang == "en" else "안녕하세요 반갑습니다.", gap=gap, lang=lang)
                self.assertEqual(final["bubble"], d["bubble"])                                # R1

    def test_3_cut_mid_sentence_continues(self):
        a = self.line("He will help to develop and to " + " ".join(["more"] * 40))
        self.assertEqual(self.draft("deliver")["bubble"], a["bubble"])
        self.assertEqual(self.line("deliver those goals.")["bubble"], a["bubble"])

    def test_4_draft_text_changes_wholesale(self):
        self.line(words(30))
        ids = {self.draft(t)["bubble"] for t in ("Mister", "Mr. Smith said that", "Mistress", "Totally different words")}
        self.assertEqual(len(ids), 1)                                                         # R2

    def test_5_draft_cleared_then_a_new_decision(self):
        a = self.line(words(30))
        d = self.draft("Hmm")
        self.clear()
        d2 = self.draft("Real words now")
        self.assertTrue(d["new"] and d2["new"])
        self.assertNotEqual(d2["bubble"], a["bubble"])
        self.assertEqual(self.line("Real words now.")["bubble"], d2["bubble"])

    def test_6_dropped_line_leaves_the_draft_place(self):
        a = self.line(words(30))
        d = self.draft("Maybe music")
        self.assertIsNone(self.line("[BLANK_AUDIO]"))                                         # filtered
        self.assertEqual(self.draft("Real words")["bubble"], d["bubble"])                      # R3
        self.assertEqual(self.line("Real words.")["bubble"], d["bubble"])

    def test_7_speaker_change_marked_late(self):
        a = self.line(words(10))
        d = self.draft("Yes I agree")
        self.assertEqual(d["bubble"], a["bubble"])
        d2 = self.draft("Yes I agree with you", turn=True)
        self.assertTrue(d2["new"])
        self.assertNotEqual(d2["bubble"], a["bubble"])
        self.assertEqual(self.line("Yes I agree with you.", turn=True)["bubble"], d2["bubble"])

    def test_8_other_source_closes_the_bubble(self):
        a = self.line(words(10))
        self.line("My own words here.", source="MIC", level=0.9)
        d = self.draft("Back again")
        self.assertTrue(d["new"])
        self.assertNotEqual(d["bubble"], a["bubble"])
        self.assertEqual(self.line("Back again.")["bubble"], d["bubble"])

    def test_9_several_sentences_in_one_pass(self):
        self.line(words(10))
        d = self.draft("One two")
        first = self.line("One two three.")
        second = self.line("Four five six.")                  # same pass: decided by the rules, bubble now 13 words
        self.assertEqual(first["bubble"], d["bubble"])
        self.assertEqual(second["bubble"], first["bubble"])
        d2 = self.draft("Tail of the next")                    # the draft after: decided again from the updated bubble
        self.assertEqual(d2["bubble"], first["bubble"])
        big = self.line(words(20, "Big"))
        self.assertEqual(big["bubble"], first["bubble"])       # 16 < 25: joins; now 36 words
        d3 = self.draft("Tail")
        self.assertTrue(d3["new"])                             # the bubble is full: the next draft starts a new one

    def test_10_lines_only_replay(self):
        ids = [self.line(words(10))["bubble"] for _ in range(4)]
        self.assertEqual(ids[0], ids[1]); self.assertEqual(ids[1], ids[2]); self.assertNotEqual(ids[2], ids[3])   # 10,20,30 -> full -> new

    def test_bubble_id_is_stable_for_a_row(self):
        a = self.line(words(10))
        for _ in range(3):
            self.assertEqual(self.draft("More")["bubble"], a["bubble"])


class AnyLanguage(Rig):
    """The developer switch "any_language": lines that are not English or Korean are kept, labelled, and translated to Korean."""

    ZH = "现在北极正在发生一些二十年前无法想象的事情。"

    def zh_line(self, text=None, share=0.0, **kw):
        return self.engine_line(text or self.ZH, share, **kw)

    def engine_line(self, text, share, gap=0.3, no_speech=None, logprob=None):
        n = len([e for e in self.out if e["type"] == "line"])
        body = {"source": "SYSTEM", "lang": "en", "text": text, "gap": gap, "level": 0.5, "language_share": share}
        if no_speech is not None:
            body.update({"no_speech_prob": no_speech, "avg_logprob": logprob})
        self.engine.submit_line(body)
        new = [e for e in self.out if e["type"] == "line"]
        return new[-1] if len(new) > n else None

    def test_off_drops_a_chinese_line(self):
        self.assertIsNone(self.zh_line())                                    # as before: neither English nor Korean

    def test_on_keeps_it_labelled_and_in_its_own_bubble(self):
        tuning.apply({"any_language": True})
        a = self.line(words(8))
        z = self.zh_line()
        self.assertEqual((z["lang"], z["script"]), ("en", "ZH"))              # "en": it is translated to Korean like English
        self.assertNotEqual(z["bubble"], a["bubble"])
        e = self.line("And back in English now.")
        self.assertNotEqual(e["bubble"], z["bubble"])
        self.assertNotIn("script", e)

    def test_on_draft_and_line_share_the_bubble(self):
        tuning.apply({"any_language": True})
        self.line(words(8))
        d = self.draft("现在北极", lang="en")
        self.assertTrue(d["new"])
        d2 = self.draft("现在北极正在发生", lang="en")
        self.assertEqual(d2["bubble"], d["bubble"])
        self.assertEqual(d2["script"], "ZH")
        self.assertEqual(self.zh_line()["bubble"], d["bubble"])               # R1 again, for another script

    def test_on_other_scripts(self):
        tuning.apply({"any_language": True})
        self.assertEqual(self.zh_line("Я подчеркну, Россия никогда никому не угрожала.")["script"], "RU")
        self.assertEqual(self.zh_line("これは日本語の文です。")["script"], "JA")

    def test_on_noise_filters_still_work(self):
        tuning.apply({"any_language": True})
        self.assertIsNone(self.zh_line(no_speech=0.9, logprob=-1.5))          # sure it is not speech: dropped in any language

    def test_unpunctuated_chinese_does_not_pile_into_one_bubble(self):
        """2026-11-21: Whisper writes Chinese without a full stop, so every line looked "cut" and all joined one bubble for minutes."""
        tuning.apply({"any_language": True})
        lines = ["保持密切交往", "有意日益深厚", "共同引领美中关系发展", "两国贸易投资关系不断加强", "芬泰尼等领域合作取得成效",
                 "双方应保持美中关系稳定发展势头", "在农产品能源超级智能等领域加强合作", "公平处理好各自关切",
                 "亚太经合组织始终把握时代脉搏", "引领亚太经济一体化进程", "助力亚太成为全球经济最具活力的地区", "中方担任今年亚太经合组织东道主以来"]
        ids = [self.zh_line(t)["bubble"] for t in lines]
        groups = sorted(set(ids))
        self.assertGreaterEqual(len(groups), 3)                                  # several bubbles, not one
        for g in groups:
            chars = sum(len(t) for t, i in zip(lines, ids) if i == g)
            self.assertLessEqual(chars, 70)                                      # about 25 English words is 40 characters

    def test_chinese_translation_is_not_held_like_a_cut_sentence(self):
        import translate
        self.assertTrue(translate.ends_sentence("保持密切交往"))                    # no punctuation, but the app ended the line
        self.assertTrue(translate.ends_sentence("Привет, как дела"))
        self.assertFalse(translate.ends_sentence("He will help to develop and to")) # English unchanged
        self.assertFalse(translate.ends_sentence("then we"))

    def test_on_korean_and_english_are_unchanged(self):
        tuning.apply({"any_language": True})
        k = self.line("안녕하세요 여러분 반갑습니다.", lang="ko")
        self.assertNotIn("script", k)
        self.assertEqual(self.line(words(5))["lang"], "en")


class TranslationWaitsForTheDraft(unittest.TestCase):
    def test_hold(self):
        tuning.reset("all")
        tuning.apply({"translate_settle_seconds": 0.3, "translate_cut_wait_seconds": 1.0})
        calls = []
        orig = translate.translate
        translate.translate = lambda text, *a, **k: calls.append(text) or "KO"
        try:
            t = translate.Translator(lambda e: None)
            t.submit({"id": 1, "bubble": 1, "source": "Them", "lang": "en", "text": "First sentence."})
            for _ in range(4):                  # a draft keeps growing in the same bubble
                time.sleep(0.2)
                t.hold(1)
            self.assertEqual(calls, [])         # R4: still waiting after 0.8 s (settle is 0.3 s)
            time.sleep(1.3)
            self.assertEqual(calls, ["First sentence."])
        finally:
            translate.translate = orig
            tuning.reset("all")


if __name__ == "__main__":
    unittest.main()
