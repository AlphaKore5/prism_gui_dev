"""No e-mail is ever guessed; every address says where it came from.

The owner, 24-Sep-2026, looking at an exported sheet of 52 addresses: "could
you look and tell if prism found these mails using apollo key?" None were
found by anything — every one was firstname.lastname@<the company's website>,
not one confirmed, and ABB's were on new.abb.com (its website, not its mail).
His rule since: "the emails shouldn't be guessed any day.. its gonna be usage
of hunter + apollo only to find mails." These tests hold Prism to it:

  · enrich never writes an address (only the company's real domain);
  · an address an older build guessed is recognised exactly — and set aside,
    never shown, sent or exported — while a real one from a sheet never is;
  · the finders are Hunter, then Apollo; Hunter asks by the company's name
    when no domain is known; nobody found means no address;
  · the sheet says where each address came from (Email source), its LinkedIn
    column holds LinkedIn only, and the Exa page a person was found on is its
    own column (Profile link);
  · a workbook's tabs import together ("All sheets": his AE _ Leads.xlsx had
    its companies on two tabs, and only the first was ever read).
"""
from __future__ import annotations

import os
import shutil
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from prospector import enrich as E                                  # noqa: E402
from prospector import exports as X                                 # noqa: E402
from prospector import gateway as G                                 # noqa: E402
from prospector import identity as I                                # noqa: E402
from prospector import importing as IMP                             # noqa: E402
from prospector import verify as V                                  # noqa: E402
from prospector.models import Lead                                  # noqa: E402


def _lead(name="Asha Rao", company="Rao Works Pvt Ltd", email="", **extra):
    lead = Lead(name=name, title="Owner", company=company, email=email)
    lead.extra.update(extra)
    return lead


class _Reply:
    def __init__(self, data):
        self._data = data

    def json(self):
        return {"data": self._data}


class _Http:
    """A reply with its status, the way requests hands one back."""

    def __init__(self, status, body):
        self.status_code, self._body, self.headers = status, body, {}

    def json(self):
        return self._body


class NothingIsGuessed(unittest.TestCase):

    def test_enrich_keeps_the_domain_and_writes_no_address(self):
        lead = _lead()
        with mock.patch.object(E, "_real_domain", return_value="raoworks.in"):
            E.enrich([lead], "exa-key")
        self.assertEqual(lead.email, "")
        self.assertEqual(lead.extra["company_domain"], "raoworks.in")

    def test_no_real_site_found_means_no_made_up_domain_either(self):
        lead = _lead()
        with mock.patch.object(E, "_real_domain", return_value=""):
            E.enrich([lead], "exa-key")
        self.assertNotIn("company_domain", lead.extra)      # not "raoworks.com"
        self.assertEqual(lead.email, "")

    def test_an_old_guess_is_recognised_and_set_aside(self):
        guess = _lead("Meera Nair Fixture", "Fixture Works Ltd", "meera.fixture@new.fixtureworks.in",
                      company_domain="new.fixtureworks.in", email_check="unknown")
        self.assertTrue(E.is_guess(guess))
        self.assertTrue(E.forget_guess(guess))
        self.assertEqual(guess.email, "")
        self.assertEqual(guess.extra["guessed_email"], "meera.fixture@new.fixtureworks.in")
        self.assertNotIn("email_check", guess.extra)        # the check was on the guess
        self.assertFalse(E.forget_guess(guess))             # once is enough

    def test_a_real_address_is_never_taken_for_a_guess(self):
        # The same first.last pattern — but from the owner's sheet (no
        # company_domain: only enrich ever set one on a lead with no address)…
        sheet = _lead("Asha Rao", "Fixture Works Ltd", "asha.rao@fixtureworks.in")
        self.assertFalse(E.is_guess(sheet))
        # …or found by Apollo / Hunter, which say so.
        for source in ("apollo", "hunter", "sheet", "you"):
            found = _lead("Asha Rao", "Fixture Works", "asha.rao@fixtureworks.in",
                          company_domain="fixtureworks.in", email_source=source)
            self.assertFalse(E.is_guess(found), source)


