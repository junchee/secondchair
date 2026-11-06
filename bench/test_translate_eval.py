"""Tests for bench/translate_eval.py and bench/llm.py. No network, no key, no paid call: a fake client only.
Run: cd bench && python3 -m unittest discover"""

import contextlib
import io
import json
import os
import tempfile
import unittest
from unittest import mock

import llm
import translate_eval as te


def word(w, start, end, spk="A"):
    return {"w": w, "start": start, "end": end, "spk": spk}


def made_up_piece():
    """Three sentences. Sentence 2 joins two utterances across a 9 s gap ("so then" ... "Okay we go")."""
    words = [word("we", 0.0, 0.3), word("need", 0.3, 0.6), word("a", 0.6, 0.7), word("T_V_", 0.7, 1.2), word("remote", 1.2, 1.8),
             word("so", 2.0, 2.3), word("then", 2.3, 2.6), word("Okay", 11.6, 12.0), word("we", 12.0, 12.2), word("go", 12.2, 12.5),
             word("Yeah", 13.0, 13.3, "B")]
    return {"meeting": "XX", "cut": 1, "start": 0.0, "end": 13.3, "words": words, "ends": [4, 9, 10], "key": [3, 7]}


def write_prepared(directory, piece=None):
    piece = piece or made_up_piece()
    with open(os.path.join(directory, "XX.cut01.json"), "w") as f:
        json.dump(piece, f)
    with open(os.path.join(directory, "manifest.json"), "w") as f:
        json.dump([{"id": "XX.cut01", "meeting": "XX", "start": piece["start"], "end": piece["end"]}], f)


def quiet_main(argv):
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        code = te.main(argv)
    return code, out.getvalue()


class Spoken(unittest.TestCase):
    def test_letters(self):
        words, flags = te.normalise_words(["the", "T_V_", "and", "L_C_D_", "D_V_D_", "I_D_", "card"], [False, True, False, False, False, False, False])
        self.assertEqual(words, ["the", "TV", "and", "LCD", "DVD", "ID", "card"])
        self.assertEqual(flags[1], True)

    def test_t_rex(self):
        words, flags = te.normalise_words(["a", "T_", "Rex", "toy"], [False, False, True, False])
        self.assertEqual(words, ["a", "T-Rex", "toy"])
        self.assertEqual(flags, [False, True, False])

    def test_single_letter_at_end(self):
        self.assertEqual(te.normalise_words(["plan", "T_"])[0], ["plan", "T"])


class Gaps(unittest.TestCase):
    def test_split_at_five_seconds(self):
        times = [(0, 1), (1, 2), (6.9, 7), (7, 8), (13, 14)]
        self.assertEqual(te.split_at_gaps(times, [0, 1, 2, 3, 4]), [[0, 1, 2, 3], [4]])   # 6.9-2 = 4.9 s is not a gap; 13-8 = 5 is
        self.assertEqual(te.split_at_gaps(times, [0, 1, 2, 3, 4], gap=4.5), [[0, 1], [2, 3], [4]])

    def test_sentences_from_piece(self):
        s = te.build_sentences("XX.cut01", made_up_piece())
        self.assertEqual([x["text"] for x in s], ["we need a TV remote", "so then", "Okay we go", "Yeah"])
        self.assertEqual([x["id"] for x in s], ["XX.cut01.S001", "XX.cut01.S002", "XX.cut01.S003", "XX.cut01.S004"])
        self.assertEqual(s[0]["key"], ["TV"])
        self.assertEqual(s[2]["key"], [])         # "Okay" is a restart marker, dropped from the key list only
        self.assertEqual(s[2]["text"].split()[0], "Okay")   # ... and stays in the text
        self.assertEqual(s[3]["spk"], "B")

    def test_backchannel(self):
        self.assertTrue(te.is_bare_backchannel("Mm-hmm"))
        self.assertTrue(te.is_bare_backchannel("Yeah okay"))
        self.assertFalse(te.is_bare_backchannel("Yeah we should do it"))


