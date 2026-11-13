"""
Leads & Outreach — the Companies page's controller
──────────────────────────────────────────────────
The Companies page (companies_page.py) is a view, as Find People's cockpit is:
it shows one page of companies and says what the owner asked by a signal. This
is what answers — the counterpart of the workbench's People half:

  · it owns the POOL (companies.build over the saved accounts and everyone in
    the People pool), the company filters (a FilterPanel of kind "company"),
    the tab, sort, search box and page, and re-answers all of them from memory
    on every click — filters are instant and free, finding new people is the
    People page's own paid button;
  · it carries out every act on the stores (accounts.py) — Save, Add to list,
    Set stage, Edit, Delete, a note, a task, a logged activity — and then hands
    the page and the open profile the records as they now stand;
  · it takes the owner to the People page: "Find people" there, filtered to the
    people at these companies, and a colleague picked in a profile.

The workbench (workbench.py) is the host: it owns the people pool, the saved
accounts, the status line, the Exa key and the credit pool. This module reads
them through a handful of names and never builds its own copy. Acting on a
company that is not saved saves it first — Apollo's rule ("save a company to
turn it into an account. This unlocks key actions like enrichment, ownership,
and timeline tracking").

Test seams (no modal in a test): ask_list_name, ask_export_path, confirm_delete,
confirm_enrich.
"""
from __future__ import annotations

import csv
import datetime
import os
import re

from PySide6.QtCore import QObject
from PySide6.QtWidgets import QFileDialog, QInputDialog, QMessageBox

import i18n
from prospector import filters as F

from addons.leads import accounts as AC
from addons.leads import companies as CO
from addons.leads import imports as IM
from addons.leads.companies_page import CompaniesPage
from addons.leads.company_panel import CompanyView
from addons.leads.filter_panel import FilterPanel, static_suggest

_NAMES_MAX = 8                      # company names offered while typing


def _plural(n: int, one: str, many: str) -> str:
    return i18n.t(one) if n == 1 else i18n.t(many).format(n=f"{n:,}")