class TheFindersAreHunterThenApollo(unittest.TestCase):

    def test_hunter_then_apollo_and_nothing_else(self):
        # 27-Sep-2026: the code used to disagree with this file's own module
        # docstring ("the finders are Hunter, then Apollo") — Apollo ran
        # first. Fixed to match (the owner: "our main will always be hunter").
        self.assertEqual([name for _k, name, _f in V._FINDERS], ["Hunter", "Apollo"])

    def test_a_website_subdomain_is_not_asked_for_mail(self):
        self.assertEqual(V._registrable("new.abb.com"), "abb.com")
        self.assertEqual(V._registrable("www.parleelizabeth.com"), "parleelizabeth.com")
        self.assertEqual(V._registrable("acme.co.in"), "acme.co.in")
        self.assertEqual(V._registrable("mail.acme.co.in"), "acme.co.in")

    def test_hunter_asks_by_the_company_name_when_no_domain_is_known(self):
        asked = []
        with mock.patch("requests.get", side_effect=lambda url, params=None, timeout=None: (
                asked.append(params), _Reply({"email": "asha.rao@raoworks.in"}))[1]):
            lead = _lead()
            V.find_and_verify(lead, {"hunter_api_key": "h"})
        self.assertEqual(asked[0]["company"], "Rao Works Pvt Ltd")
        self.assertNotIn("domain", asked[0])
        self.assertEqual((lead.email, lead.extra["email_source"]),
                         ("asha.rao@raoworks.in", "hunter"))

    def test_hunter_asks_at_the_companys_own_domain(self):
        asked = []
        with mock.patch("requests.get", side_effect=lambda url, params=None, timeout=None: (
                asked.append(params), _Reply({}))[1]):
            V.find_and_verify(_lead(company_domain="new.abb.com"), {"hunter_api_key": "h"})
        self.assertEqual(asked[0]["domain"], "abb.com")

    def test_apollo_is_asked_when_hunter_knows_nobody(self):
        with mock.patch("requests.get", return_value=_Reply({})), \
                mock.patch.object(V, "_apollo_find",
                                  return_value=("asha@raoworks.in", "valid")) as apollo:
            # _FINDERS holds the function itself: patch the list's entry too.
            finders = [(k, n, (apollo if n == "Apollo" else f)) for k, n, f in V._FINDERS]
            with mock.patch.object(V, "_FINDERS", finders):
                lead = _lead()
                V.find_and_verify(lead, {"hunter_api_key": "h", "apollo_api_key": "a"})
        self.assertEqual((lead.email, lead.extra["email_source"]),
                         ("asha@raoworks.in", "apollo"))

    def test_nobody_found_means_no_address(self):
        with mock.patch("requests.get", return_value=_Reply({})):
            lead = _lead()
            V.find_and_verify(lead, {"hunter_api_key": "h"})
        self.assertEqual(lead.email, "")
        self.assertNotIn("email_source", lead.extra)

    def test_a_confirmed_address_from_a_sheet_spends_no_finder_credit(self):
        lead = _lead(email="asha@raoworks.in", email_source="sheet")
        finder = mock.Mock(return_value=("other@raoworks.in", "valid"))
        with mock.patch.object(V, "verify_email", return_value="valid"), \
                mock.patch.object(V, "_FINDERS", [("hunter_api_key", "Hunter", finder)]):
            V.find_and_verify(lead, {"hunter_api_key": "h", "reoon_api_key": "r"})
        finder.assert_not_called()
        self.assertEqual((lead.email, lead.extra["email_check"]),
                         ("asha@raoworks.in", "valid"))


