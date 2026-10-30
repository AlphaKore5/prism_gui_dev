"""addons/boq/agents.py -- item 30's new entries: two OpenRouter-backed
writer options ("Prism Agent Claude"/"Prism Agent Deep"), and "No
research" as the research picker's own real, selectable choice.
"""
from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from addons.boq import agents as boq_agents                        # noqa: E402


class PrismAgentsAreFirstInTheWriterList(unittest.TestCase):
    def test_both_prism_agents_are_in_writer(self):
        for name in boq_agents.PRISM_AGENTS:
            self.assertIn(name, boq_agents.WRITER)

    def test_prism_agent_claude_is_the_default_first_entry(self):
        self.assertEqual(boq_agents.WRITER[0], "Prism Agent Claude")

    def test_every_browser_agent_from_before_is_still_there(self):
        for name in ("Claude", "Grok", "Kimi 2.6", "DeepSeek", "Gemini", "ChatGPT"):
            self.assertIn(name, boq_agents.WRITER)

    def test_prism_agent_deep_and_the_browser_deepseek_are_different_entries(self):
        """"Prism Agent Deep" (OpenRouter's deepseek-v3.2) must never be
        confused with "DeepSeek" (the existing browser agent, item 20-era)
        -- two different code paths, two different names."""
        self.assertIn("DeepSeek", boq_agents.WRITER)
        self.assertIn("Prism Agent Deep", boq_agents.WRITER)
        self.assertNotEqual("DeepSeek", "Prism Agent Deep")


class NoResearchIsFirstInTheResearchList(unittest.TestCase):
    def test_no_research_is_the_default_first_entry(self):
        self.assertEqual(boq_agents.RESEARCH[0], boq_agents.NO_RESEARCH)

    def test_the_real_research_tools_are_still_offered_after_it(self):
        for name in ("Perplexity", "ChatGPT", "Claude"):
            self.assertIn(name, boq_agents.RESEARCH)


class EveryPrismAgentHasAGenerationAndAFollowupModel(unittest.TestCase):
    def test_every_prism_agent_has_both_tiers_mapped(self):
        for name in boq_agents.PRISM_AGENTS:
            self.assertIn(name, boq_agents.PRISM_AGENT_MODELS)
            self.assertIn(name, boq_agents.PRISM_AGENT_FOLLOWUP_MODELS)

    def test_the_followup_tier_is_never_the_same_model_as_generation(self):
        """item 30e's whole point -- a follow-up uses a cheaper, different
        model, not the same one twice."""
        for name in boq_agents.PRISM_AGENTS:
            self.assertNotEqual(boq_agents.PRISM_AGENT_MODELS[name],
                                boq_agents.PRISM_AGENT_FOLLOWUP_MODELS[name])

    def test_model_ids_are_openrouter_shaped_provider_slash_model(self):
        for table in (boq_agents.PRISM_AGENT_MODELS, boq_agents.PRISM_AGENT_FOLLOWUP_MODELS):
            for model_id in table.values():
                self.assertRegex(model_id, r"^[a-z0-9_.-]+/[a-z0-9_.-]+$")


if __name__ == "__main__":
    unittest.main()
