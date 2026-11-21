# Prism — Privacy Policy

> **Status: DRAFT, not yet reviewed by a lawyer.** Every factual claim below
> was checked directly against the current code (`license_server/app/models.py`,
> `licensing/`, `client-guide.md` §7) on 2026-08-30, so it describes what Prism
> actually does — but the legal framing (rights language, jurisdiction,
> retention periods, grievance-officer designation) needs a lawyer's review
> before this is published as binding. Do not represent this to a client as
> final until that review happens.

**Effective date:** [fill in on publish] · **Last updated:** 2026-08-30

Alphakore ("we", "us") builds Prism, a desktop application. This policy
explains what Prism sends us, what it deliberately never sends us, and what
happens to the little it does collect.

---

## 1. The short version

Prism runs on your machine and drives AI tools through *your own*, already
logged-in Chrome. Your work — the tasks you type, the files you attach, and
everything the AI tools hand back — never touches our servers. What we do
receive is small, deliberate, and listed in full below: enough to enforce your
licence and to know, in aggregate, that the product works.

---

## 2. What never leaves your machine

Verified directly against the app's code, not asserted from memory:

- **Your files, your prompts, and every output the AI tools produce for you.**
  Prism has no server-side component that a task's content ever reaches.
- **Your Groq API key and your email app password** — stored locally
  (owner-readable only), never transmitted to us.
- **Email recipient lists** — parsed on your machine for the Email add-on,
  never sent to any AI tool or to us.
- **Your Chrome sessions.** Prism reuses your existing logins; it stores no
  passwords for the AI tools it operates.
- **CAD geometry for the BOQ add-on** — measured locally, never uploaded.

## 3. What Prism sends us, and why

Every run, Prism's licensing client asks our licence server for permission
before it does protected work (`licensing/client.py`, `license_server/app/routes/v1.py`).
That request, and the server's bookkeeping of it, includes:

| Data | Why we need it |
|---|---|
| Your licence ID | To identify which licence a request belongs to. |
| A device fingerprint (`device_fp`) — a one-way hash derived from your machine, not a serial number or MAC address in the clear | To enforce your licence's seat count and to spot a licence key shared beyond its paid seats. |
| Coarse platform info (OS, Prism version) | To know which builds are in the field, and to refuse a build too old to trust safely (`min_supported_version`). |
| Which action you took (e.g. "authorize a run", "open BOQ") | To meter usage against your plan's daily allowance, and for nothing else. |
| Your IP address, at the moment of that request | Solely to detect one licence being run from an implausible number of locations at once — see §4. Not used to track your location for any other purpose. |
| Aggregate counts afterwards — how many steps ran, on which tool, whether they succeeded, how long they took | Product reliability and support — e.g. so we can tell you "that's a known issue in v1.2, update to v1.3.1" without you having to describe it from scratch. |

**No brief, no prompt, no output, and no filename is ever sent to us.** This
is not a policy choice we could reverse later without a code change — the
client-side code has nowhere in its request schema to put that data, and the
server has no field built to store it. Prism's error reports (section 3A) are
written to contain none of this: they are scrubbed on your computer and again
on our server, though a scrubber is not a guarantee, which is why 3A says what
to do if you ever see one that does.

### 3A. Error reports and quality signals ("Pulse")

Prism can tell us when something breaks, so we can fix it without you having to
write to us. This is separate from the licence check in section 3. It is on by
default and you can turn it off at any time (see "Your choice" below).

**What Prism sends.** Each report is a short record containing only:

- when something fails: the kind of error (for example "KeyError"), the names of
  the code files and functions in Prism itself where it failed (for example
  `stepfile.py: apply_plan`), a code made from those, and a one-line error
  message in which quoted text, numbers, email addresses, file paths, long keys
  and web-address parameters have been removed or replaced;
- when the previous session ended unexpectedly: that it did, and which screen
  Prism was on;
- how long Prism took to open, in milliseconds;
- actions that took two seconds or longer: which add-on and screen, and how long;
- how a run ended: finished, failed or cancelled, and in which add-on;
- your answers on results: a thumbs up or down, one of a few fixed reasons you
  may pick (for example "wrong", "incomplete", "slow"), and what happened to the
  result next (used as it was, edited, redone). These are fixed choices; Prism
  never sends text you typed;
- with every record: the Prism version, your operating system, the add-on and
  screen involved, and your licence ID and device fingerprint (the same ones as
  in section 3, so a report can be tied to a licence and a seat).