class TheCompanysDomainIsFoundBeforeTheFindersAsk(unittest.TestCase):
    """27-Sep-2026, the owner's real 50-lead run: Hunter answered nothing for
    "company=Asian Paints" but found its CEO instantly for "domain=
    asianpaints.com" — enrich.enrich (one Exa lookup per company) was built
    and tested, but nothing ever called it, so every finder was always asked
    by a company's bare name. verify.find_domains is that missing call."""

    def test_an_exa_key_looks_the_domain_up_once_per_company(self):
        leads = [_lead("Asha Rao", "Rao Works Pvt Ltd"), _lead("Bala Iyer", "Rao Works Pvt Ltd")]
        with mock.patch.object(E, "_real_domain", return_value="raoworks.in") as real_domain:
            V.find_domains(leads, {"exa_api_key": "exa-k"})
        real_domain.assert_called_once_with("Rao Works Pvt Ltd", "exa-k")
        self.assertEqual([l.extra["company_domain"] for l in leads], ["raoworks.in"] * 2)

    def test_no_exa_key_is_a_silent_no_op(self):
        lead = _lead()
        with mock.patch.object(E, "enrich") as enriched:
            V.find_domains([lead], {})
            V.find_domains([lead], None)
        enriched.assert_not_called()
        self.assertNotIn("company_domain", lead.extra)

    def test_a_pooled_cfg_asks_with_the_pool_sentinel(self):
        from prospector import gateway as G
        lead = _lead()
        with mock.patch.object(E, "enrich") as enriched:
            V.find_domains([lead], {"exa_api_key": G.POOL_KEY})
        enriched.assert_called_once_with([lead], G.POOL_KEY)

    def test_verify_reachable_looks_up_only_the_hot_and_warm_slice(self):
        """The company lookup runs on the SAME slice the finders then work
        through (hot/warm, capped by limit) — not the whole dossier list."""
        from prospector.models import HOT, WARM, COLD
        rows = []
        for i, verdict in enumerate((HOT, WARM, COLD)):
            lead = _lead(f"P{i}", f"Company {i}")
            dossier = mock.Mock(lead=lead, verdict=verdict)
            rows.append(dossier)
        seen = []
        with mock.patch.object(V, "find_domains", side_effect=lambda ls, cfg: seen.append(list(ls))), \
                mock.patch.object(V, "find_and_verify"):
            V.verify_reachable(rows, {"hunter_api_key": "h"}, cfg={"exa_api_key": "exa-k"})
        self.assertEqual(seen, [[rows[0].lead, rows[1].lead]])      # hot, warm — not cold

    def test_with_no_cfg_verify_reachable_behaves_exactly_as_before(self):
        """Old callers that never learnt about `cfg` keep working — the
        domain step is just skipped, same as when find_domains has no key."""
        from prospector.models import HOT
        lead = _lead()
        dossier = mock.Mock(lead=lead, verdict=HOT)
        with mock.patch.object(E, "enrich") as enriched, \
                mock.patch.object(V, "find_and_verify") as checked:
            done = V.verify_reachable([dossier], {"hunter_api_key": "h"})
        enriched.assert_not_called()
        checked.assert_called_once_with(lead, {"hunter_api_key": "h"}, {})
        self.assertEqual(done, 1)