class AssignAsr(unittest.TestCase):
    sentences = [["we", "need", "a", "TV", "remote"], ["so", "then"], ["Okay", "we", "go"]]

    def test_drop_change_insert(self):
        asr = "We need TV remote so then banana okay we go now".split()
        texts = te.assign_asr(self.sentences, asr)
        self.assertEqual(texts[0], "We need TV remote")           # "a" dropped
        self.assertEqual(texts[1], "so then banana")             # an inserted word goes to the sentence before it
        self.assertEqual(texts[2], "okay we go now")

    def test_insertion_goes_to_previous_sentence(self):
        texts = te.assign_asr([["a", "b"], ["c", "d"]], "a b x c d".split())
        self.assertEqual(texts, ["a b x", "c d"])

    def test_empty_sentence(self):
        texts = te.assign_asr(self.sentences, "we need a TV remote Okay we go".split())
        self.assertEqual(texts[1], "")

    def test_punctuation_stays_with_word_before(self):
        texts = te.assign_asr([["a", "b"], ["c"]], ["A", "b,", "-", "c."])
        self.assertEqual(texts, ["A b, -", "c."])

    def test_json_forms(self):
        self.assertEqual(te._words_from_json({"text": "a b c"}), ["a", "b", "c"])
        self.assertEqual(te._words_from_json({"words": [{"word": "a"}, {"word": "b"}]}), ["a", "b"])
        self.assertEqual(te._words_from_json({"segments": [{"text": "a b"}, {"text": "c"}]}), ["a", "b", "c"])
        self.assertEqual(te._words_from_json(["a b", "c"]), ["a", "b", "c"])


class Parsing(unittest.TestCase):
    def test_parse_json_reply(self):
        self.assertEqual(te.parse_json_reply(' {"a": 1} '), {"a": 1})
        self.assertEqual(te.parse_json_reply('Here it is: {"a": 1} thanks'), {"a": 1})
        self.assertIsNone(te.parse_json_reply("no json"))
        self.assertIsNone(te.parse_json_reply('{"a": '))

    def test_valid_judge(self):
        self.assertIsNone(te.valid_judge({"meaning": "good"}))
        d = te.valid_judge({"meaning": "right"})
        self.assertEqual((d["errors"], d["critical"]), ([], []))


