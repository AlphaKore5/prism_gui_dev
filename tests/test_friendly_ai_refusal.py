"""The server's own AI refusal sentence is what the customer reads.

One case per sentence the licence server sends (errors.py wording)."""
import unittest

import friendly

SERVER_SENTENCES = {
    "not_enabled": "AI isn't switched on for your account yet. Contact "
                   "Alphakore and we'll turn it on.",
    "blocked": "AI is paused on your account. Contact Alphakore to find out "
               "why. Nothing was charged.",
    "scope": "AI isn't available to your account on this version of Prism. "
             "Install the latest version.",
    "insufficient": "Not enough AI credits for that: it needs 40 and you "
                    "have 12. Ask Alphakore to top up your credits.",
    "generic_402": "You don't have enough credits for that. Ask Alphakore to "
                   "top up your credits and it will run straight away.",
    "recheck": "Prism needs to re-check your licence before using AI. Connect "
               "to the internet and try again.",
}


class AiRefusalCopy(unittest.TestCase):
    def test_each_server_sentence_is_shown_as_written(self):
        for name, msg in SERVER_SENTENCES.items():
            with self.subTest(name):
                p = friendly.explain(msg, "plan")
                self.assertEqual(p.what, msg)
                self.assertEqual(p.title, "Prism AI couldn't run this")

    def test_context_prefix_does_not_hide_it(self):
        msg = SERVER_SENTENCES["blocked"]
        self.assertEqual(friendly.explain(msg, "run").what, msg)

    def test_other_errors_still_use_their_own_rules(self):
        p = friendly.explain("couldn't reach the licence server", "run")
        self.assertNotEqual(p.title, "Prism AI couldn't run this")


if __name__ == "__main__":
    unittest.main()
