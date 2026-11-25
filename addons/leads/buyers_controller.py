"""
Find buyers — the page's controller
───────────────────────────────────
The page (buyers_page.py) is a view. This answers it, the way the Companies
page's controller does for Companies:

  · "Find my buyers"  → one model call reads the offer into buyer types;
  · "Quick preview" / "Run the full search" → the hunt, off the UI thread;
  · every finished hunt is kept (buyers_store.py) with what the owner decided
    about each card, so a card judged once is never judged twice;
  · Accept turns the card's organisation into a saved contact (via "buyers"),
    which puts it on the People page with the evidence in its record — finding
    the PEOPLE at it is that page's own, already-charged button.

The workbench (workbench.py) is the host: it owns the config, the credit pool,
the status line and the saved contacts. This module reads them through a handful
of names and never keeps its own copy.

Test seams, so no modal or browser opens in a test: `confirm`, `open_url`.
"""
from __future__ import annotations

import os
from dataclasses import replace
from datetime import datetime

from PySide6.QtCore import QObject, QUrl
from PySide6.QtGui import QDesktopServices

import i18n
from prospector import buyers as B
from prospector import gateway

from addons.leads import buyers_store as BS
from addons.leads.buyers_page import BuyersPage
from addons.leads.store import StoreError
from addons.leads.workers import BuyerHuntWorker, BuyerOfferWorker


