"""
Find my buyers — the sources that come through Monid
────────────────────────────────────────────────────
Exa finds pages. Four of Monid's endpoints find what Exa cannot, each with the
dates and the organisation already in the answer, for a fraction of a cent a call:

  indeed   litescrape /indeed/search   jobs by title and city: the company hiring, the pay, the day posted.
  gnews    litescrape /google/news     news by topic and country: a funding round, a new plant.
  reddit   anyapi /reddit.search       posts that ask for a tool or a vendor.
  hn       anyapi /hackernews.search   the same, on Hacker News.

What was read from the real answers (22-Nov-2026) and is pinned by tests/fixtures/monid:

  · every answer's useful part is the run's `output`;
  · Indeed:  output.jobs_results[]  title, link, company_name, location, description, salary, posted_at
  · News:    output.articles[]      title, link, published_at, source
  · Reddit:  output.data.posts[]    title, selftext, url, createdUtc, author, subreddit
  · HN:      output.data.results[]  title, permalink, createdUtc, author, points

Each is turned into the SAME row the Exa search gives (url, title, text, publishedDate) plus `who` and
`source_name` where the answer names them, so the rest of the hunt does not know where a row came from.

Qt-free. Runs the Monid REST API with the owner's own key (`monid_api_key` in the config or the MONID_API_KEY
environment variable): this is the developer's direct mode, like PRISM_LEADS_DIRECT. On the credit pool the
licence server will make these calls with ITS key and this module is not used (see buyers.make_search). Every run
carries `maxCost`, Monid's own ceiling, so a surprise price is refused before anything is charged.

Monid's guide for this ("When to use Monid directly") describes a product that holds one Monid account, calls it
server to server and bills its users itself, as Prism does with credits.
"""
from __future__ import annotations

import os
import re
import time
import uuid
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

MONID_URL = "https://api.monid.ai"
SOURCES = ("indeed", "gnews", "reddit", "hn")
LABEL = {"indeed": "Indeed", "gnews": "Google News", "reddit": "Reddit", "hn": "Hacker News"}
MAX_COST = 0.02                 # dollars per run: the most any of these endpoints should ever cost
ROWS_MAX = 25


class MonidError(Exception):
    """A sentence for the owner: the wallet is empty, the key is wrong. Never a stack trace."""


def api_key(cfg: dict | None = None) -> str:
    return ((cfg or {}).get("monid_api_key") or os.environ.get("MONID_API_KEY") or "").strip()


def available(cfg: dict | None = None) -> bool:
    return bool(api_key(cfg))


# ── what to ask ───────────────────────────────────────────────────────────────

def request(source: str, text: str, *, location: str = "", country: str = "IN", days: int = 0, num: int = 10) -> dict:
    """The POST /v1/run body for one search. ValueError for a source this module does not have."""
    text = " ".join((text or "").split())[:300]
    country = (country or "IN").upper()[:2]
    if source == "indeed":
        q = {"q": text, "country": country, "limit": max(1, min(int(num), 50)), "sort": "date"}
        if location:
            q["location"] = location[:80]
        if days:
            q["fromage"] = max(1, min(int(days), 60))
        return {"provider": "litescrape", "endpoint": "/indeed/search", "maxCost": MAX_COST,
                "input": {"queryParams": q}}
    if source == "gnews":
        return {"provider": "litescrape", "endpoint": "/google/news", "maxCost": MAX_COST,
                "input": {"queryParams": {"q": text, "hl": "en-" + country, "gl": country,
                                          "limit": max(1, min(int(num), 100))}}}
    if source == "reddit":
        return {"provider": "anyapi", "endpoint": "/reddit.search", "maxCost": MAX_COST,
                "input": {"body": {"query": text, "sort": "new"}}}
    if source == "hn":
        return {"provider": "anyapi", "endpoint": "/hackernews.search", "maxCost": MAX_COST,
                "input": {"body": {"query": text, "tags": "story"}}}
    raise ValueError(f"unknown source {source!r}")


# ── what came back ────────────────────────────────────────────────────────────

def _s(v, n: int = 0) -> str:
    out = " ".join(v.split()) if isinstance(v, str) else ""
    return out[:n] if n else out


def _day(v) -> str:
    """An ISO day from an epoch, an RFC 822 date (Google News) or an ISO stamp; "" when it is none of them."""
    try:
        if isinstance(v, (int, float)) and v > 0:
            return datetime.fromtimestamp(int(v), tz=timezone.utc).date().isoformat()
        if isinstance(v, str) and v:
            if re.match(r"\d{4}-\d{2}-\d{2}", v):
                return v[:10]
            return parsedate_to_datetime(v).date().isoformat()
    except (TypeError, ValueError, OverflowError, OSError):
        pass
    return ""


def _salary(sal) -> str:
    if not isinstance(sal, dict) or not sal.get("minimum"):
        return ""
    cur = {"INR": "₹", "USD": "$", "GBP": "£", "EUR": "€"}.get(str(sal.get("currency")), str(sal.get("currency") or ""))
    lo, hi = sal.get("minimum"), sal.get("maximum")
    span = f"{cur}{lo:,}" + (f"–{hi:,}" if isinstance(hi, (int, float)) and hi != lo else "")
    return f"Pay: {span} per {str(sal.get('interval') or 'year').lower()}."


