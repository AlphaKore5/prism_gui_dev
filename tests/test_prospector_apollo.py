"""Apollo costs money per person — prove the run spends as little as it can.

Apollo's people search is free and tells you almost nothing (no e-mail, a
half-hidden surname); revealing a person costs a credit. So every line of
prospector/apollo.py is about the order of operations, and that is what these
tests pin:

  · the filters reach Apollo as Apollo's own parameters — above all "anywhere
    except India", which has to be sent as the countries that are LEFT, because
    Apollo has no exclusion parameter and an Indian who reaches the reveal has
    already been paid for;
  · the free pages come first, and anyone an earlier session pulled (by Apollo
    id) or this run already queued is dropped BEFORE a bulk_match call;
  · reveals go ten at a time and never exceed what the target still needs;
  · what Apollo cannot express — an excluded place that slipped through, a
    title exclusion — is enforced after the reveal, counted, and does not take
    a slot;
  · every refusal Apollo can send (401 / 403 / 422 / 429) becomes a message the
    owner can act on, and a network failure mid-run keeps the list it has;
  · the pieces the rest of the pipeline relies on: the lead mapping, the "a:"
    identity key, and Apollo's place in the verify waterfall.

No network and no credits: apollo._post (or, for the HTTP layer itself,
apollo._requests) is a recorder.
"""
from __future__ import annotations

import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from prospector import apollo, filters, identity, places, verify   # noqa: E402
from prospector.filters import Facet, SearchSpec                   # noqa: E402
from prospector.identity import SeenIndex                          # noqa: E402
from prospector.models import Lead                                 # noqa: E402


# ── the spec most tests run: Plant Heads, heads, anywhere except India, 1-5k ──

def _spec(**over) -> SearchSpec:
    raw = {"job_titles": {"include": ["Plant Head"]},
           "seniority": {"include": ["head"]},
           "locations": {"exclude": ["India"]},
           "headcount": ["1001-5000"]}
    raw.update(over)
    return SearchSpec.from_dict(raw)


def _card(i: int, company: str = "Acme Motors", **over) -> dict:
    """One free search row, as Apollo sends it: an id, a first name, an
    obfuscated surname, no e-mail."""
    first = over.get("first", "Rahul")
    row = {"id": f"apollo{i}", "first_name": first, "last_name": "S.",
           "last_name_obfuscated": True, "name": f"{first} S.",
           "title": over.get("title", "Plant Head"),
           "has_email": True,
           "organization": {"name": company, "primary_domain": "acme.com"}}
    if over.get("linkedin"):
        row["linkedin_url"] = over["linkedin"]
    return row


def _person(i: int, company: str = "Acme Motors", **over) -> dict:
    """The same person REVEALED — what one credit buys."""
    first = over.get("first", "Rahul")
    last = over.get("last", f"Shah{i}")
    return {"id": f"apollo{i}", "first_name": first, "last_name": last,
            "title": over.get("title", "Plant Head"),
            "email": over.get("email", f"{first.lower()}.{last.lower()}@acme.com"),
            "email_status": over.get("email_status", "verified"),
            "linkedin_url": over.get("linkedin",
                                     f"https://www.linkedin.com/in/{first.lower()}{i}"),
            "city": over.get("city", "Dubai"), "state": over.get("state", ""),
            "country": over.get("country", "United Arab Emirates"),
            "employment_history": [{"current": True, "start_date": "2021-04-01"},
                                   {"current": False, "start_date": "2016-01-01"}],
            "organization": {"name": company, "primary_domain": "acme.com",
                             "website_url": "https://www.acme.com",
                             "industry": "automotive",
                             "estimated_num_employees": over.get("headcount", 2500),
                             "annual_revenue": over.get("revenue", 250_000_000.0),
                             "city": over.get("hq_city", "Dubai"),
                             "country": over.get("hq_country", "United Arab Emirates")}}