**What Prism never sends in these reports.** Your prompts, the answers or
outputs the AI tools give you, your files, file names or folder paths, names,
email addresses, passwords, API keys or licence keys, and attachments.
Scrubbing happens on your computer first and again on our server before
anything is stored. Reports are designed not to contain personal content; if you
ever see one that does, tell us (section 12) and we will delete it.

**Your choice.** In Settings, under "Help improve Prism", the switch "Send
Prism's error reports" turns this off or on. It takes effect immediately,
without restarting Prism. While it is off, nothing is queued or sent. Prism's
licence check (section 3) is not affected and is not optional, because it is how
your licence is enforced.

**What we do with it.** We use these reports only to find and fix faults, to see
whether new versions start and run well, and to see which kinds of results
people find useful. We do not use them to profile you, to measure what you work
on, or to change what you can do in Prism: a report never switches a feature on
or off.

**Who can see it.** Only Alphakore administrators, through the admin login of
our operator console. The reports are stored in the same licence-server
database as section 6. We do not sell them or share them with advertisers.

**How long we keep it.** Pulse reports are deleted after 90 days.

**If Prism is offline.** Reports wait in a small file in Prism's own folder on
your computer (at most 300, and anything older than 7 days is dropped) and are
sent the next time Prism can reach us. Turning the switch off stops sending;
delete the `pulse` folder inside Prism's data folder to remove what is waiting.

## 4. Seat-sharing detection, specifically

A paid licence covers a fixed number of seats (devices). To make that
enforceable without being invasive, we record which device+IP combinations
have used a licence on which day (`DeviceSighting` in our database) — this is
what lets us tell a customer "your two-seat licence was active from five
different machines yesterday" instead of guessing. It is not used to build a
profile of where you personally go; it exists only to compare against the
seat count on your own licence.

## 5. What goes to the AI tools you use

Whatever your task needs — your brief, and the contents of files you
attached — goes to *your own accounts* on the AI tools Prism drives (ChatGPT,
Claude, Perplexity, Gamma, and others you choose). That traffic is between
you and those services, under **their** privacy policies and terms, exactly
as if you had typed or pasted it in yourself. We do not see it, and we are
not a party to it.

## 6. Where this data is stored

Licence and usage records are held in our licence server's database. [Fill
in: hosting provider(s) and region — confirm before publishing whether this
stays within India or crosses borders, since that changes what disclosure is
required under India's Digital Personal Data Protection Act, 2023.]

## 7. How long we keep it

Licence and device records are kept for as long as your licence exists plus a
reasonable period after expiry, for renewal and support history. Usage
counts are aggregate and not tied to task content, so their retention is a
storage-cost decision rather than a privacy-sensitive one. Pulse reports
(section 3A) are kept for 90 days and then deleted. [A precise
retention schedule should be set and stated here before this is treated as
final — currently the code enforces licence/seat state but does not itself
delete old records on a timer.]

## 8. Your rights

You can ask us, at any time, to tell you what we hold against your licence
ID or device fingerprint, or to delete it once your licence has ended. Write
to the contact below. [This section needs to name the specific rights (access,
correction, erasure, grievance redressal, and the timelines for each) once
governing law is confirmed — under India's DPDP Act, this includes a named
Grievance Officer, see §10.]

## 9. Security

- Your licence key is never stored in plaintext on our servers — only its
  SHA-256 hash (`License.key_hash`). A database compromise would not itself
  reveal a working key.
- Licence and authorization data in transit is signed (Ed25519) and verified
  offline against a key baked into the app, so Prism keeps enforcing your
  licence correctly even if it can't reach us, without trusting an
  unauthenticated response.
- Admin access to customer records requires a token compared in constant
  time and is rate-limited against guessing.

## 10. Children's privacy

Prism is B2B software sold to firms for their own staff's use. It is not
directed at, and we do not knowingly collect data about, children.

## 11. Changes to this policy

We'll update the "Last updated" date above and, for a material change, tell
existing licence holders directly rather than relying on someone noticing a
diff.

## 12. Contact / Grievance Officer

**Alphakore**
Email: contactus@alphakore.org
Phone: 798476995
Website: https://alphakore.org

Grievance Officer / Data contact: Parth Soni — CTO, Alphakore
*(Confirm this designation formally before publishing — under applicable
Indian data-protection rules, a named Grievance Officer with a stated
response-time commitment is typically required, not just a general contact.)*
