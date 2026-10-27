# Gerber Automation in Prism — Quick Overview

## What it is
A feature inside Prism that reads a PCB's manufacturing files (Gerbers and
the drill file) and automatically measures the numbers a factory needs to
check a board before production — no manual markup, no CAM operator
measuring by hand.

## What it measures
Nine numbers, taken directly off the files:

- Board size
- Array size
- Boards per array
- Minimum track width
- Minimum track spacing
- Minimum drill size
- Number of drills
- Minimum pad pitch
- Minimum SMT pad size

All nine are shown to two decimal places and have been tested against real
customer jobs.

## How it's verified
Every number goes through a short verification ladder before it's trusted —
checked against the customer's own sheet where one exists, cross-checked
with an independent reader, and only an AI re-check as the last, optional
step. Nothing is reported as final until it clears these checks.

## Why it's safe
The actual board design files never reach an AI at any point. Only the
final measured numbers leave the machine — the design itself, which is the
customer's intellectual property, stays fully protected.

## Why it matters
What used to take a CAM operator manual measurement time now comes back in
seconds, consistently, on every job — freeing people up for the judgment
calls that actually need a person.