class EmailsFoundByDomainBeforeThePerPersonAsk(unittest.TestCase):
    """02-Oct-2026: Hunter's Domain Search is a plain database lookup — confirmed
    live, the same session this was built: asianpaints.com and tatamotors.com each
    returned 10 real named people, IDENTICALLY on a repeat call (contrast the
    Fiber test the same day: 18 of 19 overlapping leads got a DIFFERENT number
    each run — an agent guessing, not a database). One Domain Search per company
    can resolve several named leads at once, instead of asking Hunter's ordinary
    per-person finder once each — same email_find credit either way; this changes
    what Hunter is asked, never what it costs."""

    def test_one_call_resolves_everyone_already_on_file_at_that_company(self):
        a = _lead("Asha Rao", "Acme", company_domain="acme.com")
        b = _lead("Bala Iyer", "Acme Industries", company_domain="acme.com")
        asked = []

        def get(url, params=None, timeout=None):
            asked.append(params)
            return _Http(200, {"data": {"emails": [
                {"first_name": "Asha", "last_name": "Rao", "value": "asha.rao@acme.com", "type": "personal"},
                {"first_name": "Bala", "last_name": "Iyer", "value": "bala.iyer@acme.com", "type": "personal"}]}})
        with mock.patch("requests.get", side_effect=get):
            V.find_emails_by_domain([a, b], {"hunter_api_key": "h"})
        self.assertEqual((a.email, a.extra["email_source"]), ("asha.rao@acme.com", "hunter"))
        self.assertEqual((b.email, b.extra["email_source"]), ("bala.iyer@acme.com", "hunter"))
        self.assertEqual(len(asked), 1)                       # one call for both, not two
        self.assertEqual(asked[0]["domain"], "acme.com")

    def test_a_generic_address_is_never_matched_to_a_named_lead(self):
        a = _lead("Asha Rao", "Acme", company_domain="acme.com")
        with mock.patch("requests.get", return_value=_Http(200, {"data": {"emails": [
                {"first_name": "", "last_name": "", "value": "sales@acme.com", "type": "generic"}]}})):
            V.find_emails_by_domain([a], {"hunter_api_key": "h"})
        self.assertEqual(a.email, "")

    def test_whoever_it_misses_is_left_untouched_for_find_and_verify(self):
        a = _lead("Asha Rao", "Acme", company_domain="acme.com")     # not on file there
        with mock.patch("requests.get", return_value=_Http(200, {"data": {"emails": []}})):
            V.find_emails_by_domain([a], {"hunter_api_key": "h"})
        self.assertEqual((a.email, a.extra.get("email_source")), ("", None))

    def test_a_lead_with_no_domain_yet_is_simply_skipped(self):
        a = _lead("Asha Rao", "Acme")                          # find_domains found nothing
        called = []
        with mock.patch("requests.get", side_effect=lambda *a, **k: called.append(1) or _Http(200, {})):
            V.find_emails_by_domain([a], {"hunter_api_key": "h"})
        self.assertEqual(called, [])

    def test_someone_who_already_has_an_address_is_not_asked_for_again(self):
        a = _lead("Asha Rao", "Acme", "asha@sheet.example", company_domain="acme.com")
        called = []
        with mock.patch("requests.get", side_effect=lambda *a, **k: called.append(1) or _Http(200, {})):
            V.find_emails_by_domain([a], {"hunter_api_key": "h"})
        self.assertEqual(called, [])

    def test_no_hunter_key_is_a_silent_no_op(self):
        a = _lead("Asha Rao", "Acme", company_domain="acme.com")
        called = []
        with mock.patch("requests.get", side_effect=lambda *a, **k: called.append(1) or _Http(200, {})):
            V.find_emails_by_domain([a], {})
        self.assertEqual((called, a.email), ([], ""))

    def test_a_broken_call_does_not_crash_and_leaves_the_fallback_its_turn(self):
        a = _lead("Asha Rao", "Acme", company_domain="acme.com")
        with mock.patch("requests.get", return_value=_Http(500, {})):
            V.find_emails_by_domain([a], {"hunter_api_key": "h"})     # must not raise
        self.assertEqual(a.email, "")
        with mock.patch("requests.get", side_effect=ConnectionError("down")):
            V.find_emails_by_domain([a], {"hunter_api_key": "h"})     # must not raise either
        self.assertEqual(a.email, "")

    def test_a_pooled_call_batches_across_companies_and_applies_results_by_ref(self):
        a = _lead("Asha Rao", "Acme", company_domain="acme.com")
        b = _lead("Cy Lund", "Globex", company_domain="globex.com")
        with mock.patch.object(G, "find_emails", return_value=[
                {"ref": "p0_0", "email": "asha.rao@acme.com", "provider": "hunter"},
                {"ref": "p1_0", "email": "cy.lund@globex.com", "provider": "hunter"}]) as find:
            V.find_emails_by_domain([a, b], {"pool": G.POOL_KEY})
        self.assertEqual((a.email, b.email), ("asha.rao@acme.com", "cy.lund@globex.com"))
        [(batch,)] = [c.args for c in find.call_args_list]
        self.assertEqual({(p["ref"], p["domain"]) for p in batch},
                         {("p0_0", "acme.com"), ("p1_0", "globex.com")})

    def test_pooled_never_falls_through_to_a_customers_own_key(self):
        a = _lead("Asha Rao", "Acme", company_domain="acme.com")
        with mock.patch.object(G, "find_emails", return_value=[]), \
                mock.patch("requests.get", side_effect=AssertionError("asked Hunter directly, not the pool")):
            V.find_emails_by_domain([a], {"pool": G.POOL_KEY, "hunter_api_key": "h"})
        self.assertEqual(a.email, "")