class _Apollo:
    """Stands in for apollo._post: serves the cards a page at a time, reveals a
    person by id, and records every call so a test can read what was asked."""

    def __init__(self, cards, people=None, total=None):
        self.cards = list(cards)
        self.people = {p["id"]: p for p in (people or [])}
        self.total = len(self.cards) if total is None else total
        self.calls = []                      # (path, body)
        self.fail_search_on = 0              # nth search call raises _Unreachable

    def __call__(self, path, body, api_key, timeout=30):
        self.calls.append((path, body))
        if path == apollo.SEARCH:
            if self.fail_search_on and self.searches == self.fail_search_on:
                raise apollo._Unreachable(apollo.UNREACHABLE)
            page, per = int(body.get("page", 1)), int(body.get("per_page", 100))
            return {"total_entries": self.total,
                    "people": self.cards[(page - 1) * per:page * per]}
        if path == apollo.BULK_MATCH:
            return {"matches": [self.people.get(d.get("id"))
                                for d in body.get("details", [])]}
        return {}

    @property
    def searches(self) -> int:
        return sum(1 for path, _ in self.calls if path == apollo.SEARCH)

    @property
    def reveals(self) -> list:
        return [body for path, body in self.calls if path == apollo.BULK_MATCH]

    @property
    def revealed_ids(self) -> list:
        return [d.get("id") for body in self.reveals for d in body["details"]]


def _run(fake, spec=None, **kw):
    stats: dict = {}
    with mock.patch.object(apollo, "_post", fake):
        leads = apollo.search_people(spec or _spec(), "key", stats=stats, **kw)
    return leads, stats


# ── the parameters ────────────────────────────────────────────────────────────

class ParamsTest(unittest.TestCase):
    """`params_for` is pure, so every mapping is pinned without a network."""

    def test_except_india_is_sent_as_the_places_that_are_left(self):
        body = apollo.params_for(_spec())
        where = body["person_locations"]
        self.assertIn("United Arab Emirates", where)
        self.assertGreater(len(where), 50)          # the world, less one country
        # Not India, and not one of India's OWN names or places: a credit is
        # spent the moment one of them comes back.
        banned = set(places.aliases_of("India"))
        self.assertEqual([w for w in where if w.casefold() in banned], [])

    def test_includes_are_asked_for_as_given(self):
        body = apollo.params_for(SearchSpec.from_dict(
            {"locations": {"include": ["United Arab Emirates", "Singapore"]},
             "company_hq": {"include": ["Germany"]},
             "job_titles": {"include": ["Plant Head"]}}))
        self.assertEqual(body["person_locations"], ["United Arab Emirates", "Singapore"])
        self.assertEqual(body["organization_locations"], ["Germany"])

    def test_an_exclusion_inside_an_include_opens_it_up(self):
        body = apollo.params_for(SearchSpec.from_dict(
            {"locations": {"include": ["Asia"], "exclude": ["India"]},
             "job_titles": {"include": ["Plant Head"]}}))
        where = body["person_locations"]
        self.assertIn("Singapore", where)
        self.assertNotIn("India", where)
        self.assertNotIn("Mumbai", where)

    def test_titles_seniority_and_similar_titles(self):
        body = apollo.params_for(_spec())
        self.assertEqual(body["person_titles"], ["Plant Head"])
        self.assertIs(body["include_similar_titles"], True)
        self.assertEqual(body["person_seniorities"], ["head"])
        off = apollo.params_for(_spec(similar_titles=False))
        self.assertIs(off["include_similar_titles"], False)

    def test_titles_fall_back_to_the_roles_the_spec_spells_out(self):
        body = apollo.params_for(SearchSpec.from_dict(
            {"seniority": {"include": ["head"]}, "functions": {"include": ["operations"]}}))
        self.assertEqual(body["person_titles"], ["Head Operations"])
        # A seniority already points the search; the function word would only
        # narrow it to people whose title repeats it.
        self.assertNotIn("q_keywords", body)

    def test_functions_become_keywords_when_nothing_else_narrows(self):
        body = apollo.params_for(SearchSpec.from_dict(
            {"functions": {"include": ["operations", "quality"]}}))
        self.assertEqual(body["q_keywords"], "Operations Quality")

    def test_headcount_bands(self):
        self.assertEqual(apollo.params_for(_spec())["organization_num_employees_ranges"],
                         ["1001,5000"])
        top = apollo.params_for(_spec(headcount=["1-10", "10001+"]))
        self.assertEqual(top["organization_num_employees_ranges"],
                         ["1,10", "10001,1000000"])

    def test_revenue_is_one_span_over_the_chosen_bands(self):
        body = apollo.params_for(_spec(revenue=["10m-50m", "50m-100m"]))
        self.assertEqual(body["revenue_range[min]"], 10_000_000)
        self.assertEqual(body["revenue_range[max]"], 100_000_000)
        # The top band has no ceiling, so none is sent.
        open_ended = apollo.params_for(_spec(revenue=["gt1b"]))
        self.assertEqual(open_ended["revenue_range[min]"], 1_000_000_000)
        self.assertNotIn("revenue_range[max]", open_ended)
        self.assertNotIn("revenue_range[min]", apollo.params_for(_spec()))

    def test_the_industry_and_the_keywords_share_q_keywords(self):
        body = apollo.params_for(_spec(keywords={"include": ["IIoT"]}), "Auto Components")
        self.assertEqual(body["q_keywords"], "Auto Components IIoT")

    def test_nothing_longer_than_two_hundred_characters(self):
        # The live bug: a whole inter-stage brief reached the filters and Apollo
        # answered "Value too long: … exceeds 200 characters".
        spec = SearchSpec(job_titles=Facet(include=["Plant Head " + "x" * 300]))
        body = apollo.params_for(spec, "Automobile " + "y" * 400)
        for value in list(body["person_titles"]) + [body["q_keywords"]]:
            self.assertLessEqual(len(value), apollo.MAX_VALUE)
        self.assertEqual(len(body["person_titles"][0]), apollo.MAX_VALUE)

    def test_exclusions_apollo_cannot_take_are_never_sent(self):
        spec = _spec(job_titles={"include": ["Plant Head"], "exclude": ["Intern"]},
                     companies={"exclude": ["Tata Motors"]},
                     keywords={"exclude": ["recruitment"]})
        text = repr(apollo.params_for(spec, "Automobile")).casefold()
        for banned in ("intern", "tata", "recruitment", "india"):
            self.assertNotIn(banned, text)


