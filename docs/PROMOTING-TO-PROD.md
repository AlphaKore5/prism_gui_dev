# Promoting a dev release to production

The owner's rule (2026-10-27): until they say **"move to prod"**, every step is built so that,
the moment they do, customers on **1.6.10** (who read Hitarth's repository) see the download
badge and can update. Dev is a rehearsal of exactly what production will do.

`python3 devtools/promote_check.py` is the gate. Run it at the end of every dev release. It
changes nothing; it reads, runs the real-1.6.10 tests, and prints the steps below for the
version in the tree. `--dev-proof` also fetches the published dev release the way a 1.6.10
client would.

## What a 1.6.10 customer does, and so what must be true

| 1.6.10 behaviour | Therefore |
|---|---|
| Reads one address: `HitarthTrivedi/prism_gui`, GitHub's "latest" release | the production release is published there, as a normal (non-pre) release; the organisation copy is a mirror only |
| Trusts one key, `u1` | only the owner's offline key signs it; never CI, never an assistant |
| Never checks by itself. Learns of an update from the licence server's **Production** latest version (the banner) or from Settings > Check for updates | the banner appears only when you raise Production's latest version; a pressed Check for updates works as soon as the signed lists are live |
| Download fetches the signed list and every file, checking size and hash, then restarts | files are published **before** the signed list (so nobody is offered a version with files missing) |
| Ignores signed-list fields it does not know (rollout, min updater, revoke) | those may be used freely; they do not apply to the first hop |
| Rolls back to 1.6.10 if the new build does not start | a build that starts but misbehaves cannot be rolled back automatically; this is why the real-machine checklist exists |

## The steps (who acts)

1. You say "move to prod". Nothing visible changes yet.
2. Push the exact tested commit to `HitarthTrivedi/prism_gui` and tag `v<version>`. **Needs your explicit
   OK in that message.** CI builds the production installers (there are no dev settings in that repository)
   and runs the tests first; the release waits for them.
3. Sign the lists with the production key. **You, offline.**
   `python3 devtools/release_all.py v<version> <run id>` publishes to Hitarth's repository, then mirrors to the
   organisation. One platform first (Windows), then the rest. GitHub allows about 5,000 requests an hour, so a full
   release takes hours and the script resumes.
4. `python3 devtools/check_as_old_client.py --expect-version <version>` must say PASS on every platform. A FAIL
   means customers on that platform will not see the update: fix it, do not raise the banner.
5. Update your own real 1.6.10 installs (Windows first, then Mac), then phone the first customers.
6. Raise Production's latest version in the licence console. It asks first and shows how many computers
   will see the banner.
7. Watch Releases > Who has updated.

## Never

- Promote a commit that was not a dev release (the gate fails it).
- Reuse a production version number.
- Raise the Production banner before step 4 passes: customers would be offered a version that is not there.
- Change the dev numbers to "test" production. Mark a tester's computer as Development instead (console).
- Let a dev build and production share a data folder.