class CompaniesController(QObject):
    """See the module docstring. `host` is the LeadsWorkbench."""

    def __init__(self, host, page: CompaniesPage):
        super().__init__(page)
        self.host = host
        self.page = page
        self._pool: list = []               # companies.build(...)
        self._tab = "total"
        self._sort = "relevance"
        self._page_no = 0
        self._query = ""
        self._sig = None                    # what the result on screen IS
        self._dirty = True                  # the pool needs rebuilding when shown
        self._worker = None
        self.filters = FilterPanel(suggest=self._suggest, kind="company")
        page.set_filter_panel(self.filters)
        self.filters.changed.connect(self._on_filters_changed)
        page.tabChanged.connect(self._on_tab)
        page.pageRequested.connect(self._on_page)
        page.sortChanged.connect(self._on_sort)
        page.queryChanged.connect(self._on_query)
        page.importRequested.connect(lambda kind: self.host._import(kind))
        page.openRequested.connect(self._open)
        page.saveRequested.connect(self._save)
        page.findPeopleRequested.connect(self._find_people)
        page.listRequested.connect(self._add_to_list)
        page.exportRequested.connect(self._export)
        page.stageRequested.connect(self._set_stage)
        page.enrichRequested.connect(self._enrich)
        page.deleteRequested.connect(self._delete)
        p = page.panel
        p.saveRequested.connect(lambda c: self._save([c]))
        p.stageRequested.connect(lambda c, s: self._set_stage([c], s))
        p.listRequested.connect(lambda c: self._add_to_list([c]))
        p.findPeopleRequested.connect(lambda c: self._find_people([c]))
        p.noteRequested.connect(self._note)
        p.taskRequested.connect(self._task)
        p.taskDoneRequested.connect(self._task_done)
        p.logRequested.connect(self._log)
        p.editRequested.connect(self._edit)
        p.flagRequested.connect(self._flag)
        p.deleteRequested.connect(lambda c: self._delete([c], asked=True))
        p.enrichRequested.connect(lambda c: self._enrich([c]))
        p.personPicked.connect(self._person_picked)

    # ── the pool ──────────────────────────────────────────────────────────────
    def refresh(self, force: bool = False) -> None:
        """The people or the saved accounts changed under the page: rebuild the
        pool now when it is on screen, else when it next is."""
        self._dirty = True
        if force or self.page.isVisible():
            self._rebuild()

    def on_shown(self) -> None:
        """The Companies tab was opened."""
        if self._dirty:
            self._rebuild()

    def _rebuild(self) -> None:
        host = self.host
        self._dirty = False
        self._pool = CO.build(getattr(host, "_saved_accounts", ()) or (),
                              getattr(host, "_people", ()) or ())
        self._sync_imports()
        self.filters.set_record_options(CO.record_options(host._saved_accounts))
        self._refilter(keep_page=True)
        self._reshow()

    def _sync_imports(self) -> None:
        try:
            self.filters.set_imports((), IM.list_imports(self.host._imports_dir(), "accounts"))
        except Exception:                                   # noqa: BLE001
            pass                            # no imports folder yet: nothing to offer

    def _suggest(self, facet: str, text: str) -> list:
        """The typeahead of the open facets: the companies and industries Prism
        holds, then the starter lists."""
        fold = " ".join(str(text or "").split()).casefold()
        if facet == "companies" and fold:
            names = [c.name for c in self._pool if c.name and fold in c.name.casefold()]
            return sorted(set(names), key=str.casefold)[:_NAMES_MAX]
        if facet == "industries" and fold:
            seen = sorted({c.industry for c in self._pool
                           if c.industry and fold in c.industry.casefold()}, key=str.casefold)
            return seen[:_NAMES_MAX] + [s for s in static_suggest(facet, text)
                                        if s not in seen][:_NAMES_MAX]
        return static_suggest(facet, text)

    def _refilter(self, keep_page: bool = False) -> None:
        """The page: the pool filtered (the rail + Search companies), split into
        Total / Net New / Saved, sorted, and the chosen page of 25 shown."""
        if not keep_page:
            self._page_no = 0
        spec = self.filters.spec()
        matched = CO.filter_companies(self._pool, spec, query=self._query)
        tabs = CO.split(matched)
        counts = {k: len(v) for k, v in tabs.items()}
        rows = CO.sort_companies(tabs.get(self._tab, tabs["total"]), self._sort)
        info = CO.page(rows, self._page_no)
        import json
        signature = (json.dumps(spec.to_dict(), sort_keys=True), self._tab, self._query)
        if signature != self._sig:
            self._sig = signature
            self.page.clear_selection()
        self._page_no = info["page"]
        if self._pool and not rows:
            from addons.leads.companies_page import _NO_MATCH_BODY, _NO_MATCH_TITLE
            empty = (i18n.t(_NO_MATCH_TITLE), i18n.t(_NO_MATCH_BODY))
        else:
            empty = None
        self.page.set_companies(info["rows"], info, counts, rows, empty)
        self.page.set_filter_count(spec.active_count())

    def _on_filters_changed(self) -> None:
        self._refilter()

    def _on_tab(self, key: str) -> None:
        self._tab = key if key in ("total", "net_new", "saved") else "total"
        self._refilter()

    def _on_page(self, index: int) -> None:
        self._page_no = max(0, int(index))
        self._refilter(keep_page=True)

    def _on_sort(self, key: str) -> None:
        self._sort = key if key in CO.SORTS else "relevance"
        self._refilter()

    def _on_query(self, text: str) -> None:
        self._query = (text or "").strip()
        self._refilter()

    # ── opening a company ─────────────────────────────────────────────────────
    def _find(self, company):
        """The pool's row for this company as it now stands (a pool rebuilt under
        an open profile makes new objects; the keys stay)."""
        keys = getattr(company, "keys", None) or frozenset()
        for c in self._pool:
            if keys and not keys.isdisjoint(c.keys):
                return c
        return company

    def view_of(self, company) -> CompanyView:
        fresh = self._find(company)
        return CompanyView(company=fresh, account=fresh.account if fresh.saved else None,
                           people=list(fresh.people))

    def _open(self, company) -> None:
        self.page.show_profile(self.view_of(company))

    def _reshow(self) -> None:
        """The open profile again, from the records as they now stand."""
        company = self.page.open_company()
        if company is not None:
            self.page.show_profile(self.view_of(company))

    # ── helpers ───────────────────────────────────────────────────────────────
    def _say(self, text: str) -> None:
        self.host._status.setText(text)

    def _dir(self) -> str:
        return self.host._accounts_dir()

    def _changed(self) -> None:
        """Something wrote the accounts: re-read them and rebuild what shows
        them — the People page's account filters and this page."""
        self.host._reload_accounts()
        self.host._rebuild_pool_keep_page()         # its _pool_changed refreshes this page

    def _ensure_saved(self, companies) -> bool:
        """Save the ones that are not accounts yet. False (and said) when the
        file can't be written."""
        todo = [c for c in companies if not c.saved]
        if not todo:
            return True
        try:
            AC.save(self._dir(), CO.accounts_of(todo), via="save")
        except AC.StoreError as e:
            self._say(str(e))
            return False
        return True

    # ── the action bar ────────────────────────────────────────────────────────
    def _save(self, companies) -> None:
        todo = [c for c in companies if not c.saved]
        if not companies:
            return
        if not todo:
            self._say(i18n.t("Those companies are already saved."))
            return
        if not self._ensure_saved(todo):
            return
        self._say(_plural(len(todo), "Saved 1 company as an account — it's under Saved now.",
                          "Saved {n} companies as accounts — they're under Saved now."))
        self._changed()

    def _set_stage(self, companies, stage: str) -> None:
        stage = AC.stage_named(stage)
        if not (companies and stage) or not self._ensure_saved(companies):
            return
        try:
            moved = AC.set_stage_many(self._dir(), [c.view() for c in companies], stage)
        except AC.StoreError as e:
            self._say(str(e))
            return
        if moved:
            words = (i18n.t("Moved 1 company to {stage}.") if moved == 1
                     else i18n.t("Moved {n} companies to {stage}."))
            self._say(words.format(n=f"{moved:,}", stage=stage))
        else:
            self._say(i18n.t("They are all at {stage} already.").format(stage=stage))
        self._changed()

    def ask_list_name(self, default: str):
        """The list's name, or None on Cancel. A test seam."""
        name, ok = QInputDialog.getText(self.page, i18n.t("Add to list"),
                                        i18n.t("Name this list:"), text=default)
        return name if ok else None

    def _add_to_list(self, companies) -> None:
        if not companies:
            return
        name = self.ask_list_name(i18n.t("My companies"))
        if name is None or not name.strip():
            return
        try:
            AC.save(self._dir(), CO.accounts_of(companies), via="save",
                    list_name=name.strip())
        except AC.StoreError as e:
            self._say(str(e))
            return
        self._say(i18n.t("Added {n} to the company list “{name}”.").format(
            n=f"{len(companies):,}", name=name.strip()))
        self._changed()

    def ask_export_path(self, default: str) -> str:
        """Where to write the CSV, or "" on Cancel. A test seam."""
        path, _ = QFileDialog.getSaveFileName(self.page, i18n.t("Export companies"),
                                              default, "CSV (*.csv)")
        return path or ""

    def _export(self, companies) -> None:
        """Apollo's "Export accounts to a CSV" — what Prism holds on each."""
        if not companies:
            return
        stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
        default = os.path.join(self.host._autosave_dir(), f"Prism companies {stamp}.csv")
        path = self.ask_export_path(default)
        if not path:
            return
        header, rows = CO.export_table(companies)
        try:
            with open(path, "w", newline="", encoding="utf-8-sig") as f:
                w = csv.writer(f)
                w.writerow(header)
                w.writerows(rows)
        except OSError as e:
            self._say(i18n.t("Couldn't write {path}: {err}. If it is open in Excel, close "
                             "it and try again.").format(path=path, err=e))
            return
        self._say(i18n.t("Exported {n} companies to {path}").format(
            n=f"{len(companies):,}", path=path))

    def confirm_delete(self, n: int) -> bool:
        """Apollo's warning for deleting accounts. A test seam."""
        box = QMessageBox(
            QMessageBox.Icon.Question, i18n.t("Delete accounts"),
            (i18n.t("Delete 1 account? Its stage, lists, notes, tasks and activity go with "
                    "it. Its people stay in Prism, and the company stays on the page as "
                    "net new.") if n == 1 else
             i18n.t("Delete {n} accounts? Their stage, lists, notes, tasks and activity go "
                    "with them. Their people stay in Prism, and the companies stay on the "
                    "page as net new.").format(n=f"{n:,}")),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, self.page)
        box.setDefaultButton(QMessageBox.StandardButton.No)
        return box.exec() == QMessageBox.StandardButton.Yes

    def _delete(self, companies, asked: bool = False) -> None:
        """Delete accounts. `asked`: the profile already asked about this one."""
        saved = [c for c in companies if c.saved]
        if not saved:
            self._say(i18n.t("Only saved companies are accounts — nothing to delete."))
            return
        if not asked and not self.confirm_delete(len(saved)):
            return
        try:
            gone = AC.remove(self._dir(), [c.view() for c in saved])
        except AC.StoreError as e:
            self._say(str(e))
            return
        open_company = self.page.open_company()
        if open_company is not None and any(not self._find(c).keys.isdisjoint(
                open_company.keys) for c in saved):
            self.page.close_profile()
        self._say(_plural(gone, "Deleted 1 account.", "Deleted {n} accounts."))
        self._changed()

    # ── to the People page ────────────────────────────────────────────────────
    def _find_people(self, companies) -> None:
        """Apollo's "Find people": a people search scoped to these companies."""
        names = []
        for c in companies:
            if c.name and c.name not in names:
                names.append(c.name)
        if not names:
            return
        names = names[:F.MAX_FACET_VALUES]
        spec = self.host._filters.spec()
        spec.companies.include = names
        spec.companies.exclude = []
        self.host._filters.set_spec(spec)
        self.host._cockpit.show_people_tab()
        self._say(_plural(len(names),
                          "The people Prism holds at that company. Add a job title and press "
                          "Find new people to search for more.",
                          "The people Prism holds at those {n} companies. Add a job title "
                          "and press Find new people to search for more."))

    def _person_picked(self, person) -> None:
        self.host._cockpit.open_person(person)

    # ── the profile's own acts ────────────────────────────────────────────────
    def _act(self, company, doing) -> None:
        """Save the company first when it is not an account, run `doing(view)`
        on the stores, and redraw."""
        if not self._ensure_saved([company]):
            return
        try:
            doing(company.view())
        except AC.StoreError as e:
            self._say(str(e))
            return
        self._changed()

    def _note(self, company, text: str) -> None:
        self._act(company, lambda v: AC.add_note(self._dir(), v, text))

    def _task(self, company, text: str, due: str) -> None:
        self._act(company, lambda v: AC.add_task(self._dir(), v, text, due))

    def _task_done(self, company, task_id: str, done: bool) -> None:
        self._act(company, lambda v: AC.set_task_done(self._dir(), v, task_id, done))

    def _log(self, company, kind: str, text: str) -> None:
        self._act(company, lambda v: AC.log(self._dir(), v, kind, text))

    def _edit(self, company, changes: dict) -> None:
        self._act(company, lambda v: AC.edit(self._dir(), v, changes))

    def _flag(self, company) -> None:
        """"Flag as inaccurate": noted in Activities (the company stays)."""
        self._act(company, lambda v: AC.log(self._dir(), v, "flagged", ""))

    # ── the Exa lookup ────────────────────────────────────────────────────────
    def confirm_enrich(self, n: int) -> bool:
        """"Look up N companies?" — every search is a credit the owner approves.
        The host words it (it knows the pool). A test seam."""
        return self.host._confirm_enrich(n)

    def _enrich(self, companies) -> None:
        """Look the companies up on Exa for what they lack — a website, size,
        revenue, HQ — as an accounts import's enrichment does; what is found is
        saved to the accounts (a company not saved yet becomes one)."""
        from addons.leads.workers import LeadsAccountEnrichWorker
        host = self.host
        todo = [c for c in companies if CompaniesPage.needs_lookup(c)]
        if not todo:
            self._say(i18n.t("Nothing to look up — they already have a website, size, "
                             "revenue and HQ."))
            return
        if host._jobs:
            return
        if host._pooled():
            blocked = host._pool_blocker("company")
            if blocked:
                self._say(blocked)
                return
        elif not host._key("exa_api_key"):
            self._say(i18n.t("Looking the companies up needs an Exa API key — add it under "
                             "Search settings › Keys & claims."))
            return
        if not self.confirm_enrich(len(todo)):
            return
        host._set_running(True)
        self._say(_plural(len(todo), "Looking up 1 company…", "Looking up {n} companies…"))
        worker = LeadsAccountEnrichWorker([c.view() for c in todo], host.cfg, "all")
        self._worker = worker
        host._enrich_worker = worker            # the host keeps it alive, as for an import
        worker.progress.connect(lambda i, total, name: self._say(
            i18n.t("Looking up {i} of {n}: {name}").format(i=i, n=total, name=name)))
        worker.done.connect(self._on_enriched)
        worker.failed.connect(host._on_failed)
        host._job_started()
        worker.start()

    def _on_enriched(self, companies, filled: int) -> None:
        host = self.host
        idle = host._job_done()
        try:
            AC.save(self._dir(), companies, via="enrich", update=True)
            AC.note_enriched(self._dir(), companies,
                             i18n.t("website, size, revenue and HQ"))
        except AC.StoreError as e:
            self._say(str(e))
        else:
            self._say(i18n.t("Filled in {n} companies from Exa.").format(n=filled))
        if idle:
            host._set_running(False)
        self._changed()