class FakeFlow(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.prepared = os.path.join(self.tmp.name, "prepared")
        os.makedirs(self.prepared)
        write_prepared(self.prepared)
        self.results = os.path.join(self.tmp.name, "results")
        self.addCleanup(self.tmp.cleanup)

    def argv(self, *extra):
        return ["--prepared-dir", self.prepared, "--results-dir", self.results, "--asr-dir", os.path.join(self.tmp.name, "asr"),
                "--fake", "--workers", "1", "--translator", "fake/a", "--budget-usd", "5", *extra]

    def write_asr(self, text, model="stub"):
        os.makedirs(os.path.join(self.tmp.name, "asr", model), exist_ok=True)
        with open(os.path.join(self.tmp.name, "asr", model, "XX.cut01.txt"), "w") as f:
            f.write(text)

    def rows(self, name="r"):
        with open(os.path.join(self.results, name, "rows.jsonl")) as f:
            return [json.loads(line) for line in f]

    def test_run_then_second_run_calls_nothing(self):
        self.write_asr("we need a TV remote so then Okay we go banana")
        code, out = quiet_main(self.argv("--run-name", "r", "--asr-model", "stub"))
        self.assertEqual(code, 0)
        self.assertIn("a. reference Korean", out)
        rows = self.rows()
        self.assertEqual(len(rows), 8)                      # 4 sentences x T0, T1
        self.assertTrue(os.path.exists(os.path.join(self.results, "r", "summary.txt")))
        counted = []
        real = llm.FakeClient.chat

        def counting(self_, body):
            counted.append(1)
            return real(self_, body)

        with mock.patch.object(llm.FakeClient, "chat", counting):
            code, out = quiet_main(self.argv("--run-name", "r", "--asr-model", "stub"))
        self.assertEqual((code, len(counted)), (0, 0))
        self.assertIn("Nothing to call", out)
        self.assertEqual(len(self.rows()), 8)

    def test_t1_marks_empty_asr_sentence(self):
        self.write_asr("we need a TV remote Okay we go Yeah")      # nothing for "so then"
        quiet_main(self.argv("--run-name", "r", "--asr-model", "stub", "--conditions", "T1"))
        rows = {r["sentence"]: r for r in self.rows()}
        empty = rows["XX.cut01.S002"]
        self.assertTrue(empty["asr_empty"])
        self.assertEqual(empty["candidate_ko"], "")
        self.assertEqual(empty["judge"]["meaning"], "wrong")      # an empty candidate for a content sentence
        self.assertFalse(rows["XX.cut01.S001"]["asr_empty"])

    def test_max_seconds(self):
        quiet_main(self.argv("--run-name", "r", "--conditions", "T0", "--max-seconds", "3"))
        self.assertEqual([r["sentence"] for r in self.rows()], ["XX.cut01.S001", "XX.cut01.S002"])

    def test_budget_refusal_makes_no_call(self):
        counted = []
        real = llm.FakeClient.chat
        with mock.patch.object(llm.FakeClient, "chat", lambda s, b: counted.append(1) or real(s, b)):
            code, out = quiet_main(self.argv("--run-name", "r", "--conditions", "T0", "--budget-usd", "0.0000001"))
        self.assertEqual((code, len(counted)), (2, 0))
        self.assertIn("REFUSED", out)

    def test_dry_run_calls_nothing_and_writes_nothing(self):
        code, out = quiet_main(self.argv("--run-name", "r", "--conditions", "T0", "--dry-run"))
        self.assertEqual(code, 0)
        self.assertIn("Plan", out)
        self.assertFalse(os.path.exists(os.path.join(self.results, "r")))

    def test_budget_stops_during_the_run(self):
        # the plan fits, but the real costs are higher than planned, so the limit is hit part-way
        real = llm.FakeClient.chat

        def dear(self_, body):
            reply = real(self_, body)
            reply["usage"]["cost"] = 0.01
            return reply

        with mock.patch.object(llm.FakeClient, "chat", dear):
            code, out = quiet_main(self.argv("--run-name", "r", "--conditions", "T0", "--budget-usd", "0.5"))
        # 4 reference + 4 translate + 4 judge = 12 calls at $0.01 is only $0.12: the limit is not reached
        self.assertEqual(code, 0)
        with mock.patch.object(llm.FakeClient, "chat", dear):
            code, out = quiet_main(self.argv("--run-name", "r2", "--translator", "fake/b", "--conditions", "T0", "--budget-usd", "0.025"))
        self.assertEqual(code, 3)
        self.assertIn("STOPPED EARLY", open(os.path.join(self.results, "r2", "summary.txt")).read())

    def test_resume_after_interruption(self):
        calls = {"n": 0}
        real = llm.FakeClient.chat

        def counting(self_, body):
            calls["n"] += 1
            return real(self_, body)

        results_full = os.path.join(self.tmp.name, "full")
        base = ["--prepared-dir", self.prepared, "--asr-dir", os.path.join(self.tmp.name, "asr"), "--fake", "--workers", "1",
                "--translator", "fake/a", "--conditions", "T0", "--budget-usd", "5", "--run-name", "r"]
        with mock.patch.object(llm.FakeClient, "chat", counting):
            self.assertEqual(quiet_main(base + ["--results-dir", results_full])[0], 0)
        full = calls["n"]
        self.assertGreater(full, 6)

        calls["n"] = 0

        def interrupt(self_, body):
            if calls["n"] >= 6:
                raise KeyboardInterrupt("stop")
            return counting(self_, body)

        with mock.patch.object(llm.FakeClient, "chat", interrupt):
            self.assertEqual(quiet_main(base + ["--results-dir", self.results])[0], 130)
        self.assertEqual(calls["n"], 6)
        calls["n"] = 0
        with mock.patch.object(llm.FakeClient, "chat", counting):
            self.assertEqual(quiet_main(base + ["--results-dir", self.results])[0], 0)
        self.assertEqual(calls["n"], full - 6)

    def test_judge_parse_error_and_retry(self):
        def responder(body):
            text = llm.body_text(body)
            if "You check the Korean translation" in text:
                if "candidate" in text and RETRY_SEEN(text):
                    return "still not json"
                return "not json at all"
            return llm.fake_reply(body)

        RETRY_SEEN = lambda text: te.RETRY_NOTE.strip() in text
        runner = self.runner(responder)
        ev = te.Evaluation(runner, "ref", "judge", True, 1)
        sentences = te.build_sentences("XX.cut01", made_up_piece())
        rows = ev.run([{"id": "XX.cut01", "sentences": sentences, "asr": None}], ["T0"], ["fake/a"], ["app"])
        self.assertTrue(all(r["judge"] == {"parse_error": True, "raw": "still not json"} for r in rows))
        self.assertEqual(runner.stats["judge"]["new"], 8)       # 4 sentences, each asked twice
        summary = te.summarise(rows)
        self.assertEqual((summary[0]["parse_error"], summary[0]["judged"], summary[0]["Meaning_right"]), (4, 0, None))

    def test_judge_retry_succeeds(self):
        def responder(body):
            text = llm.body_text(body)
            if "You check the Korean translation" in text:
                if te.RETRY_NOTE.strip() in text:
                    return 'Sure! {"meaning": "partly", "critical": [], "errors": [], "comment": "x"}'
                return "oops"
            return llm.fake_reply(body)

        runner = self.runner(responder)
        ev = te.Evaluation(runner, "ref", "judge", True, 1)
        sentences = te.build_sentences("XX.cut01", made_up_piece())
        rows = ev.run([{"id": "XX.cut01", "sentences": sentences, "asr": None}], ["T0"], ["fake/a"], ["app"])
        self.assertEqual({r["judge"]["meaning"] for r in rows}, {"partly"})

    def runner(self, responder=None):
        prices = llm.load_prices(offline=True)
        return llm.Runner(llm.FakeClient(prices, responder), llm.Cache(os.path.join(self.tmp.name, "c")), llm.Budget(5), prices)

    def test_cache_hit_means_no_second_call(self):
        runner = self.runner()
        body = te.claude_body("anthropic/claude-sonnet-5.5", "hello", 10)
        first = runner.ask("judge", body, 10)
        second = runner.ask("judge", body, 10)
        self.assertEqual(runner.client.calls, 1)
        self.assertEqual(first["text"], second["text"])
        self.assertEqual((runner.stats["judge"]["new"], runner.stats["judge"]["cached"]), (1, 1))
        runner.ask("judge", te.claude_body("anthropic/claude-sonnet-5.5", "hello!", 10), 10)     # another input: a call
        self.assertEqual(runner.client.calls, 2)

    def test_budget_class(self):
        b = llm.Budget(0.10)
        b.reserve(0.06)
        b.settle(0.06, 0.05)
        with self.assertRaises(llm.BudgetStop):
            b.reserve(0.06)
        b.reserve(0.05)

    def test_judge_check_agreement(self):
        answers = {"N1": "partly", "N2": "wrong", "N3": "right"}

        def responder(body):
            text = llm.body_text(body)
            for cid, meaning in answers.items():
                if f"case-{cid}" in text:
                    sev = {"partly": "major", "wrong": "critical", "right": "minor"}[meaning]
                    return json.dumps({"meaning": meaning, "critical": [], "errors": [{"type": "omission", "severity": sev}], "comment": ""})
            return "bad"

        cases = [
            {"id": "N1", "previous": "", "source_en": "x", "reference_ko": "r", "candidate_ko": "case-N1", "expected_meaning": "partly", "expected_top_severity": "major"},
            {"id": "N2", "previous": "A: hi", "source_en": "x", "reference_ko": "r", "candidate_ko": "case-N2", "expected_meaning": "right", "expected_top_severity": None},
            {"id": "N3", "previous": "", "source_en": "x", "reference_ko": "r", "candidate_ko": "case-N3", "expected_meaning": "right", "expected_top_severity": "minor"},
            {"id": "N4", "previous": "", "source_en": "x", "reference_ko": "r", "candidate_ko": "case-N4", "expected_meaning": "right", "expected_top_severity": None},
        ]
        ev = te.Evaluation(self.runner(responder), "ref", "judge", True, 1)
        results, counts = te.judge_check(ev, cases)
        self.assertEqual(counts, {"cases": 4, "judged": 4, "meaning_agree": 2, "severity_agree": 2, "parse_errors": 1})
        self.assertIn("meaning agrees in 2 of 4", te.format_judge_check(results, counts))

    def test_judge_check_cli_fake(self):
        code, out = quiet_main(["--judge-check", "--fake", "--results-dir", self.results, "--run-name", "jc"])
        self.assertEqual(code, 0)
        self.assertIn("meaning agrees in", out)
        self.assertTrue(os.path.exists(os.path.join(self.results, "jc", "judge_check.json")))


class Summary(unittest.TestCase):
    def row(self, meaning, words, errors=(), kind="content", backchannel=False, candidate="가", critical=(), perr=False):
        judge = {"parse_error": True, "raw": ""} if perr else {"meaning": meaning, "critical": list(critical),
                                                              "errors": [{"type": t, "severity": s} for t, s in errors]}
        return {"translator": "m", "variant": "app", "condition": "T0", "ref_words": words, "judge": judge, "reference_kind": kind,
                "backchannel": backchannel, "candidate_ko": candidate, "asr_empty": False, "cost_translate": 0.01,
                "cost_judge": 0.02, "seconds_translate": 1.0}

    def test_numbers_by_hand(self):
        rows = [
            self.row("right", 10),
            self.row("partly", 10, [("omission", "major")]),
            self.row("wrong", 10, [("wrong_name_or_number", "critical"), ("addition", "minor")], critical=["x"]),
            self.row("right", 2, kind="backchannel", backchannel=True, candidate=""),
            self.row(None, 5, perr=True),
        ]
        rows[3]["seconds_translate"] = None
        g = te.summarise(rows)[0]
        self.assertEqual((g["sentences"], g["judged"], g["parse_error"], g["unjudged"]), (5, 4, 1, 0))
        self.assertAlmostEqual(g["Meaning_right"], 2 / 4)
        self.assertAlmostEqual(g["Meaning_right_partly"], 3 / 4)
        self.assertAlmostEqual(g["Meaning_noBC_right"], 1 / 3)
        self.assertAlmostEqual(g["Meaning_noBC_right_partly"], 2 / 3)
        self.assertAlmostEqual(g["Meaning_content_right"], 1 / 3)
        self.assertEqual((g["n_noBC"], g["n_content"]), (3, 3))
        self.assertAlmostEqual(g["Critical_per_100_sentences"], 25.0)
        self.assertAlmostEqual(g["T_err_per_100_words"], 2 / 32 * 100)          # one major + one critical in 32 judged words
        self.assertAlmostEqual(g["T_err_minor"], 1 / 32 * 100)
        self.assertAlmostEqual(g["T_err_by_type"]["omission"], 1 / 32 * 100)
        self.assertAlmostEqual(g["T_err_by_type"]["wrong_name_or_number"], 1 / 32 * 100)
        self.assertEqual(g["T_err_by_type"]["addition"], 0)                      # the addition was minor
        self.assertEqual(g["empty_candidates"], 1)
        self.assertAlmostEqual(g["cost_translate_usd"], 0.05)
        self.assertAlmostEqual(g["mean_translate_seconds"], 1.0)
        self.assertIn("m", te.format_table([g]))

    def test_critical_falls_back_to_list(self):
        self.assertEqual(te.critical_count({"critical": ["a", "b"], "errors": []}), 2)
        self.assertEqual(te.critical_count({"critical": [], "errors": [{"severity": "critical"}]}), 1)


class Requests(unittest.TestCase):
    def test_variants(self):
        base = te.translate_body("m", "app", "hello there", ["A: one", "B: two", "A: three"])
        self.assertIn("A: three", base["messages"][1]["content"])
        self.assertNotIn("A: one", base["messages"][1]["content"])             # 2 context lines
        speech = te.translate_body("m", "speech", "hello there", ["A: one"])
        self.assertIn("speech recogniser", speech["messages"][0]["content"])
        self.assertTrue(speech["messages"][0]["content"].endswith("Reply with the translation only."))
        four = te.translate_body("m", "context4", "hello", ["1", "2", "3", "4", "5"])
        self.assertIn("2\n3\n4\n5", four["messages"][1]["content"])
        self.assertNotIn("1\n", four["messages"][1]["content"])
        self.assertEqual(base["provider"]["zdr"], True)
        self.assertEqual(base["usage"], {"include": True})

    def test_copy_matches_the_app(self):
        module = te._import_app_translate()
        if module is None:
            self.skipTest("translate.py cannot be imported here")
        a = te.app_request("hello there", ["A: one"], "m", module)
        b = te._copied_build_request("hello there", "Korean", ["A: one"], "m")
        self.assertEqual(a, b)

    def test_prompts_fill_completely(self):
        for path in (te.REFERENCE_PROMPT, te.JUDGE_PROMPT):
            self.assertNotIn("---\n", te.load_prompt(path)[:5])
            self.assertTrue(te.load_prompt(path).strip())
        with self.assertRaises(ValueError):
            te.fill("{{a}} {{b}}", a="x")

    def test_budget_default_from_control_file(self):
        with tempfile.NamedTemporaryFile("w", suffix=".md", delete=False) as f:
            f.write("x: 1\nbudget_usd_per_batch: 7.5\n")
        self.addCleanup(os.unlink, f.name)
        self.assertEqual(te.read_budget_default(f.name), 7.5)
        self.assertEqual(te.read_budget_default("/nonexistent/file"), 5.0)

    def test_real_client_without_key(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("OPENROUTER_API_KEY", None)
            with self.assertRaises(llm.CallError):
                llm.RealClient().chat({"model": "m", "messages": []})


if __name__ == "__main__":
    unittest.main()
