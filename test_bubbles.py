"""Bubble grouping for lines from Anne.app (gap given): size guide in words, question + pause = new bubble."""
import unittest

import bubbles
import tuning

HOST = [
    "less than his 2024 win of about 33 and a half points.",
    "And in the days since, Congressman Stutzman has been blunt about what his party should do and how the White House should respond.",
    "Indiana's Congressman Marlin Stutzman joins me now live.",
    "Congressman, thank you so much for being here this morning.",
    "I really appreciate you joining me.",
    "As you know, there's a lot of debate about what went wrong for the GOP in last week's election and how the party and your party should respond to the message sent by the electorate.",
    "So given that, was it the right move for President Trump to name Stephen Miller as his new chief of staff?",
]
GUEST = [
    "Good morning, Matthew.",
    "Great to be with you this morning.",
    "You know, first of all, we need to admit that we got beat, and we got beat badly.",
    "We need to listen to the American people.",
    "As you mentioned, my numbers in Northeast Indiana, I've never seen numbers that bad.",
    "And, you know, as I'm talking to constituents, they said, you guys aren't listening.",
    "You're not paying attention.",
    "And that's what we as Republicans need to do.",
]


def feed(sentences_and_gaps, source="Them", turns=()):
    g = bubbles.Grouper()
    ids = []
    for i, (text, gap) in enumerate(sentences_and_gaps):
        ids.append(g.assign({"id": i + 1, "source": source, "lang": "en", "text": text, "gap": gap, "turn": i in turns}))
    return ids


class BubbleSize(unittest.TestCase):
    def test_short_sentences_are_gathered(self):
        ids = feed([("Good morning, Matthew.", 0.4), ("Great to be with you this morning.", 0.4), ("We need to listen.", 0.4)])
        self.assertEqual(len(set(ids)), 1)

    def test_target_reached_starts_a_new_bubble(self):
        s = "One two three four five six seven eight nine ten."          # 10 words
        ids = feed([(s, 0.3)] * 5)                                         # 10, 20, 30 -> full; then new
        self.assertEqual(ids, [1, 1, 1, 4, 4])

    def test_decided_by_the_open_bubble_only(self):
        # a 24-word bubble still takes the next sentence, however long (the grey draft must not move between bubbles)
        a = " ".join(["Word"] * 24) + "."
        b = " ".join(["Word"] * 30) + "."
        self.assertEqual(feed([(a, 0.3), (b, 0.3), ("Next.", 0.3)]), [1, 1, 3])

    def test_long_sentence_stays_whole(self):
        long = " ".join(["Word"] * 60) + "."
        ids = feed([(long, 0.3), ("Short one.", 0.3)])
        self.assertEqual(ids, [1, 2])                                      # not cut, and the next one starts fresh

    def test_long_pause_starts_a_new_bubble(self):
        self.assertEqual(feed([("Hello there.", 0.3), ("Hello again.", 3.0)]), [1, 2])

    def test_question_and_pause_is_a_new_bubble(self):
        self.assertEqual(feed([("Is it right?", 0.3), ("Yes it is.", 1.2)]), [1, 2])
        self.assertEqual(feed([("Is it right?", 0.3), ("Yes it is.", 0.4)]), [1, 1])   # quick follow-up stays

    def test_sentence_cut_by_the_app_is_never_split(self):
        w = " ".join(["Word"] * 40)
        # the first line is 40 words but stops in the middle of a sentence: the rest joins it, however long
        ids = feed([("You should have watched television. " + w + " and to", 0.3), ("deliver those goals.", 0.3), ("Next sentence here.", 0.3)])
        self.assertEqual(ids, [1, 1, 3])
        ids = feed([("It was said " + w + ".", 0.3), ("Another.", 0.3)])      # full stop at 43 words, no cut: a new bubble follows
        self.assertEqual(ids, [1, 2])

    def test_grey_draft_goes_where_the_final_line_goes(self):
        g = bubbles.Grouper()
        g.assign({"id": 1, "source": "Them", "lang": "en", "text": " ".join(["Word"] * 20) + ".", "gap": 0.3})
        for draft in ("Next", "Next sentence is", "Next sentence is getting very long and keeps going"):
            self.assertEqual(g.peek("Them", draft, "en", 0.3), 1)           # the draft stays in the open bubble
        final = " ".join(["Next"] * 40) + "."
        self.assertEqual(g.assign({"id": 2, "source": "Them", "lang": "en", "text": final, "gap": 0.3}), 1)   # and so does the final line

    def test_speaker_change_and_return(self):
        g = bubbles.Grouper()
        a = g.assign({"id": 1, "source": "Them", "lang": "en", "text": "Hello.", "gap": 0.3})
        b = g.assign({"id": 2, "source": "MIC", "lang": "en", "text": "Hi.", "gap": 0.3})
        c = g.assign({"id": 3, "source": "Them", "lang": "en", "text": "Back again.", "gap": 0.3})
        self.assertEqual((a, b, c), (1, 2, 3))

    def test_whisper_turn_mark(self):
        self.assertEqual(feed([("One.", 0.3), ("Two.", 0.3)], turns={1}), [1, 2])

    def test_interview_transcript(self):
        lines = [(t, 0.4) for t in HOST] + [(GUEST[0], 1.3)] + [(t, 0.4) for t in GUEST[1:]]
        ids = feed(lines)
        groups = []
        for i in ids:
            if i not in groups:
                groups.append(i)
        print("bubbles:", len(groups), [ids.count(i) for i in groups])
        self.assertEqual(ids[len(HOST) - 1] != ids[len(HOST)], True)         # the answer is not in the question's bubble
        self.assertLessEqual(len(groups), 9)


if __name__ == "__main__":
    unittest.main()
