# Try a build flavour from source

```
devtools/run_flavour.sh <complete|studio|sales|engineering>
```

Offscreen check (no window, prints the self-test list and exits):

```
PRISM_SELFTEST=1 QT_QPA_PLATFORM=offscreen devtools/run_flavour.sh sales
```

What the script does: sets `HOME=~/prism-flavour-sandbox/<flavour>` (created if
missing; your real `~/.prism` is never touched), `PRISM_FLAVOUR=<flavour>`,
`PRISM_LICENSE_OFFLINE_DEV=1` (minted licence, no licence server) and
`PRISM_HOME` inside the sandbox. `PRISM_FLAVOUR` is read by
`channel.apply_flavour_override()` only in a source run; a frozen build ignores
it and `flavour.FLAVOUR` still defaults to `complete`.

State for a flavour is in `~/prism-flavour-sandbox/<flavour>/.prism-dev/.prism/`.
Delete the folder to start fresh.

## What to expect (add-ons, from `addons/flavours/*.py`)

| Flavour | Add-ons | Self-test "add-ons registered" |
|---|---|---|
| complete | Email inquiry automation, BOQ, Gerber, STEP, BOM & Stock, Email Outreach, Leads & Outreach, WhatsApp, Reel / Studio, Motion Graphics | 10 |
| studio | Reel / Studio, Motion Graphics | 2 |
| sales | Email inquiry automation, Email Outreach, Leads & Outreach, WhatsApp | 4 |
| engineering | BOQ, BOM & Stock, STEP, Gerber | 4 |

Anything outside the flavour is absent from the sidebar. The self-test also
skips that add-on's checks (for example Sales runs no BOQ or Reel check).

## Checking Pulse locally

Pulse is off for source runs unless you set `PRISM_PULSE=1`. To see it work
without sending anything to production:

1. Open Settings and find the "Send Prism's error reports" switch (on by default).
2. Events are queued in
   `~/prism-flavour-sandbox/<flavour>/.prism-dev/.prism/pulse/queue.jsonl`.
3. With the switch off nothing is queued; turn it on and trigger an error to see a line appear.
4. Leave `PRISM_PULSE` unset so nothing is sent; the queue file is the thing to inspect.
