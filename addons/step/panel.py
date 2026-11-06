"""The STEP front door."""
from __future__ import annotations

import theme
from widgets.panel_base import AddonFrontDoor


class StepPanel(AddonFrontDoor):
    TITLE = "STEP"
    BLURB = ("Every part's size, thickness, holes and weight — measured "
             "from the 3D model itself, not guessed. Then draft, ask or "
             "edit.")
    ICON = "grid"
    HEADLINE = "Attach a STEP model to begin"
    DETAIL = ("A .step or .stp straight from the customer — measured here, "
              "on this machine, and it never leaves.")
    ACTION = "Attach a model"
    KIND = "step"

    STEPS = [
        ("paperclip", "Attach the model",
         "Upload one or more .step / .stp 3D CAD files to measure."),
        ("chart", "Measured on this machine",
         "Extracts formed sizes, sheet thickness, hole diameters, and weights."),
        ("lock", "The model never leaves",
         "Only raw numbers and local renders are processed — models stay private."),
        ("pencil", "Draft, ask or edit",
         "Generates dimensioned drawing sheets, review plans, or modified models."),
    ]

    PLACEHOLDERS = [
        ("How do I make this lighter?",
         "Analyzes measured geometry to suggest material and weight optimizations."),
        ("Fit M8 bolts instead of M6",
         "Enlarges holes on a copy of the model and recalculates measurements."),
    ]

    def build(self):
        self.HUE = theme.ACCENT
        super().build()

    def tool_roles(self):
        """Mirrors StepDialog: ChatGPT draws a Draft; Claude Haiku 5.5 (or
        Claude Sonnet 5.5, if picked) answers and reviews the plan for Ask
        and Edit, called directly with your own OpenRouter key. Every one
        sees the measured numbers and, only with your consent each
        session, Prism's own render — never the model."""
        return [
            ("image", "Draws the styled sheet (Draft)",
             "ChatGPT, always — its image model is the one that draws a "
             "dimension sheet well from a numbers-only brief. It is handed "
             "the measured figures and Prism's own plain render — never "
             "the model. Prism's own dimensioned sheet is made regardless.",
             "ChatGPT"),
            ("bulb", "Answers and reviews the plan (Ask, Edit)",
             "Claude Haiku 5.5 by default, or Claude Sonnet 5.5 if you "
             "pick it — called directly with your own OpenRouter key, "
             "never a browser tab. It turns its own suggestions into the "
             "exact changes Prism can apply, from the numbers alone.",
             "Claude Haiku 5.5"),
        ]