class AFinderThatRefusesTheAccountIsAskedOnce(unittest.TestCase):
    """24-Sep-2026, the owner's Find e-mails on 159 people: Apollo answered
    every lookup 403 API_INACCESSIBLE (people/match is not in a Free plan) and
    Hunter 429 (the month's searches used up). Both were read as "nobody
    found", every person was asked of both, and he was told nothing. A refusal
    of the ACCOUNT is now asked once a batch and named; one person nobody
    knows, or a per-second limit, is still just "not found"."""

    _FREE_PLAN = {"error": "The api/v1/people/match API is not included in your "
                           "Free plan and is not accessible, even with a master key.",
                  "error_code": "API_INACCESSIBLE"}
    _QUOTA = {"errors": [{"id": "too_many_requests", "code": 429,
                          "details": "You've reached the limit for the number of "
                                     "searches per billing period included in your plan."}]}

    def _apollo_says(self, status, body):
        from prospector import apollo
        calls = []

        def post(url, json=None, headers=None, timeout=None):
            calls.append(json)
            return _Http(status, body)

        return calls, mock.patch.object(apollo, "_requests",
                                        return_value=mock.Mock(post=post))

    def test_apollo_on_a_free_plan_is_asked_once_and_says_so(self):
        calls, patched = self._apollo_says(403, self._FREE_PLAN)
        refused = {}
        with patched:
            for lead in (_lead("Asha Rao"), _lead("Bala Iyer")):
                V.find_and_verify(lead, {"apollo_api_key": "a"}, refused)
        self.assertEqual(len(calls), 1)
        self.assertEqual(refused["Apollo"], "Apollo: finding e-mails isn't in your Free "
                                            "plan. Only paid Apollo plans include it.")

    def test_a_trial_of_a_paid_plan_is_named_as_the_trial_it_is(self):
        """25-Sep-2026: the owner started Apollo's Basic trial and asked if it
        helps — Apollo refuses a trial too, and saying "Free" would have told
        him nothing changed when something had."""
        trial = {"error": "The api/v1/people/match API is not included in your "
                          "Basic (Trial) plan and is not accessible, even with a "
                          "master key. All paid plans include full API access.",
                 "error_code": "API_INACCESSIBLE"}
        _calls, patched = self._apollo_says(403, trial)
        refused = {}
        with patched:
            V.find_and_verify(_lead(), {"apollo_api_key": "a"}, refused)
        self.assertIn("your Basic (Trial) plan", refused["Apollo"])

    def test_a_refusal_without_apollos_words_still_says_what_to_do(self):
        _calls, patched = self._apollo_says(403, {"error_code": "API_INACCESSIBLE"})
        refused = {}
        with patched:
            V.find_and_verify(_lead(), {"apollo_api_key": "a"}, refused)
        self.assertEqual(refused["Apollo"], "Apollo: finding e-mails isn't in your "
                                            "Apollo plan. Only paid Apollo plans include it.")

    def test_a_key_apollo_does_not_know_is_named_too(self):
        _calls, patched = self._apollo_says(401, {})
        refused = {}
        with patched:
            V.find_and_verify(_lead(), {"apollo_api_key": "a"}, refused)
        self.assertIn("not accepted", refused["Apollo"])

    def test_one_person_apollo_cannot_take_is_not_a_refusal(self):
        _calls, patched = self._apollo_says(422, {})
        refused = {}
        with patched:
            V.find_and_verify(_lead(), {"apollo_api_key": "a"}, refused)
        self.assertEqual(refused, {})

    def test_hunters_spent_quota_is_asked_once_and_says_when_it_comes_back(self):
        asked = []

        def get(url, params=None, timeout=None):
            asked.append(url)
            if url == V.ACCOUNT:                  # free: when the searches come back
                return _Http(200, {"data": {"reset_date": "2026-09-27"}})
            return _Http(429, self._QUOTA)

        refused = {}
        with mock.patch("requests.get", side_effect=get):
            for lead in (_lead("Asha Rao"), _lead("Bala Iyer")):
                V.find_and_verify(lead, {"hunter_api_key": "h"}, refused)
        self.assertEqual(asked.count(V.FINDER), 1)
        self.assertIn("used up", refused["Hunter"])
        self.assertIn("27 Sep", refused["Hunter"])

    def test_hunters_per_second_limit_is_not_a_refusal(self):
        burst = {"errors": [{"id": "too_many_requests", "code": 429,
                             "details": "You have reached the rate limit."}]}
        refused = {}
        with mock.patch("requests.get", return_value=_Http(429, burst)):
            V.find_and_verify(_lead(), {"hunter_api_key": "h"}, refused)
        self.assertEqual(refused, {})

    def test_the_other_finder_is_still_asked(self):
        """27-Sep-2026: Hunter is asked first now (our main finder) — a
        refusal from it does not stop Apollo being asked for the SAME lead."""
        asked = []

        def get(url, params=None, timeout=None):
            asked.append(url)
            if url == V.ACCOUNT:
                return _Http(200, {"data": {"reset_date": "2026-09-27"}})
            return _Http(429, self._QUOTA)

        refused = {}
        apollo = mock.Mock(return_value=("asha.rao@raoworks.in", "valid"))
        # _FINDERS holds the function itself: patch the list's entry too.
        finders = [(k, n, (apollo if n == "Apollo" else f)) for k, n, f in V._FINDERS]
        with mock.patch("requests.get", side_effect=get), \
                mock.patch.object(V, "_FINDERS", finders):
            lead = _lead()
            V.find_and_verify(lead, {"hunter_api_key": "h", "apollo_api_key": "a"},
                              refused)
        self.assertEqual(asked.count(V.FINDER), 1)
        self.assertEqual((lead.email, lead.extra["email_source"]),
                         ("asha.rao@raoworks.in", "apollo"))
        self.assertIn("Hunter", refused)

    def test_without_a_shared_dict_a_refusal_still_never_ends_a_run(self):
        _calls, patched = self._apollo_says(403, self._FREE_PLAN)
        with patched:
            lead = _lead()
            V.find_and_verify(lead, {"apollo_api_key": "a"})
        self.assertEqual(lead.email, "")