def _items(output, *path) -> list:
    node = output
    for key in path:
        node = node.get(key) if isinstance(node, dict) else None
    return [x for x in node if isinstance(x, dict)] if isinstance(node, list) else []


def rows(source: str, output) -> list:
    """The search answer as rows the hunt reads. Nothing here raises: a row that is not one is left out."""
    out = []
    if source == "indeed":
        for j in _items(output, "jobs_results"):
            url, title, company = _s(j.get("link") or j.get("apply_link")), _s(j.get("title")), _s(j.get("company_name"))
            if not (url and title):
                continue
            where = _s(j.get("location"))
            text = " ".join(x for x in (f"{title} at {company}" + (f", {where}." if where else "."), _salary(j.get("salary")),
                                         _s(j.get("description"), 1200)) if x)
            out.append({"url": url, "title": title, "who": company, "text": text, "publishedDate": _day(j.get("posted_at")),
                        "source_name": LABEL["indeed"]})
    elif source == "gnews":
        for a in _items(output, "articles"):
            url, title = _s(a.get("link")), _s(a.get("title"))
            if not (url and title):
                continue
            by = _s(a.get("source"))
            out.append({"url": url, "title": title, "text": title + (f" ({by})" if by else ""),
                        "publishedDate": _day(a.get("published_at")), "source_name": by or LABEL["gnews"]})
    elif source == "reddit":
        for p in _items(output, "data", "posts"):
            title, body = _s(p.get("title")), _s(p.get("selftext"), 1500)
            link = _s(p.get("url")) or (("https://www.reddit.com" + _s(p.get("permalink"))) if p.get("permalink") else "")
            if not (link and title):
                continue
            sub, author = _s(p.get("subreddit")), _s(p.get("author"))
            out.append({"url": link, "title": title, "text": (title + ". " + body) if body else title,
                        "publishedDate": _day(p.get("createdUtc")), "who": f"u/{author} in r/{sub}" if author and sub else "",
                        "source_name": f"r/{sub}" if sub else LABEL["reddit"]})
    elif source == "hn":
        for p in _items(output, "data", "results"):
            link, title = _s(p.get("permalink")) or _s(p.get("url")), _s(p.get("title"))
            if not (link and title):
                continue
            ext = _s(p.get("url"))
            out.append({"url": link, "title": title, "text": title + (f" ({ext})" if ext else ""),
                        "publishedDate": _day(p.get("createdUtc")), "who": f"{_s(p.get('author'))} on Hacker News" if p.get("author") else "",
                        "source_name": LABEL["hn"]})
    return out[:ROWS_MAX]


# ── running one ───────────────────────────────────────────────────────────────

def _post(url: str, headers: dict, body: dict, timeout: int):
    import requests                                      # lazy, like the rest of the engine
    r = requests.post(url, headers=headers, json=body, timeout=timeout)
    try:
        return r.status_code, r.json()
    except ValueError:
        return r.status_code, {}


def _get(url: str, headers: dict, timeout: int):
    import requests
    r = requests.get(url, headers=headers, timeout=timeout)
    try:
        return r.status_code, r.json()
    except ValueError:
        return r.status_code, {}


def run(source: str, text: str, *, key: str, location: str = "", country: str = "IN", days: int = 0, num: int = 10,
        post=None, get=None, max_wait: float = 45.0, sleep=time.sleep):
    """One search. A list of rows (maybe empty) when Monid answered, None when it could not (the provider was
    down, nothing was charged). MonidError, in words for the owner, when the key or the wallet is the problem.
    `post(url, headers, body, timeout)` and `get(url, headers, timeout)` -> (status, json) are test seams."""
    post, get = post or _post, get or _get
    headers = {"Authorization": "Bearer " + key, "X-Monid-Client": "prism-desktop", "Idempotency-Key": uuid.uuid4().hex}
    status, data = post(MONID_URL + "/v1/run", headers, request(source, text, location=location, country=country,
                                                                  days=days, num=num), 60)
    if status in (401, 403):
        raise MonidError("Monid refused the API key. Check MONID_API_KEY.")
    if status == 402 or (isinstance(data, dict) and data.get("errorCode") == "WALLET_INSUFFICIENT_FUNDS"):
        raise MonidError("Your Monid wallet is empty. Top it up at monid.ai, then search again.")
    if not isinstance(data, dict):
        return None
    waited = 0.0
    while status == 202 or str(data.get("status") or "").upper() in ("READY", "RUNNING"):
        if waited >= max_wait or not data.get("runId"):
            return None
        sleep(1.5)
        waited += 1.5
        status, data = get(MONID_URL + "/v1/runs/" + str(data["runId"]), headers, 40)
        if not isinstance(data, dict):
            return None
    if str(data.get("status") or "").upper() != "COMPLETED" or data.get("output") is None:
        return None                                      # failed, blocked or the provider said no: not "no buyers"
    return rows(source, data["output"])
