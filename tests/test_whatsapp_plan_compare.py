"""WhatsApp plans, as AiSensy shows them (the owner, 27-Nov-2026: "build all of it like aisensy").

Held here:
  - prices read like a pricing page: "₹1,500 / month", a discount for quarterly and yearly, "Free", "Talk to us";
  - Compare plans shows every tier with its limits and features, marks the current plan, and asks for another
    through plan/request (a message to Alphakore, never a purchase);
  - a refusal for the plan, from any screen, offers the plan or add-on that has it — once, not twice;
  - the Plan page names the add-ons and extra seats.

Demo mode (no network), no real ~/.prism; no event loop is run."""
from __future__ import annotations

import os
import sys
import unittest
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtWidgets import QApplication, QLabel, QPushButton    # noqa: E402

_app = QApplication.instance() or QApplication(sys.argv)

from addons.whatsapp import demo_usage, plan_compare as PC          # noqa: E402


def plan_reply(plan="basic", addons=()):
    return {"plan": plan, "label": plan.title(), "addons": list(addons), "extra_seats": 0, "catalogue": demo_usage.catalogue()}


class Words(unittest.TestCase):
    def test_prices_read_like_a_pricing_page(self):
        disc = {"monthly": 0, "quarterly": 5, "yearly": 10}
        self.assertEqual(PC.price_text(1500, "monthly", disc), "Rs 1,500 / month")
        self.assertEqual(PC.price_text(3200, "yearly", disc), "Rs 2,880 / month, billed yearly")
        self.assertEqual(PC.price_text(0, "yearly", disc), "Free")
        self.assertEqual(PC.price_text(None), "Talk to us")

    def test_limits_read_as_numbers_none_or_no_limit(self):
        self.assertEqual(PC.limit_text("tags", 250), "250")
        self.assertEqual(PC.limit_text("webhooks", 0), "–")
        self.assertEqual(PC.limit_text("agents", None), "No limit")
        self.assertEqual(PC.limit_text("storage_mb", 5120), "5 GB")

    def test_what_unlocks_a_refusal_is_said_in_words(self):
        cat = demo_usage.catalogue()
        self.assertEqual(PC.needs_words("pro", cat), "Pro")
        self.assertEqual(PC.needs_words("addon:chatbot", cat), "the Chatbot flows add-on")
        self.assertEqual(PC.want_of("addon:ai_agent"), {"addons": ["ai_agent"]})
        self.assertEqual(PC.want_of("premium"), {"plan": "premium"})
        self.assertEqual(PC.want_of(None), {})


class TheCompareScreen(unittest.TestCase):
    def setUp(self):
        self.calls = []
        patch = mock.patch.object(PC.ui, "call", lambda owner, route, data=None, **kw: self.calls.append((route, data)))
        patch.start()
        self.addCleanup(patch.stop)

    def dialog(self, **kw):
        d = PC.PlanCompareDialog(plan_reply(**kw))
        self.addCleanup(d.deleteLater)
        return d

    def texts(self, d):
        return [w.text() for w in d.findChildren(QLabel)] + [b.text() for b in d.findChildren(QPushButton)]

    def test_every_tier_is_shown_with_its_price_and_the_current_one_is_marked(self):
        d = self.dialog(plan="pro")
        t = self.texts(d)
        for name in ("Free", "Basic", "Pro", "Premium", "Unlimited", "Enterprise"):
            self.assertIn(name, t)
        self.assertIn("Rs 3,200 / month", t)
        self.assertIn("Your plan", t)
        self.assertNotIn("pro", d.ask_buttons)                  # no "Ask for Pro" on Pro itself
        self.assertIn("premium", d.ask_buttons)

    def test_yearly_shows_the_discounted_monthly_price(self):
        d = self.dialog()
        d._set_cycle("yearly")
        self.assertIn("Rs 1,350 / month, billed yearly", self.texts(d))      # Basic, 10% off

    def test_features_and_add_ons_are_listed(self):
        t = self.texts(self.dialog())
        for words in ("Campaign scheduler", "Number masking", "Chatbot flows", "AI agent", "Extra agent seat", "Ask for it"):
            self.assertIn(words, t)

    def test_asking_for_a_plan_sends_a_request_and_nothing_else(self):
        d = self.dialog(plan="basic")
        d.ask_buttons["premium"].click()
        self.assertEqual(self.calls[-1][0], "plan/request")
        self.assertEqual(self.calls[-1][1]["want"], {"plan": "premium"})

    def test_a_held_add_on_is_marked_not_offered(self):
        t = self.texts(self.dialog(addons=["chatbot"]))
        self.assertIn("You have it", t)


