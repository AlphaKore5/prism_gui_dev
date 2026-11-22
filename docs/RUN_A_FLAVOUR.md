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
`PRISM_LICENSE_OFFLINE_DEV=1` and `PRISM_HOME` inside the sandbox.
`PRISM_FLAVOUR` is read by `channel.apply_flavour_override()` only in a source
run; a frozen build ignores it and `flavour.FLAVOUR` still defaults to
`complete`.

State for a flavour is in `~/prism-flavour-sandbox/<flavour>/.prism-dev/.prism/`.
Delete the folder to start fresh.

## The licence

Before starting Prism the script runs `devtools/mint.py flavour --flavour <f>`.
If the sandbox has no valid licence for that flavour, it writes a 30-day dev
licence into the sandbox's `license.json` with the flavour's licence features:
`core` plus the feature of each add-on in `addons/flavours/<f>.py`. Feature keys
are not add-on keys (Email inquiries = `inbox`, WhatsApp = `marketing`, Motion =
`reel`, BOM = `boq`):

| Flavour | Licence features |
|---|---|
| complete | core, boq, email, gerber, inbox, leads, marketing, reel, step |
| studio | core, reel |
| sales | core, email, inbox, leads, marketing |
| engineering | core, boq, gerber, step |

The licence is signed with the dev key, kid `dev2` in `licensing/keys.py`. Prism
trusts that key only when it runs from source; a frozen build trusts the
production key and nothing else, so a dev licence is worthless to a customer.
The private half is `devtools/dev-signing-key.hex`, gitignored, never
committed. In a git worktree the script uses the main checkout's copy;
`PRISM_DEV_SIGNING_KEY=<path>` points it elsewhere.

While a dev licence is in force the script also sets
`PRISM_LICENSE_SERVER=http://127.0.0.1:9`, a closed local port, so neither the
real licence server nor the AI server is contacted. Because no server answers,
`PRISM_LICENSE_OFFLINE_DEV=1` then lets each add-on start if the licence has
its feature. That flag mints nothing by itself: it only changes the answer when
the server cannot be reached. Server-backed features (AI through Prism's server)
therefore do not work in a dev-licensed sandbox.

If the key file is missing the script says so in one line and starts Prism as
before, with no licence, so the licence screen shows. If the sandbox holds a
licence signed by the production key (you activated a real key there), it is
left alone and the real server is used.

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