# ── the sourcing run ──────────────────────────────────────────────────────────

class SearchTest(unittest.TestCase):

    def test_a_full_run_stops_at_target_and_pays_for_no_more(self):
        cards = [_card(i) for i in range(60)]
        fake = _Apollo(cards, [_person(i) for i in range(60)])
        leads, stats = _run(fake, target=12)
        self.assertEqual(len(leads), 12)
        self.assertEqual(stats["revealed"], 12)         # one credit each, no more
        self.assertEqual(stats["searched"], 60)
        self.assertEqual(stats["short_by"], 0)
        self.assertEqual(len(fake.reveals), 2)          # 10 + 2
        self.assertEqual([len(b["details"]) for b in fake.reveals], [10, 2])

    def test_reveals_never_exceed_what_the_target_still_needs(self):
        fake = _Apollo([_card(i) for i in range(60)], [_person(i) for i in range(60)])
        leads, stats = _run(fake, target=7)
        self.assertEqual(len(leads), 7)
        self.assertEqual([len(b["details"]) for b in fake.reveals], [7])
        self.assertEqual(stats["reveal_calls"], 1)

    def test_pages_until_the_target_can_be_filled(self):
        fake = _Apollo([_card(i) for i in range(10)], [_person(i) for i in range(10)])
        leads, stats = _run(fake, target=6, per_page=2)
        self.assertEqual(len(leads), 6)
        self.assertEqual(stats["search_calls"], 3)      # 3 pages × 2 = 6 cards
        self.assertEqual([b["page"] for p, b in fake.calls if p == apollo.SEARCH],
                         [1, 2, 3])

    def test_it_ends_when_the_candidates_run_out(self):
        fake = _Apollo([_card(i) for i in range(3)], [_person(i) for i in range(3)])
        leads, stats = _run(fake, target=25)
        self.assertEqual(len(leads), 3)
        self.assertEqual(stats["short_by"], 22)
        self.assertEqual(stats["search_calls"], 1)      # 3 of 3: nothing left to ask

    def test_max_pages_is_the_budget(self):
        fake = _Apollo([_card(i) for i in range(50)], [_person(i) for i in range(50)])
        leads, stats = _run(fake, target=25, per_page=1, max_pages=4)
        self.assertEqual(stats["search_calls"], 4)
        self.assertEqual(len(leads), 4)

    def test_industries_take_turns_so_one_cannot_eat_the_target(self):
        fake = _Apollo([_card(i) for i in range(10)], [_person(i) for i in range(10)])
        spec = _spec(industries={"include": ["Automobile", "Cement"]})
        _run(fake, spec, target=4, per_page=2)
        asked = [b["q_keywords"] for p, b in fake.calls if p == apollo.SEARCH]
        self.assertEqual(asked[:2], ["Automobile", "Cement"])

    def test_someone_an_earlier_session_pulled_costs_nothing(self):
        cards = [_card(i) for i in range(4)]
        fake = _Apollo(cards, [_person(i) for i in range(4)])
        stats: dict = {}
        # The ONLY thing the free row carries about him is his Apollo id.
        skip = SeenIndex(["a:apollo2"])
        with mock.patch.object(apollo, "_post", fake):
            leads = apollo.search_people(_spec(), "key", target=3, skip=skip, stats=stats)
        self.assertEqual(stats["skipped_seen"], 1)
        self.assertNotIn("apollo2", fake.revealed_ids)  # never reached a credit
        self.assertEqual(stats["revealed"], 3)
        self.assertEqual([l.extra["apollo_id"] for l in leads],
                         ["apollo0", "apollo1", "apollo3"])

    def test_the_same_person_on_two_pages_is_revealed_once(self):
        cards = [_card(0), _card(1), _card(0), _card(2)]
        fake = _Apollo(cards, [_person(i) for i in range(3)])
        leads, stats = _run(fake, target=3, per_page=2)
        self.assertEqual(stats["duplicates"], 1)
        self.assertEqual(fake.revealed_ids.count("apollo0"), 1)
        self.assertEqual(len(leads), 3)

    def test_two_people_who_both_read_rahul_s_are_two_people(self):
        # Search hides the surname, so every card here says "Rahul S." at Acme
        # Motors. Read as an identity that is one person — and the second real
        # Rahul would be dropped as a duplicate, unseen and unbilled-for.
        fake = _Apollo([_card(i) for i in range(3)], [_person(i) for i in range(3)])
        leads, stats = _run(fake, target=3)
        self.assertEqual(stats["duplicates"], 0)
        self.assertEqual(len(leads), 3)

    def test_someone_apollo_could_not_find_costs_no_credit(self):
        # matches[] holds a null where Apollo knows nobody — and charges nothing.
        fake = _Apollo([_card(i) for i in range(3)],
                       [_person(0), _person(2)])
        leads, stats = _run(fake, target=3)
        self.assertEqual(stats["revealed"], 2)
        self.assertEqual(len(leads), 2)

    def test_a_mislocated_person_is_dropped_after_the_reveal_and_counted(self):
        cards = [_card(i) for i in range(4)]
        people = [_person(0), _person(1, city="Pune", state="Maharashtra",
                          country="India"), _person(2), _person(3)]
        fake = _Apollo(cards, people)
        # A credit of margin over the target, so the one who slipped through can
        # be paid for AND the target still filled.
        leads, stats = _run(fake, target=3, budget=4)
        self.assertEqual(len(leads), 3)
        self.assertEqual(stats["filtered"], {"location": 1})
        # He cost a credit — which is exactly why the country list above matters.
        self.assertEqual(stats["revealed"], 4)
        self.assertNotIn("apollo1", [l.extra["apollo_id"] for l in leads])

    def test_with_no_margin_the_budget_is_the_target_and_the_list_comes_short(self):
        """The same four people, no margin asked for: the mislocated one is paid
        for out of the target's own credits, so the run hands back two and says
        it is one short — rather than buying a reveal the rail never promised."""
        cards = [_card(i) for i in range(4)]
        people = [_person(0), _person(1, city="Pune", state="Maharashtra",
                          country="India"), _person(2), _person(3)]
        fake = _Apollo(cards, people)
        leads, stats = _run(fake, target=3)
        self.assertEqual(len(leads), 2)
        self.assertEqual(stats["revealed"], 3)          # exactly what was asked
        self.assertEqual(stats["short_by"], 1)
        self.assertEqual(stats["filtered"], {"location": 1})

    def test_an_exclusion_apollo_cannot_express_cannot_run_up_the_bill(self):
        """The case the budget exists for. Apollo has no "not this title"
        parameter, so nine "Head of Sales" in ten are found out only after they
        are paid for — and each one leaves the target exactly as far away as it
        was. Uncapped, the run would pay its way down the whole index
        (max_pages × per_page); capped, it stops at the credits the rail
        promised and reports what it bought."""
        def title(i):
            return "Plant Head" if i % 10 == 0 else "Head of Sales, Plant"

        fake = _Apollo([_card(i) for i in range(200)],
                       [_person(i, title=title(i)) for i in range(200)])
        spec = _spec(job_titles={"include": ["Plant Head"], "exclude": ["Sales"]})
        leads, stats = _run(fake, spec, target=20, per_page=10)
        self.assertEqual(stats["revealed"], 20)         # not 200, not 2,000
        self.assertEqual(len(leads), 2)                 # one in ten passes
        self.assertEqual(stats["filtered"], {"job_title": 18})
        self.assertEqual(stats["short_by"], 18)         # and it says it is short
        # The free pages stop with the credits: paging on would only queue
        # people this run can no longer afford to look at.
        self.assertEqual(stats["search_calls"], 2)

    def test_an_excluded_title_is_enforced_after_the_reveal(self):
        # Apollo has no "not this title" parameter, so this is the only place it
        # can happen.
        cards = [_card(0), _card(1)]
        people = [_person(0, title="Head of Talent Acquisition"), _person(1)]
        fake = _Apollo(cards, people)
        spec = _spec(job_titles={"include": ["Plant Head"], "exclude": ["Talent Acquisition"]})
        leads, stats = _run(fake, spec, target=2)
        self.assertEqual([l.extra["apollo_id"] for l in leads], ["apollo1"])
        self.assertEqual(stats["filtered"], {"job_title": 1})

    def test_the_company_bands_are_checked_against_apollos_own_organization(self):
        cards = [_card(0), _card(1)]
        fake = _Apollo(cards, [_person(0, headcount=40), _person(1)])
        leads, stats = _run(fake, target=2)
        self.assertEqual([l.extra["apollo_id"] for l in leads], ["apollo1"])
        self.assertEqual(stats["filtered"], {"headcount": 1})

    def test_progress_is_reported_for_both_stages(self):
        fake = _Apollo([_card(i) for i in range(4)], [_person(i) for i in range(4)])
        seen = []
        with mock.patch.object(apollo, "_post", fake):
            apollo.search_people(_spec(), "key", target=4,
                                 on_progress=lambda *a: seen.append(a))
        self.assertEqual({row[0] for row in seen}, {"search", "reveal"})
        self.assertEqual(seen[-1], ("reveal", 4, 4, 4))

    def test_the_last_name_apollo_hid_is_never_sent_back_to_it(self):
        fake = _Apollo([_card(0)], [_person(0)])
        _run(fake, target=1)
        detail = fake.reveals[0]["details"][0]
        self.assertEqual(detail["id"], "apollo0")
        self.assertNotIn("last_name", detail)
        self.assertNotIn("name", detail)