class TheSheetSaysWhereEachAddressCameFrom(unittest.TestCase):

    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.dir, True)

    def test_email_source_in_words(self):
        cases = {"hunter": "Hunter", "apollo": "Apollo", "sheet": "Your sheet",
                 "you": "Typed by you"}
        for source, words in cases.items():
            self.assertEqual(X.email_source_of(_lead(email="a@b.in", email_source=source)),
                             words)
        self.assertEqual(X.email_source_of(_lead(email="a@b.in")), "Your sheet")
        self.assertEqual(X.email_source_of(_lead()), "")    # no address, no source

    def test_the_leads_sheet_columns(self):
        import openpyxl
        found = _lead(email="asha@raoworks.in", email_source="hunter",
                      linkedin="https://www.linkedin.com/in/asha-rao")
        exa = _lead("Bo Lund", "Lund Steel", profile_url="https://exa.ai/library/person/x1")
        stale = _lead("Cy Ng", "Ng Works", linkedin="https://exa.ai/library/person/x2")
        path = os.path.join(self.dir, "Prism leads.xlsx")
        with mock.patch.object(X, "build_email_checks", return_value={}):   # no DNS
            X.leads_xlsx([found, exa, stale], path)
        ws = openpyxl.load_workbook(path).active
        head = [c.value for c in ws[1]]
        for col in ("E-mail", "Email check", "Email source", "LinkedIn", "Profile link"):
            self.assertIn(col, head)
        rows = {r[head.index("Name")]: r for r in ws.iter_rows(min_row=2, values_only=True)}
        at = head.index
        self.assertEqual(rows["Asha Rao"][at("Email source")], "Hunter")
        self.assertEqual(rows["Asha Rao"][at("LinkedIn")], "https://www.linkedin.com/in/asha-rao")
        self.assertIn(rows["Bo Lund"][at("LinkedIn")], (None, ""))
        self.assertEqual(rows["Bo Lund"][at("Profile link")], "https://exa.ai/library/person/x1")
        # An old run's Exa link filed as LinkedIn still lands in Profile link.
        self.assertIn(rows["Cy Ng"][at("LinkedIn")], (None, ""))
        self.assertEqual(rows["Cy Ng"][at("Profile link")], "https://exa.ai/library/person/x2")