class BuyersController(QObject):
    """See the module docstring. `host` is the LeadsWorkbench."""

    def __init__(self, host, page: BuyersPage):
        super().__init__(page)
        self.host, self.page = host, page
        self._read_worker = None
        self._hunt_worker = None
        self._current: dict | None = None       # the hunt on screen, cards as Hit objects
        self._loaded = False
        self._after_read = None                 # (channels, preview) of a hunt waiting for the offer to be read again
        page.readRequested.connect(self._read)
        page.huntRequested.connect(self._hunt)
        page.acceptRequested.connect(self._accept)
        page.decisionRequested.connect(self._decide)
        page.openRequested.connect(self.open_url)
        page.huntPicked.connect(self._pick_hunt)

    # ── where it is kept ──────────────────────────────────────────────────────
    def folder(self) -> str:
        """Beside the member's saved contacts. Tests patch this."""
        return os.path.join(os.path.dirname(self.host._contacts_dir()), "buyers")

    def on_shown(self) -> None:
        """The tab was opened: put back the offer the owner last described and
        the newest hunt, once."""
        self.page.set_monid(B.monid_ready(self.host.cfg))
        if self._loaded:
            return
        self._loaded = True
        try:
            offer, summary, types = BS.load_offer(self.folder())
            if offer.text:
                self.page.set_offer(offer)
            if types:
                self.page.set_types(summary, types, competitors=offer.competitors, channels=offer.channels,
                                    ideal=offer.ideal, company_kinds=offer.company_kinds,
                                    max_staff=offer.max_staff)
            self.refresh_learned()
            hunts = BS.list_hunts(self.folder())
            self.page.set_hunts(self._hunt_menu(hunts))
            if hunts:
                self._current = hunts[0]
                self.page.set_hunt(self._current)
        except Exception as e:                              # noqa: BLE001 — never block the tab
            self.page.set_status(str(e) or i18n.t("Couldn't read your earlier buyer searches."))

    @staticmethod
    def _hunt_menu(hunts: list) -> list:
        """[{"id", "label"}] for the Hunts menu: when it ran, whether it was a preview, how many buyers."""
        out = []
        for h in hunts:
            try:
                when = datetime.fromisoformat(h.get("created_at") or "").strftime("%d %b, %H:%M")
            except ValueError:
                when = i18n.t("Earlier")
            n = sum(1 for c in h["hits"] if c.status != B.CLOSED and not c.weak)
            label = i18n.t("{when} · {n} buyers").format(when=when, n=n)
            out.append({"id": h["id"], "label": (i18n.t("Preview, ") if h.get("preview") else "") + label})
        return out

    def _pick_hunt(self, hunt_id: str) -> None:
        """The Hunts menu: show an earlier search, with the decisions made on it."""
        hunt = BS.get_hunt(self.folder(), hunt_id)
        if hunt is None:
            self.page.set_status(i18n.t("That search is no longer kept."))
            return
        self._current = hunt
        self.page.close_panel()
        self.page.set_hunt(hunt)

    # ── what it has learnt ────────────────────────────────────────────────────
    def _memory(self) -> list:
        return BS.load_memory(self.folder())

    def _contact_rows(self) -> list:
        """[(source, stage)] for each accepted buyer now in People: how far the owner took it. Never raises."""
        try:
            from addons.leads import contacts as CT
            return [(c.lead.extra.get("buyer_channel"), c.stage)
                    for c in CT.list_contacts(self.host._contacts_dir())
                    if "buyers" in (c.via or []) and c.lead.extra.get("buyer_channel")]
        except Exception:                                   # noqa: BLE001
            return []

    def refresh_learned(self) -> None:
        """Tell the page how each source is doing, from the decisions and from People."""
        from prospector import buyers_learn as BL
        try:
            self.page.set_learned(BL.report(self._memory(), BL.outcomes(self._contact_rows())))
        except Exception:                                   # noqa: BLE001 — a report never blocks the page
            self.page.set_learned([])

    # ── seams ─────────────────────────────────────────────────────────────────
    def confirm(self, title: str, lines: list) -> bool:
        """Every credit is approved first (23-Sep-2026). On the developer's own
        keys nothing is charged, so nothing is asked. Tests patch this."""
        if not gateway.pooled():
            return True
        return self.host._confirm_pool(title, lines)

    def open_url(self, url: str) -> None:
        """Show a card's source page in the browser. Web addresses only.
        Tests patch this."""
        if str(url or "").lower().startswith(("http://", "https://")):
            QDesktopServices.openUrl(QUrl(url))

    @staticmethod
    def _cr(n: int) -> str:
        return i18n.t("1 credit") if int(n) == 1 else i18n.t("{n} credits").format(n=f"{int(n):,}")

    # ── step one: read the offer ──────────────────────────────────────────────
    def _read(self, offer) -> None:
        if self._read_worker is not None or self._hunt_worker is not None:
            return
        if gateway.pooled():
            price = gateway.rate("ai_qualify", 1)
            if not self.confirm(i18n.t("Find my buyers"), [
                    i18n.t("Prism will read what you sell and name the kinds of buyer — about {c}.")
                    .format(c=self._cr(price))]):
                return
        try:
            BS.save_offer(self.folder(), offer)
        except StoreError as e:
            self.page.set_status(str(e))
        self.page.set_busy(True, i18n.t("Reading what you sell…"))
        self._read_worker = BuyerOfferWorker(offer, self.host.cfg)
        self._read_worker.done.connect(lambda reading, o=offer: self._on_read(o, reading))
        self._read_worker.failed.connect(self._on_read_failed)
        self._read_worker.start()

    def _on_read(self, offer, reading) -> None:
        self._read_worker = None
        offer = replace(offer, competitors=" \u00b7 ".join(reading.competitors), channels=tuple(reading.channels),
                        ideal=reading.ideal, company_kinds=tuple(reading.company_kinds), max_staff=reading.max_staff)
        try:
            BS.save_offer(self.folder(), offer, reading.summary, reading.types)
        except StoreError as e:
            self.page.set_status(str(e))
        self.page.set_types(reading.summary, reading.types, competitors=offer.competitors, channels=offer.channels,
                            ideal=offer.ideal, company_kinds=offer.company_kinds, max_staff=offer.max_staff)
        self.page.set_busy(False, "")
        self._after_spend()
        pending, self._after_read = self._after_read, None
        if pending:                                             # the hunt that asked for this reading
            self._hunt(self.page.offer(), reading.summary, self.page.types(), pending[0], pending[1], _chained=True)

    def _on_read_failed(self, why: str) -> None:
        self._after_read = None
        self._read_worker = None
        self.page.set_busy(False, why or i18n.t("Couldn't read what you sell."))

    # ── step two: the hunt ────────────────────────────────────────────────────
    def _hunt(self, offer, summary: str, types: list, channels, preview: bool, _chained: bool = False) -> None:
        if self._hunt_worker is not None or self._read_worker is not None:
            return
        if not _chained and B.LIST in set(channels or ()) and not offer.company_kinds:
            # An offer read before the company list existed cannot be searched for companies: read it again first,
            # then run this hunt, instead of running and saying so afterwards (22-Nov-2026).
            self._after_read = (tuple(channels), bool(preview))
            self._read(offer)
            if self._read_worker is None:                       # declined, or could not start
                self._after_read = None
            return
        monid = B.monid_ready(self.host.cfg)
        self.page.set_monid(monid)
        est = B.estimate(offer, types, channels, preview=preview, monid=monid)
        if not est["searches"]:
            if B.LIST in set(channels or ()) and not offer.company_kinds:
                self.page.set_status(i18n.t("Prism couldn't tell what kind of companies your customers are. "
                                            "Say more about who buys it in your description and try again."))
            else:
                self.page.set_status(i18n.t("Pick at least one kind of buyer and one place to look."))
            return
        if gateway.pooled():
            search = gateway.rate("hunt", 1)
            read = gateway.rate("ai_qualify", 1)
            top = est["searches"] * search + est["model_calls"] * read
            if not self.confirm(i18n.t("Quick preview") if preview else i18n.t("Find my buyers"), [
                    i18n.t("It will run {n} web searches and {m} AI reads — up to {c}.").format(
                        n=est["searches"], m=est["model_calls"], c=self._cr(top)),
                    i18n.t("A search that finds nothing is not charged.")]):
                return
        self.page.set_busy(True, i18n.t("Searching…"))
        self._hunt_worker = BuyerHuntWorker(offer, summary, types, channels, self.host.cfg, preview,
                                            memory=self._memory())
        self._hunt_worker.progress.connect(lambda i, n, ch: self.page.set_busy(
            True, i18n.t("Searching {i} of {n}…").format(i=i, n=n)))
        self._hunt_worker.waiting.connect(lambda why: self.page.set_busy(True, i18n.t(why)))
        self._hunt_worker.done.connect(
            lambda res, o=offer, s=summary, t=list(types), c=tuple(channels), p=preview:
            self._on_hunted(o, s, t, c, p, res))
        self._hunt_worker.failed.connect(self._on_hunt_failed)
        self._hunt_worker.start()

    def _on_hunted(self, offer, summary, types, channels, preview, res) -> None:
        self._hunt_worker = None
        try:
            self._current = BS.save_hunt(self.folder(), offer=offer, summary=summary, types=types,
                                         channels=channels, preview=preview, result=res)
        except StoreError as e:
            # Kept in memory so the owner still sees what they paid for; said plainly.
            self._current = {"id": "", "preview": preview, "hits": list(res.hits), "stats": dict(res.stats),
                             "notes": list(res.notes) + [str(e)]}
        self.page.set_busy(False, "")
        self.page.set_hunt(self._current)
        try:
            self.page.set_hunts(self._hunt_menu(BS.list_hunts(self.folder())))
        except Exception:                                   # noqa: BLE001 - a menu never blocks a result
            pass
        self._after_spend()

    def _on_hunt_failed(self, why: str) -> None:
        self._hunt_worker = None
        self.page.set_busy(False, why or i18n.t("The search stopped. Nothing was charged for what did not run."))
        self._after_spend()

    def _after_spend(self) -> None:
        try:
            self.host._refresh_credits()
        except Exception:                                   # noqa: BLE001 — a balance read never blocks a result
            pass

    # ── step three: the owner decides ─────────────────────────────────────────
    def _apply(self, ids: list, decision: str, reason: str = "") -> int:
        """Set a decision on the cards on screen and keep it. Returns how many
        changed; says why when it could not be kept."""
        cur = self._current
        if cur is None:
            return 0
        n = B.decide(cur["hits"], ids, decision, reason)
        if n:
            judged = [h for h in cur["hits"] if h.id in set(ids)]
            try:
                if cur.get("id"):
                    BS.set_decisions(self.folder(), cur["id"], ids, decision, reason)
                BS.remember(self.folder(), judged, decision, reason)
            except StoreError as e:
                self.page.set_status(str(e))
            self.refresh_learned()
        self.page.set_hunt(cur)
        return n

    def _decide(self, ids: list, decision: str, reason: str) -> None:
        self._apply(list(ids), decision, reason)

    def _accept(self, hits: list) -> None:
        leads = [B.to_lead(h) for h in hits or ()]
        if not leads:
            return
        if not self.host._keep_as_contacts(leads, "buyers"):
            return                                          # the host said why on its own status line
        self._apply([h.id for h in hits], B.ACCEPTED)
        self.host._status.setText(
            i18n.t("Added 1 to People. Open it there and press Find people to reach someone who decides.")
            if len(leads) == 1 else
            i18n.t("Added {n} to People. Open them there and press Find people to reach someone "
                   "who decides.").format(n=len(leads)))