# ── what a revealed person becomes ────────────────────────────────────────────

class LeadTest(unittest.TestCase):

    def _lead(self, **over) -> Lead:
        # A title-only spec: the mapping is what is on trial here, not the
        # filters (a Pune address would otherwise be dropped, rightly).
        spec = SearchSpec.from_dict({"job_titles": {"include": ["Plant Head"]}})
        fake = _Apollo([_card(0)], [_person(0, **over)])
        leads, _ = _run(fake, spec, target=1)
        return leads[0]

    def test_the_whole_mapping(self):
        lead = self._lead()
        self.assertEqual(lead.name, "Rahul Shah0")
        self.assertEqual(lead.title, "Plant Head")
        self.assertEqual(lead.company, "Acme Motors")
        self.assertEqual(lead.email, "rahul.shah0@acme.com")
        self.assertEqual(lead.industry, "automotive")
        self.assertEqual(lead.extra["location"], "Dubai, United Arab Emirates")
        self.assertEqual(lead.extra["apollo_id"], "apollo0")
        self.assertEqual(lead.extra["email_check"], "valid")
        self.assertEqual(lead.extra["company_domain"], "acme.com")
        self.assertEqual(lead.extra["headcount"], 2500)
        self.assertEqual(lead.extra["revenue"], 250_000_000)
        self.assertEqual(lead.extra["since"], "2021-04")
        self.assertIn("linkedin.com/in/rahul0", lead.extra["linkedin"])

    def test_a_city_state_and_country_all_show(self):
        self.assertEqual(self._lead(city="Pune", state="Maharashtra",
                                    country="India").extra["location"],
                         "Pune, Maharashtra, India")

    def test_only_apollos_verified_is_called_valid(self):
        self.assertEqual(self._lead(email_status="likely to engage")
                         .extra["email_check"], "unknown")

    def test_a_locked_address_is_no_address(self):
        # Apollo answers a locked record with a placeholder that would bounce.
        lead = self._lead(email="email_not_unlocked@domain.com")
        self.assertEqual(lead.email, "")
        self.assertNotIn("email_check", lead.extra)
        # And nothing to say it came from Apollo — the address the pipeline
        # ends up mailing will be enrich's guess, which a finder may improve.
        self.assertNotIn("email_source", lead.extra)

    def test_an_address_apollo_supplied_says_so(self):
        """Apollo stands behind only some of its addresses, so the rest reach
        the verify waterfall unconfirmed. The mark is what stops that waterfall
        buying this very address back from Apollo a second time."""
        self.assertEqual(self._lead().extra["email_source"], "apollo")
        self.assertEqual(self._lead(email_status="unverified")
                         .extra["email_source"], "apollo")

    def test_the_searched_industry_stands_in_when_apollo_names_none(self):
        person = _person(0)
        person["organization"].pop("industry")
        fake = _Apollo([_card(0)], [person])
        spec = _spec(industries={"include": ["Auto Components"]})
        leads, _ = _run(fake, spec, target=1)
        self.assertEqual(leads[0].industry, "Auto Components")