class LinkedInIsLinkedInOnly(unittest.TestCase):

    def test_an_exa_page_is_moved_off_linkedin_and_keeps_who_they_are(self):
        lead = _lead(linkedin="https://exa.ai/library/person/r2d9p7b03m5")
        before = I.keys_of(lead)
        self.assertTrue(I.move_profile_link(lead))
        self.assertEqual(lead.extra, {"profile_url": "https://exa.ai/library/person/r2d9p7b03m5"})
        self.assertEqual(I.keys_of(lead), before)           # the same person to Prism

    def test_a_real_linkedin_stays(self):
        lead = _lead(linkedin="https://in.linkedin.com/in/asha-rao")
        self.assertFalse(I.move_profile_link(lead))
        self.assertTrue(I.is_linkedin(lead.extra["linkedin"]))

    def test_a_search_result_files_its_link_where_it_belongs(self):
        from prospector import source as S

        def row(url):
            return {"url": url, "entities": [{"type": "person", "properties": {
                "name": "Asha Rao", "location": "Pune, India",
                "workHistory": [{"title": "Owner", "company": {"name": "Rao Works"},
                                 "dates": {"from": "2020-01-01", "to": None}}]}}]}
        exa = row("https://exa.ai/library/person/x1")
        lead = S._lead_of(exa, exa["entities"][0], "Tooling")
        self.assertEqual(lead.extra.get("profile_url"), "https://exa.ai/library/person/x1")
        self.assertNotIn("linkedin", lead.extra)
        li = row("https://www.linkedin.com/in/asha-rao")
        lead = S._lead_of(li, li["entities"][0], "Tooling")
        self.assertEqual(lead.extra.get("linkedin"), "https://www.linkedin.com/in/asha-rao")


class EveryTabImportsTogether(unittest.TestCase):

    def setUp(self):
        import openpyxl
        self.dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.dir, True)
        self.path = os.path.join(self.dir, "AE _ Leads.xlsx")
        wb = openpyxl.Workbook()
        a = wb.active
        a.title = "ChatGPT"
        a.append(["Company Name", "Website", "Lead Quality"])
        a.append(["Parle Elizabeth Tools", "parleelizabeth.com", "High"])
        a.append(["ACG Pampac", "acg-world.com", "Medium"])
        b = wb.create_sheet("Perplexity")
        b.append(["company name", "Website", "Source URL"])     # same column, other case
        b.append(["IDMC Limited", "idmc.company", "https://example.com/idmc"])
        wb.save(self.path)

    def test_all_sheets_is_one_table_with_the_tab_on_each_row(self):
        name, header, rows = IMP.read_table(self.path, IMP.ALL_SHEETS)
        self.assertEqual(name, IMP.ALL_SHEETS_NAME)
        self.assertEqual(header, ["Company Name", "Website", "Lead Quality", "Source URL",
                                  IMP.SHEET_COLUMN])
        self.assertEqual(len(rows), 3)
        idmc = rows[2]
        self.assertEqual((idmc[0], idmc[1], idmc[3], idmc[4]),
                         ("IDMC Limited", "idmc.company", "https://example.com/idmc",
                          "Perplexity"))
        self.assertEqual(idmc[2], "")                       # that tab has no Lead Quality
        companies, _skipped = IMP.accounts_from_rows(
            header, rows, IMP.guess_mapping(header, "accounts"))
        self.assertEqual([c["name"] for c in companies],
                         ["Parle Elizabeth Tools", "ACG Pampac", "IDMC Limited"])

    def test_one_tab_is_still_one_tab(self):
        name, _header, rows = IMP.read_table(self.path, "Perplexity")
        self.assertEqual((name, len(rows)), ("Perplexity", 1))

    def test_a_sheets_own_address_says_so(self):
        import openpyxl
        path = os.path.join(self.dir, "people.xlsx")
        wb = openpyxl.Workbook()
        wb.active.append(["Name", "Company", "Email"])
        wb.active.append(["Asha Rao", "Rao Works", "asha@raoworks.in"])
        wb.save(path)
        _name, header, rows = IMP.read_table(path)
        leads, _skipped = IMP.contacts_from_rows(header, rows,
                                                 IMP.guess_mapping(header, "contacts"))
        self.assertEqual(leads[0].extra["email_source"], "sheet")


if __name__ == "__main__":
    unittest.main()