class ARefusalOffersTheWay(unittest.TestCase):
    def setUp(self):
        PC._OPEN.clear()
        self.made = []

        class Fake:
            def __init__(fake, message, needs, parent=None):
                fake.message, fake.needs, fake.visible = message, needs, False
                self.made.append(fake)

            def open(fake):
                fake.visible = True

            def isVisible(fake):
                return fake.visible
        patch = mock.patch.object(PC, "UpgradePrompt", Fake)
        patch.start()
        self.addCleanup(patch.stop)
        self.addCleanup(PC._OPEN.clear)

    def test_a_plan_refusal_opens_the_prompt_with_what_unlocks_it(self):
        shown = PC.offer_upgrade(None, "Scheduling a campaign is not part of the Basic plan.",
                                 {"reason": "plan_feature", "needs": "pro"})
        self.assertTrue(shown)
        self.assertEqual((self.made[0].needs, self.made[0].visible), ("pro", True))

    def test_another_refusal_is_not_a_prompt(self):
        self.assertFalse(PC.offer_upgrade(None, "Nope.", {"reason": "window_closed"}))
        self.assertEqual(self.made, [])

    def test_the_same_wall_twice_is_one_prompt(self):
        PC.offer_upgrade(None, "x", {"reason": "plan_limit", "needs": "premium"})
        PC.offer_upgrade(None, "x", {"reason": "plan_limit", "needs": "premium"})
        self.assertEqual(len(self.made), 1)

    def test_every_platform_call_routes_plan_refusals_here(self):
        from addons.whatsapp import ui
        seen = []
        with mock.patch.object(PC, "offer_upgrade", lambda o, m, d: seen.append(d)):
            ui._offer_upgrade(None, "x", {"reason": "plan_feature", "needs": "addon:chatbot"})
            ui._offer_upgrade(None, "x", {"reason": "bad_request"})
        self.assertEqual(seen, [{"reason": "plan_feature", "needs": "addon:chatbot"}])


class TheTabsShowWhatThePlanLacks(unittest.TestCase):
    def bench(self):
        from addons.whatsapp import ui
        from addons.whatsapp import workbench as WB
        with mock.patch.object(ui, "call", lambda *a, **k: None):
            wb = WB.WhatsAppWorkbench({})
        self.addCleanup(wb.deleteLater)
        return wb, WB

    def test_free_locks_campaigns_shop_and_forms_and_names_the_plan(self):
        wb, WB = self.bench()
        cat = demo_usage.catalogue()
        free = next(t for t in cat["tiers"] if t["plan"] == "free")
        wb._apply_plan({"features": free["features"], "catalogue": cat})
        self.assertEqual(sorted(wb._locked_tabs), sorted([WB._CAMPAIGNS, WB._SHOP, WB._FORMS]))
        self.assertIn("Part of Basic", wb._tab_buttons[WB._CAMPAIGNS].toolTip())
        self.assertIn("Part of Pro", wb._tab_buttons[WB._SHOP].toolTip())

    def test_pro_unlocks_them_again(self):
        wb, WB = self.bench()
        cat = demo_usage.catalogue()
        pro = next(t for t in cat["tiers"] if t["plan"] == "pro")
        wb._apply_plan({"features": [], "catalogue": cat})
        wb._apply_plan({"features": pro["features"], "catalogue": cat})
        self.assertEqual(wb._locked_tabs, [])
        self.assertEqual(wb._tab_buttons[WB._SHOP].toolTip(), "")


class ThePlanPage(unittest.TestCase):
    def test_add_ons_and_extra_seats_are_named(self):
        from addons.whatsapp.settings_plan import addons_words
        self.assertEqual(addons_words({"addons": ["chatbot", "ai_agent"], "extra_seats": 2}),
                         "Add-ons: Chatbot flows, AI agent, 2 extra seats")
        self.assertEqual(addons_words({"addons": [], "extra_seats": 0}), "")


if __name__ == "__main__":
    unittest.main()