# ── every refusal Apollo can send ─────────────────────────────────────────────

class _Response:
    def __init__(self, status, payload=None, headers=None):
        self.status_code = status
        self._payload = {} if payload is None else payload
        self.headers = headers or {}

    def json(self):
        return self._payload


class _Net:
    """Stands in for the requests module. Serves scripted responses (the last
    one repeats); an Exception in the script is raised instead."""

    def __init__(self, *responses):
        self.script = list(responses)
        self.calls = []

    def post(self, url, json=None, headers=None, timeout=None):
        self.calls.append({"url": url, "json": json, "headers": headers})
        item = self.script[0] if len(self.script) == 1 else self.script.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


class ErrorTest(unittest.TestCase):

    def _post(self, *responses, waits=None):
        net = _Net(*responses)
        with mock.patch.object(apollo, "_requests", lambda: net), \
                mock.patch.object(apollo, "_pause", (waits if waits is not None
                                                     else []).append):
            return net, apollo._post(apollo.SEARCH, {"page": 1}, "key")

    def test_the_key_goes_in_the_header(self):
        net, data = self._post(_Response(200, {"people": []}))
        self.assertEqual(net.calls[0]["headers"]["x-api-key"], "key")
        self.assertEqual(net.calls[0]["url"], apollo.BASE + apollo.SEARCH)
        self.assertEqual(data, {"people": []})

    def test_401_names_the_key(self):
        with self.assertRaises(apollo.ApolloError) as caught:
            self._post(_Response(401))
        self.assertEqual(str(caught.exception), apollo.BAD_KEY)
        self.assertIn("Settings > Agents", str(caught.exception))

    def test_403_says_the_key_is_scoped_and_names_the_endpoint(self):
        with self.assertRaises(apollo.ApolloError) as caught:
            self._post(_Response(403))
        message = str(caught.exception)
        self.assertIn("master key", message)
        self.assertIn(apollo.SEARCH, message)

    def test_422_points_at_the_filters(self):
        with self.assertRaises(apollo.ApolloError) as caught:
            self._post(_Response(422))
        self.assertEqual(str(caught.exception), apollo.BAD_PARAMS)
        self.assertIn("200 characters", str(caught.exception))

    def test_429_is_retried_twice_honouring_retry_after_then_raised(self):
        waits: list = []
        with self.assertRaises(apollo.ApolloError) as caught:
            self._post(_Response(429, headers={"Retry-After": "3"}), waits=waits)
        self.assertEqual(str(caught.exception), apollo.RATE_LIMITED)
        self.assertEqual(waits, [3.0, 3.0])             # two retries, then it stops

    def test_429_that_clears_is_not_an_error(self):
        waits: list = []
        net, data = self._post(_Response(429), _Response(200, {"people": [1]}),
                               waits=waits)
        self.assertEqual(data, {"people": [1]})
        self.assertEqual(len(net.calls), 2)
        self.assertEqual(waits, [apollo._WAIT])         # no header: a plain wait

    def test_a_dead_network_is_an_unreachable(self):
        with self.assertRaises(apollo._Unreachable):
            self._post(OSError("no route to host"))

    def test_no_key_at_all(self):
        with self.assertRaises(apollo.ApolloError) as caught:
            apollo.search_people(_spec(), "  ")
        self.assertEqual(str(caught.exception), apollo.NO_KEY)

    def test_a_network_failure_on_a_later_page_keeps_the_list(self):
        fake = _Apollo([_card(i) for i in range(6)], [_person(i) for i in range(6)])
        fake.fail_search_on = 2
        leads, stats = _run(fake, target=6, per_page=2)
        self.assertEqual([l.extra["apollo_id"] for l in leads], ["apollo0", "apollo1"])
        self.assertEqual(stats["errors"], 1)
        self.assertEqual(stats["short_by"], 4)

    def test_a_network_failure_on_the_first_call_is_raised(self):
        fake = _Apollo([_card(0)], [_person(0)])
        fake.fail_search_on = 1
        with self.assertRaises(apollo.ApolloError) as caught:
            _run(fake, target=5)
        self.assertEqual(str(caught.exception), apollo.UNREACHABLE)


