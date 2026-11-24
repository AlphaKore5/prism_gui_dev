"""Keeping a hunt under the model's rate limit (22-Nov-2026): the owner saw "Groq is rate-limiting this key" five
times in one run. Pace the calls, switch to the next model before waiting, cool off only when every model refused."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from prospector import ai_pace as P                      # noqa: E402

LIMIT = RuntimeError("Groq is rate-limiting your API key. Wait a minute and try again.")


class Clock:
    def __init__(self):
        self.now, self.slept = 1000.0, []

    def __call__(self):
        return self.now

    def sleep(self, seconds):
        self.slept.append(seconds)
        self.now += seconds


class ThePacer(unittest.TestCase):
    def setUp(self):
        self.clock = Clock()
        self.pacer = P.Pacer(6000, clock=self.clock)

    def test_calls_that_fit_the_minute_do_not_wait(self):
        self.pacer.spent(2000)
        self.assertEqual(self.pacer.wait_needed(3000), 0.0)

    def test_a_call_that_does_not_fit_waits_until_enough_of_the_last_minute_has_passed(self):
        self.pacer.spent(4000)
        self.clock.now += 20
        self.pacer.spent(1500)
        self.clock.now += 10                                   # the first 4000 is 30 s old, the 1500 is 10 s old
        self.assertAlmostEqual(self.pacer.wait_needed(2000), 30.0)    # frees at 60 s from the first spend

    def test_a_call_bigger_than_the_whole_budget_goes_after_an_empty_window_and_is_not_stuck(self):
        self.assertEqual(self.pacer.wait_needed(20000), 0.0)    # nothing spent: it can only go
        self.pacer.spent(500)
        self.assertGreater(self.pacer.wait_needed(20000), 0.0)
        self.clock.now += 61
        self.assertEqual(self.pacer.wait_needed(20000), 0.0)

    def test_every_refusal_tightens_the_budget_down_to_a_floor(self):
        for _ in range(20):
            self.pacer.tighten()
        self.assertEqual(self.pacer.per_minute, P.FLOOR)

    def test_the_estimate_grows_with_the_prompt(self):
        self.assertLess(P.tokens_of("a" * 300), P.tokens_of("a" * 3000))
        self.assertGreater(P.tokens_of(""), 0)


class ThePacedAsk(unittest.TestCase):
    def setUp(self):
        self.clock = Clock()
        self.pacer = P.Pacer(6000, clock=self.clock)
        self.waits = []

    def ask(self, call, models=("big", "mid", "small"), **kw):
        return P.paced(call, models, self.pacer, sleep=self.clock.sleep,
                       on_wait=lambda s, why: self.waits.append((s, why)), **kw)

    def test_a_good_answer_comes_back_from_the_first_model_with_no_wait(self):
        ask = self.ask(lambda m, p, t, j: f"{m}:ok")
        self.assertEqual(ask("prompt"), "big:ok")
        self.assertEqual(self.waits, [])

    def test_a_refused_model_is_followed_by_the_next_one_before_anything_waits(self):
        tried = []

        def call(m, p, t, j):
            tried.append(m)
            if m == "big":
                raise LIMIT
            return f"{m}:ok"
        ask = self.ask(call)
        self.assertEqual(ask("prompt"), "mid:ok")
        self.assertEqual(tried, ["big", "mid"])
        self.assertEqual(self.clock.slept, [])
        self.assertLess(self.pacer.per_minute, 6000)                # and the pace learned from it

    def test_when_every_model_refuses_it_cools_off_once_and_tries_them_all_again(self):
        calls = []

        def call(m, p, t, j):
            calls.append(m)
            if len(calls) <= 3:
                raise LIMIT
            return "late"
        ask = self.ask(call)
        self.assertEqual(ask("prompt"), "late")
        self.assertEqual(calls, ["big", "mid", "small", "big"])
        self.assertAlmostEqual(sum(self.clock.slept), P.COOL_OFF)
        self.assertEqual(len(self.waits), 1)
        self.assertIn("rate-limited", self.waits[0][1])

    def test_after_the_cool_off_it_gives_up_and_says_why_in_the_servers_words(self):
        ask = self.ask(lambda m, p, t, j: (_ for _ in ()).throw(LIMIT))
        with self.assertRaises(RuntimeError) as cm:
            ask("prompt")
        self.assertIn("rate-limiting", str(cm.exception))

    def test_an_error_that_is_not_a_rate_limit_is_raised_at_once_and_never_retried(self):
        calls = []

        def call(m, p, t, j):
            calls.append(m)
            raise RuntimeError("Groq rejected your API key.")
        with self.assertRaises(RuntimeError):
            self.ask(call)("prompt")
        self.assertEqual(calls, ["big"])

    def test_a_call_over_budget_is_paced_and_says_what_it_is_waiting_for(self):
        ask = self.ask(lambda m, p, t, j: "ok")
        big = "x" * 15000                                       # about 5500 tokens
        ask(big)
        ask(big)                                                # the second would exceed 6000 in the same minute
        self.assertTrue(self.waits and "stays under its rate limit" in self.waits[0][1])
        self.assertGreater(sum(self.clock.slept), 0)

    def test_stop_is_heard_while_waiting(self):
        self.pacer.spent(6000)
        ask = self.ask(lambda m, p, t, j: "ok", cancelled=lambda: True)
        with self.assertRaises(RuntimeError) as cm:
            ask("x" * 3000)
        self.assertEqual(str(cm.exception), "Stopped.")

    def test_only_the_first_few_models_are_tried(self):
        tried = []

        def call(m, p, t, j):
            tried.append(m)
            raise LIMIT
        with self.assertRaises(RuntimeError):
            self.ask(call, models=("a", "b", "c", "d", "e"))("p")
        self.assertEqual(set(tried), {"a", "b", "c"})


class TheRealAsk(unittest.TestCase):
    def test_the_owners_own_key_gets_a_paced_ask_that_calls_the_router_without_its_own_retries(self):
        from unittest import mock

        import core_bridge as CB
        from prospector import buyers as B
        with mock.patch.object(CB.router, "groq_chat", return_value="{}") as chat:
            ask = B.make_ask({"api_key": "k", "model": "m"})
            self.assertEqual(ask("p", "qualify", True, 0.1), "{}")
        self.assertEqual(chat.call_args.kwargs["retries"], 0)
        self.assertEqual(chat.call_args.args[1], "m")

    def test_a_refused_first_model_goes_to_the_next_model_the_engine_knows(self):
        from unittest import mock

        import core_bridge as CB
        from prospector import buyers as B
        seen = []

        def chat(key, model, prompt, **kw):
            seen.append(model)
            if len(seen) == 1:
                raise LIMIT
            return "ok"
        with mock.patch.object(CB.router, "groq_chat", side_effect=chat):
            self.assertEqual(B.make_ask({"api_key": "k", "model": "mine"})("p", "qualify", True, 0.1), "ok")
        self.assertEqual(seen[0], "mine")
        self.assertNotEqual(seen[1], "mine")

    def test_the_owner_can_raise_the_budget_when_their_plan_allows_it(self):
        from unittest import mock

        import core_bridge as CB
        from prospector import buyers as B
        with mock.patch.object(CB.router, "groq_chat", return_value="{}"):
            self.assertIsNotNone(B.make_ask({"api_key": "k", "ai_tokens_per_minute": 30000}))


if __name__ == "__main__":
    unittest.main()