# ── the finder, the identity key and the waterfall ────────────────────────────

def _never(path, body, key, timeout=30):
    """A _post that fails the test if it is called — every Apollo call here is
    a credit, so "no call" is the assertion."""
    raise AssertionError(f"Apollo was asked for {path} — that is a credit spent")


class FinderTest(unittest.TestCase):

    def _lead(self, **extra) -> Lead:
        lead = Lead(name="Rahul Shah", company="Acme Motors")
        lead.extra.update(extra)
        return lead

    def test_it_asks_by_profile_link_and_maps_the_answer(self):
        calls = []

        def fake(path, body, key, timeout=30):
            calls.append((path, body))
            return {"person": {"email": "rahul.shah@acme.com", "email_status": "verified"}}

        lead = self._lead(linkedin="https://www.linkedin.com/in/rahul",
                          company_domain="acme.com")
        with mock.patch.object(apollo, "_post", fake):
            self.assertEqual(apollo.find_email(lead, "key"),
                             ("rahul.shah@acme.com", "valid"))
        path, body = calls[0]
        self.assertEqual(path, apollo.MATCH)
        self.assertEqual(body["linkedin_url"], "https://www.linkedin.com/in/rahul")
        self.assertEqual(body["domain"], "acme.com")

    def test_the_apollo_id_is_used_when_the_lead_carries_one(self):
        calls = []

        def fake(path, body, key, timeout=30):
            calls.append(body)
            return {"person": {"email": "a@b.com", "email_status": "unverified"}}

        with mock.patch.object(apollo, "_post", fake):
            self.assertEqual(apollo.find_email(self._lead(apollo_id="apollo7"), "key"),
                             ("a@b.com", "unknown"))
        self.assertEqual(calls[0]["id"], "apollo7")
        self.assertEqual(calls[0]["organization_name"], "Acme Motors")

    def test_nothing_found_nothing_claimed(self):
        for answer in ({}, {"person": None},
                       {"person": {"email": "email_not_unlocked@domain.com"}}):
            with mock.patch.object(apollo, "_post", lambda *a, **k: answer):
                self.assertEqual(apollo.find_email(self._lead(company_domain="acme.com"),
                                                   "key"), ("", ""))

    def test_an_address_apollo_already_sold_is_never_bought_twice(self):
        """A lead SOURCED from Apollo carries Apollo's address and Apollo's id.
        people/match, asked by that id, finds the same person and returns the
        same address — for a second credit. So the finder declines before it
        calls, and an address enrich merely GUESSED still gets asked about."""
        lead = self._lead(apollo_id="apollo7", company_domain="acme.com",
                          email_check="unknown", email_source="apollo")
        lead.email = "rahul.shah@acme.com"
        with mock.patch.object(apollo, "_post", _never):
            self.assertEqual(apollo.find_email(lead, "key"), ("", ""))
        lead.extra.pop("email_source")           # a pattern guess: no source
        with mock.patch.object(apollo, "_post",
                               lambda *a, **k: {"person": {"email": "r.s@acme.com",
                                                           "email_status": "verified"}}):
            self.assertEqual(apollo.find_email(lead, "key"), ("r.s@acme.com", "valid"))

    def test_the_waterfall_spends_no_credit_on_apollos_own_address(self):
        """The whole point of the mark: a seller whose ONLY key is Apollo's has
        no free verifier to promote an unconfirmed address, so every hot/warm
        lead would otherwise reach the Apollo finder and be re-bought."""
        lead = self._lead(apollo_id="apollo7", company_domain="acme.com",
                          email_check="unknown", email_source="apollo")
        lead.email = "rahul.shah@acme.com"
        keys = verify.collect_keys({"apollo_api_key": "ap-k"})
        self.assertEqual(list(keys), ["apollo_api_key"])
        with mock.patch.object(apollo, "_post", _never):
            verify.find_and_verify(lead, keys)
        self.assertEqual(lead.email, "rahul.shah@acme.com")

    def test_the_finder_that_replaced_the_address_is_the_one_recorded(self):
        """A guessed address Apollo DID improve is now Apollo's — so the next
        pass over this lead (a reopened session, a second verify) must not pay
        to be told the same thing again."""
        lead = self._lead(company_domain="acme.com", email_check="unknown")
        lead.email = "guess@acme.com"
        keys = {"apollo_api_key": "ap-k"}
        with mock.patch.object(apollo, "_post",
                               lambda *a, **k: {"person": {"email": "real@acme.com",
                                                           "email_status": "verified"}}):
            verify.find_and_verify(lead, keys)
        self.assertEqual(lead.email, "real@acme.com")
        self.assertEqual(lead.extra["email_source"], "apollo")
        with mock.patch.object(apollo, "_post", _never):
            verify.find_and_verify(lead, keys)

    def test_a_refusal_never_ends_a_run(self):
        def boom(*a, **k):
            raise apollo.ApolloError(apollo.BAD_KEY)

        with mock.patch.object(apollo, "_post", boom):
            self.assertEqual(apollo.find_email(self._lead(company_domain="acme.com"),
                                               "key"), ("", ""))
        self.assertEqual(apollo.find_email(self._lead(), ""), ("", ""))

    def test_apollo_is_the_only_finder(self):
        # Changed 25-Nov-2026, the owner: "no room for hunter now" (was 27-Sep-2026: "our main will always be
        # hunter"). Apollo's reveal sells the full name with the address for about Hunter's price.
        keys = [k for k, _, _ in verify._FINDERS]
        self.assertEqual(keys, ["apollo_api_key"])
        self.assertIn("apollo_api_key", verify.VERIFIER_KEYS)

    def test_collect_keys_picks_the_apollo_key_up(self):
        self.assertEqual(verify.collect_keys({"apollo_api_key": " k "})["apollo_api_key"],
                         "k")
        with mock.patch.dict(os.environ, {"APOLLO_API_KEY": "envkey"}):
            self.assertEqual(verify.collect_keys()["apollo_api_key"], "envkey")
            self.assertEqual(apollo.api_key(), "envkey")
        self.assertEqual(apollo.api_key({"apollo_api_key": " k "}), "k")

    def test_the_finder_is_wired_to_find_email(self):
        lead = self._lead(company_domain="acme.com")
        with mock.patch.object(apollo, "_post",
                               lambda *a, **k: {"person": {"email": "x@acme.com",
                                                           "email_status": "verified"}}):
            self.assertEqual(verify._apollo_find(lead, "key"), ("x@acme.com", "valid"))


class IdentityTest(unittest.TestCase):

    def test_the_apollo_id_is_an_identity_key(self):
        lead = Lead(name="Rahul Shah", company="Acme Motors")
        lead.extra["apollo_id"] = "apollo7"
        self.assertIn("a:apollo7", identity.keys_of(lead))
        # And it alone is enough to recognise him next time — which is the whole
        # point: the free search row has no e-mail and half a surname.
        self.assertIn(lead, SeenIndex(["a:apollo7"]))
        self.assertNotIn(Lead(name="Rahul Shah", company="Acme Motors"),
                         SeenIndex(["a:apollo7"]))

    def test_no_id_no_key(self):
        lead = Lead(name="Rahul Shah", company="Acme Motors")
        lead.extra["apollo_id"] = ""
        self.assertEqual([k for k in identity.keys_of(lead) if k.startswith("a:")], [])


if __name__ == "__main__":
    unittest.main()
