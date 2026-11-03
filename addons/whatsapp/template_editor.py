"""The template window: write it, see it as the customer will, see Meta's rules checked as you type.

A template is the only thing WhatsApp lets a business use to START a conversation, and Meta
reviews each one. Rejections are slow (a day) and say little, so this window runs the same rules
Meta applies — name pattern, variables in order and with samples, none at the very start or end of
the text, length limits — against the server while you type, shows the message on a phone the way
it will arrive, and only enables Submit when nothing Meta is known to refuse is left.

Three ways in: a blank form (or one of the ready-made templates), "edit and resubmit" for a
rejected one (the name stays — Meta replaces the rejected version), and "duplicate" for a copy under
a new name.
"""
from __future__ import annotations

import re

from PySide6.QtCore import QEvent, QTime, QTimer, Qt
from PySide6.QtWidgets import (QComboBox, QFrame, QHBoxLayout, QLineEdit, QPlainTextEdit,
                               QScrollArea, QVBoxLayout, QWidget)

import i18n
import theme
from addons.whatsapp import template_kinds as TK
from addons.whatsapp import ui
from addons.whatsapp.workers import PlatformWorker
from dialogs.base import PrismDialog
from widgets import controls as C

_VARIABLE = re.compile(r"\{\{\s*(\d+)\s*\}\}")

LANGUAGES = (("en_US", "English (US)"), ("en_GB", "English (UK)"), ("en", "English"), ("hi", "Hindi"),
             ("gu", "Gujarati"), ("mr", "Marathi"), ("ta", "Tamil"), ("te", "Telugu"), ("kn", "Kannada"),
             ("ml", "Malayalam"), ("bn", "Bengali"), ("pa", "Punjabi"), ("ur", "Urdu"))

QUICK, URL, PHONE, COPY = "QUICK_REPLY", "URL", "PHONE_NUMBER", "COPY_CODE"
NEW, RESUBMIT, DUPLICATE = "new", "resubmit", "duplicate"


NAME_MAX = 512
_NAME_BAD = re.compile(r"[^a-z0-9_]")


def clean_name(text: str) -> tuple:
    """A template name the way Meta takes it: lowercase letters, numbers and underscores, at most 512.

    Capitals become lowercase and spaces or hyphens become underscores, since that is what the person meant.
    Anything else is dropped, and the second value says what was, so the form can tell them instead of
    letting a letter vanish without a word."""
    lowered = text.lower().replace(" ", "_").replace("-", "_")
    dropped = "".join(dict.fromkeys(_NAME_BAD.findall(lowered)))
    return _NAME_BAD.sub("", lowered)[:NAME_MAX], dropped


def variables_of(text: str) -> list:
    """The variable numbers in a text, in order of appearance, each once."""
    seen: list = []
    for m in _VARIABLE.finditer(text or ""):
        n = int(m.group(1))
        if n not in seen:
            seen.append(n)
    return seen


def _button_part(kind: str, text: str, value: str) -> dict:
    if kind == URL:
        part = {"type": URL, "text": text, "url": value}
        if _VARIABLE.search(value):                          # Meta wants a full example address for a dynamic one
            part["example"] = [_VARIABLE.sub("sample", value)]
        return part
    if kind == PHONE:
        return {"type": PHONE, "text": text, "phone_number": value}
    if kind == COPY:
        return {"type": COPY, "text": text or "Copy code", "example": value}
    return {"type": QUICK, "text": text}


def _button_parts(buttons: list) -> list:
    parts = []
    for b in buttons:
        kind, text, value = (QUICK, b, "") if isinstance(b, str) else b
        if (text or "").strip() or (value or "").strip():
            parts.append(_button_part(kind, (text or "").strip(), (value or "").strip()))
    return parts


def components_from(header: str, body: str, footer: str, buttons: list, samples: dict, header_sample: str = "", *,
                    kind: str = "text", handle: str = "", offer: dict = None, cards=None) -> list:
    """The `components` Meta wants, from what the form holds. `buttons` are (kind, text, value);
    a bare string is a quick reply. `kind` is what the template is: text, image, video, document, location, carousel or offer.
    `handle` is Meta's handle for the sample file of a media header; `offer` the limited-time-offer component; `cards` a CarouselEditor
    (given the shared button parts, it makes the carousel)."""
    comps = []
    if kind == "carousel":
        head = None
    elif kind == "offer":
        head = TK.header_component((offer or {}).get("media") or "image", handle)
    else:
        head = TK.header_component(kind, handle, header, header_sample)
    if head is not None:
        comps.append(head)
    body_part = {"type": "BODY", "text": body.strip()}
    found = variables_of(body)
    if found:
        # A blank sample is left out, so the count is short and the server says which are missing
        # (Meta rejects an empty example, and a "" that passed a length check would reach it).
        body_part["example"] = {"body_text": [[v for v in ((samples.get(n) or "").strip() for n in found) if v]]}
    comps.append(body_part)
    if kind == "offer" and offer:
        comps.append({"type": "LIMITED_TIME_OFFER", "limited_time_offer": offer["offer"]})
    if kind != "carousel" and footer.strip():
        comps.append({"type": "FOOTER", "text": footer.strip()})
    parts = _button_parts(buttons)
    if kind == "carousel" and cards is not None:
        comps.append(cards.component(parts))
    elif parts:
        comps.append({"type": "BUTTONS", "buttons": parts})
    return comps


def fields_from(components: list) -> dict:
    """The form's fields, from a template's components (a library entry, or one Meta has on file)."""
    out = {"header": "", "header_sample": "", "body": "", "footer": "", "buttons": [], "samples": {},
           "kind": "text", "handle": "", "offer": None, "cards": None}
    for comp in components or []:
        kind = comp.get("type")
        if kind == "HEADER":
            fmt = comp.get("format", "TEXT")
            if fmt == "TEXT":
                out["header"] = comp.get("text", "")
                out["header_sample"] = ((comp.get("example") or {}).get("header_text") or [""])[0]
            elif fmt in ("IMAGE", "VIDEO", "DOCUMENT"):
                out["kind"] = fmt.lower()
                out["handle"] = ((comp.get("example") or {}).get("header_handle") or [""])[0]
            elif fmt == "LOCATION":
                out["kind"] = "location"
        elif kind == "BODY":
            out["body"] = comp.get("text", "")
            given = ((comp.get("example") or {}).get("body_text") or [[]])[0]
            out["samples"] = dict(zip(variables_of(out["body"]), given))
        elif kind == "FOOTER":
            out["footer"] = comp.get("text", "")
        elif kind == "LIMITED_TIME_OFFER":
            out["offer"] = comp
        elif kind == "CAROUSEL":
            out["cards"] = comp
            out["kind"] = "carousel"
        elif kind == "BUTTONS":
            for b in comp.get("buttons") or []:
                if b.get("type") == URL:
                    out["buttons"].append((URL, b.get("text", ""), b.get("url", "")))
                elif b.get("type") == PHONE:
                    out["buttons"].append((PHONE, b.get("text", ""), b.get("phone_number", "")))
                elif b.get("type") == QUICK:
                    out["buttons"].append((QUICK, b.get("text", ""), ""))
                elif b.get("type") == COPY:
                    out["buttons"].append((COPY, b.get("text", ""), b.get("example", "") if isinstance(b.get("example"), str) else ""))
    if out["offer"] is not None:
        out["kind"] = "offer"
    if out["cards"] is not None:                     # a carousel's buttons live on its cards
        first = ((out["cards"].get("cards") or [{}])[0]).get("components", [])
        for comp in first:
            if comp.get("type") == "BUTTONS":
                for b in comp.get("buttons") or []:
                    kind = b.get("type")
                    out["buttons"].append((kind, b.get("text", ""), b.get("url", "") if kind == URL else b.get("phone_number", "") if kind == PHONE else ""))
    return out


def filled(text: str, samples: dict) -> str:
    """The body as the customer will read it: each {{n}} replaced by its sample, or left visible when it has none."""
    return _VARIABLE.sub(lambda m: (samples.get(int(m.group(1))) or "").strip() or m.group(0), text or "")


def discard(widget):
    if widget is not None:
        widget.setParent(None)
        widget.deleteLater()


class TemplatePreview(QFrame):
    """The message on a phone. Plain text only: what Meta delivers is plain text, so what shows here is what arrives."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("waPhone")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setStyleSheet(f"#waPhone {{ background: {theme.NEUTRAL[200]}; border-radius: {theme.R_CARD}px; }}")
        col = QVBoxLayout(self)
        col.setContentsMargins(theme.SPACE_4, theme.SPACE_4, theme.SPACE_4, theme.SPACE_4)
        col.setSpacing(theme.SPACE_1)
        self.bubble = QFrame()
        self.bubble.setObjectName("waBubble")
        self.bubble.setAttribute(Qt.WA_StyledBackground, True)
        self.bubble.setStyleSheet(
            f"#waBubble {{ background: {theme.CARD}; border-radius: {theme.R_CONTROL + 2}px;"
            f" border: 1px solid {theme.HAIRLINE}; }}")
        self.inner = QVBoxLayout(self.bubble)
        self.inner.setContentsMargins(12, 10, 12, 8)
        self.inner.setSpacing(6)
        self.head = C.label("", level="BODY", weight=700, wrap=True)
        self.text = C.label("", level="BODY", wrap=True)
        self.foot = C.label("", level="META", colour=theme.NEUTRAL[500], wrap=True)
        self.clock = C.label(QTime.currentTime().toString("hh:mm"), level="META", colour=theme.NEUTRAL[400])
        self.clock.setAlignment(Qt.AlignRight)
        for w in (self.head, self.text, self.foot, self.clock):
            self.inner.addWidget(w)
        for w in (self.head, self.text, self.foot):
            w.installEventFilter(self)
        col.addWidget(self.bubble)
        self.buttons = QVBoxLayout()
        self.buttons.setSpacing(theme.SPACE_1)
        col.addLayout(self.buttons)
        self.extra = C.label("", level="SUPPORT", weight=600, colour=theme.NEUTRAL[600], wrap=True)
        self.extra.setAlignment(Qt.AlignCenter)
        self.extra.setMinimumHeight(54)
        self.extra.setStyleSheet(f"color: {theme.NEUTRAL[600]}; background: {theme.NEUTRAL[100]}; border-radius: {theme.R_CONTROL}px; font-weight: 600;")
        self.inner.insertWidget(0, self.extra)
        self.extra.hide()
        self.empty = C.label(i18n.t("Your message appears here as you type."), level="SUPPORT",
                             colour=theme.NEUTRAL[500], wrap=True)
        col.addWidget(self.empty)
        col.addStretch(1)
        self.set_content("", "", "", [], {}, "")

    def eventFilter(self, obj, event):
        if event.type() == QEvent.Resize and obj in (self.head, self.text, self.foot):
            self._fit_text()                                    # the label has just been given its real width
        return super().eventFilter(obj, event)

    def _fit_text(self):
        """Give each wrapped line of text the height its width needs. A page that caps this widget's width still offers it the whole
        column, so the layout measures the message at the wider width, finds one line, and cuts the last words off the real, narrower one."""
        for lab in (self.head, self.text, self.foot):
            if lab.isVisibleTo(self) and lab.width() > 0:
                need = lab.heightForWidth(lab.width())
                if need > 0 and lab.minimumHeight() != need:
                    lab.setMinimumHeight(need)

    def set_extra(self, text: str):
        """What stands in for a picture, a video, a document, a location, an offer or cards, so the preview says what will be there."""
        self.extra.setText(text)
        self.extra.setVisible(bool(text))

    def set_content(self, header: str, body: str, footer: str, buttons: list, samples: dict, header_sample: str):
        has_body = bool(body.strip()) or self.extra.isVisible()
        self.bubble.setVisible(has_body)
        self.empty.setVisible(not has_body)
        self.head.setText(_VARIABLE.sub(header_sample.strip() or "{{1}}", header) if variables_of(header) else header)
        self.head.setVisible(bool(header.strip()))
        self.text.setText(filled(body, samples))
        self.foot.setText(footer)
        self.foot.setVisible(bool(footer.strip()))
        while self.buttons.count():
            discard(self.buttons.takeAt(0).widget())
        for kind, text, _value in buttons:
            if not (text or "").strip():
                continue
            b = C.label(text.strip(), level="SUPPORT", weight=600, colour=theme.INFO_INK)
            b.setAlignment(Qt.AlignCenter)
            b.setMinimumHeight(34)
            b.setStyleSheet(b.styleSheet() + f" background: {theme.CARD}; border-radius: {theme.R_CONTROL}px;")
            self.buttons.addWidget(b)
        self._fit_text()


class TemplateEditor(PrismDialog):
    def __init__(self, parent=None, prefill: dict = None, mode: str = NEW):
        titles = {NEW: i18n.t("New message template"), RESUBMIT: i18n.t("Edit and resubmit"),
                  DUPLICATE: i18n.t("Duplicate template")}
        subtitles = {NEW: i18n.t("Meta reviews every template before you can send it. Fix what is marked here first "
                                 "and it is far more likely to be approved."),
                     RESUBMIT: i18n.t("Change what Meta objected to and send it again under the same name."),
                     DUPLICATE: i18n.t("A copy to change. Give it a new name — the original stays as it is.")}
        super().__init__(titles.get(mode, titles[NEW]), subtitles.get(mode, subtitles[NEW]), icon="message", parent=parent)
        self.mode = mode if mode in titles else NEW
        self._issues: list = []
        self._sample_edits: dict = {}
        self._busy = False
        self._lint_token = 0
        self._rejected_as = ""

        cols = QHBoxLayout()
        cols.setSpacing(theme.SPACE_5)
        self.body.addLayout(cols, stretch=1)

        # ── the form ─────────────────────────────────────────────────────────
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.viewport().setAutoFillBackground(False)
        host = QWidget()
        ui.see_through(host)
        form = QVBoxLayout(host)
        form.setContentsMargins(0, 0, theme.SPACE_3, 0)
        form.setSpacing(theme.SPACE_3)
        scroll.setWidget(host)
        cols.addWidget(scroll, stretch=5)
        self._scroll = scroll

        self.start_from = QComboBox()
        self.start_from.setMinimumHeight(38)
        self.start_from.addItem(i18n.t("A blank template"), None)
        self.start_from.currentIndexChanged.connect(self._on_library_pick)
        self.library_btn = C.button(i18n.t("Browse the library"), "secondary", "book", small=True, on_click=self._browse_library)
        self.ai_btn = C.button(i18n.t("Write with AI"), "secondary", "sparkles", small=True, on_click=self._write_with_ai)
        tools = QHBoxLayout()
        tools.setSpacing(theme.SPACE_2)
        tools.addWidget(self.library_btn)
        tools.addWidget(self.ai_btn)
        tools.addStretch(1)
        self.tools_field = self._field(i18n.t("Get a head start"), tools, i18n.t("Pick one of a hundred ready-made templates, or describe what you want and let AI write it."))
        form.addWidget(self.tools_field)
        self.start_field = self._field(i18n.t("Start from"), self.start_from)
        form.addWidget(self.start_field)
        if self.mode != NEW:
            self.start_field.hide()
            self.tools_field.hide()

        row = QHBoxLayout()
        row.setSpacing(theme.SPACE_3)
        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText(i18n.t("e.g. diwali_offer"))
        self.name_edit.setMinimumHeight(38)
        self.name_edit.setAccessibleName(i18n.t("Template name"))
        self.name_edit.textChanged.connect(self._name_edited)
        self.name_note = C.label("", level="META", colour=theme.WARN_INK, wrap=True)
        self.name_note.hide()
        name_field = self._field(i18n.t("Name"), self.name_edit,
                                 i18n.t("Capitals and spaces are changed for you: Meta takes lowercase letters, numbers and underscores."))
        name_field.layout().addWidget(self.name_note)
        row.addWidget(name_field, stretch=3, alignment=Qt.AlignTop)
        self.lang = QComboBox()
        self.lang.setMinimumHeight(38)
        for code, name in LANGUAGES:
            self.lang.addItem(name, code)
        self.lang.currentIndexChanged.connect(self._changed)
        row.addWidget(self._field(i18n.t("Language"), self.lang), stretch=2, alignment=Qt.AlignTop)
        form.addLayout(row)

        self.category = QComboBox()
        self.category.setMinimumHeight(38)
        self.category.addItem(i18n.t("Marketing — offers and promotions"), "MARKETING")
        self.category.addItem(i18n.t("Utility — updates about something they asked for"), "UTILITY")
        self.category.addItem(i18n.t("Authentication — one-time passwords"), "AUTHENTICATION")
        self.category.currentIndexChanged.connect(self._category_changed)
        form.addWidget(self._field(i18n.t("Category"), self.category,
                                   i18n.t("Meta decides the final category from what the message says.")))

        self.kind_box = QComboBox()
        self.kind_box.setMinimumHeight(38)
        for key, label in TK.kinds():
            self.kind_box.addItem(label, key)
        self.kind_box.currentIndexChanged.connect(self._kind_changed)
        self.kind_field = self._field(i18n.t("Type"), self.kind_box, i18n.t("What the message carries above its words."))
        form.addWidget(self.kind_field)

        self.auth_panel = TK.AuthPanel()
        self.auth_panel.changed.connect(self._changed)
        self.auth_field = self._field(i18n.t("One-time password"), self.auth_panel)
        form.addWidget(self.auth_field)
        self.auth_field.hide()

        self.header_edit = QLineEdit()
        self.header_edit.setPlaceholderText(i18n.t("Optional — a short line in bold above the message"))
        self.header_edit.setMinimumHeight(38)
        self.header_edit.setMaxLength(60)
        self.header_edit.textChanged.connect(self._changed)
        self.header_sample = QLineEdit()
        self.header_sample.setPlaceholderText(i18n.t("Sample value for the header's {{1}}"))
        self.header_sample.setMinimumHeight(38)
        self.header_sample.textChanged.connect(self._changed)
        self.header_sample.hide()
        hbox = QWidget()
        hl = QVBoxLayout(hbox)
        hl.setContentsMargins(0, 0, 0, 0)
        hl.setSpacing(theme.SPACE_2)
        hl.addWidget(self.header_edit)
        hl.addWidget(self.header_sample)
        self.header_field = self._field(i18n.t("Header"), hbox)
        form.addWidget(self.header_field)

        mbox = QWidget()
        ml = QVBoxLayout(mbox)
        ml.setContentsMargins(0, 0, 0, 0)
        ml.setSpacing(theme.SPACE_2)
        self.offer_media = QComboBox()
        self.offer_media.setMinimumHeight(38)
        self.offer_media.addItem(i18n.t("Picture"), "image")
        self.offer_media.addItem(i18n.t("Video"), "video")
        self.offer_media.currentIndexChanged.connect(self._offer_media_changed)
        self.offer_media_field = self._field(i18n.t("The offer shows a"), self.offer_media)
        ml.addWidget(self.offer_media_field)
        self.sample_picker = TK.SamplePicker("image")
        self.sample_picker.changed.connect(self._changed)
        ml.addWidget(self.sample_picker)
        self.media_field = self._field(i18n.t("Sample file"), mbox, i18n.t("Meta's reviewers look at this sample. You choose the real file each time you send."))
        form.addWidget(self.media_field)
        self.media_field.hide()

        self.offer_panel = TK.OfferPanel()
        self.offer_panel.changed.connect(self._changed)
        self.offer_field = self._field(i18n.t("The offer"), self.offer_panel)
        form.addWidget(self.offer_field)
        self.offer_field.hide()

        self.cards_editor = TK.CardsEditor()
        self.cards_editor.changed.connect(self._changed)
        self.cards_field = self._field(i18n.t("Cards"), self.cards_editor, i18n.t("Two to ten cards that scroll sideways, each a picture or video with a short text."))
        form.addWidget(self.cards_field)
        self.cards_field.hide()

        self.body_edit = QPlainTextEdit()
        self.body_edit.setPlaceholderText(i18n.t("Hello {{1}}, your order {{2}} has shipped and will reach you tomorrow."))
        self.body_edit.setFixedHeight(120)
        self.body_edit.setAccessibleName(i18n.t("Message"))
        self.body_edit.textChanged.connect(self._changed)
        self.body_count = C.label("", level="META", colour=theme.NEUTRAL[500])
        box = QWidget()
        bl = QVBoxLayout(box)
        bl.setContentsMargins(0, 0, 0, 0)
        bl.setSpacing(4)
        bl.addWidget(self.body_edit)
        bl.addWidget(self.body_count)
        self.body_field = self._field(i18n.t("Message"), box,
                                      i18n.t("Use {{1}}, {{2}}… for the parts that change for each person — never at the very start or end."))
        form.addWidget(self.body_field)

        self.samples_box = QWidget()
        self.samples_col = QVBoxLayout(self.samples_box)
        self.samples_col.setContentsMargins(0, 0, 0, 0)
        self.samples_col.setSpacing(theme.SPACE_2)
        self.samples_field = self._field(i18n.t("Sample values"), self.samples_box,
                                         i18n.t("Meta reads these to judge the message. Use realistic examples."))
        self.samples_field.hide()
        form.addWidget(self.samples_field)

        self.footer_edit = QLineEdit()
        self.footer_edit.setPlaceholderText(i18n.t("Optional — small grey text, no variables"))
        self.footer_edit.setMinimumHeight(38)
        self.footer_edit.setMaxLength(60)
        self.footer_edit.textChanged.connect(self._changed)
        self.footer_field = self._field(i18n.t("Footer"), self.footer_edit)
        form.addWidget(self.footer_field)

        self.button_rows: list = []
        bcol = QVBoxLayout()
        bcol.setSpacing(theme.SPACE_2)
        for i in range(3):
            bcol.addWidget(self._button_row(i))
        self.buttons_field = self._field(i18n.t("Buttons"), bcol,
                                         i18n.t("Up to three. Quick replies send an answer back to you; a website or call button opens it for them. "
                                                "A copy-code button gives them a coupon to copy."))
        form.addWidget(self.buttons_field)

        self.validity = QComboBox()
        self.validity.setMinimumHeight(38)
        self.validity.currentIndexChanged.connect(self._changed)
        self.validity_field = self._field(i18n.t("Message validity"), self.validity,
                                          i18n.t("How long Meta keeps trying to deliver it if the phone is off. Part of the Premium plan."))
        form.addWidget(self.validity_field)
        self._fill_validity()

        self.rewrite_row = QHBoxLayout()
        self.rewrite_btn = C.button(i18n.t("Fix it with AI"), "secondary", "sparkles", small=True, on_click=self._rewrite_with_ai)
        self.rewrite_row.addWidget(self.rewrite_btn)
        self.rewrite_row.addStretch(1)
        self.rewrite_field = self._field(i18n.t("Why Meta refused it"), self.rewrite_row, "")
        form.addWidget(self.rewrite_field)
        self.rewrite_field.hide()
        form.addStretch(1)

        # ── the phone and the verdict ────────────────────────────────────────
        right = QVBoxLayout()
        right.setSpacing(theme.SPACE_3)
        right.addWidget(C.label(i18n.t("How it will look").upper(), level="LABEL", colour=theme.NEUTRAL[500]))
        self.preview = TemplatePreview()
        right.addWidget(self.preview, stretch=1)
        self.check_box = QFrame()
        self.check_box.setObjectName("waCheck")
        self.check_box.setAttribute(Qt.WA_StyledBackground, True)
        self.check_col = QVBoxLayout(self.check_box)
        self.check_col.setContentsMargins(theme.SPACE_4, theme.SPACE_3, theme.SPACE_4, theme.SPACE_3)
        self.check_col.setSpacing(4)
        right.addWidget(self.check_box)
        wrap = QWidget()
        wrap.setLayout(right)
        wrap.setMinimumWidth(300)
        wrap.setMaximumWidth(380)
        cols.addWidget(wrap, stretch=3)

        self.submit_btn = self.button(i18n.t("Resubmit to Meta") if self.mode == RESUBMIT else i18n.t("Submit to Meta"),
                                      "primary", on_click=self._submit)
        self.footer.add_secondary(self.button(i18n.t("Cancel"), on_click=self.reject))
        self.footer.set_primary(self.submit_btn)
        self.setMinimumSize(880, 600)
        self.resize(1040, 760)

        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(450)
        self._timer.timeout.connect(self._lint)
        self._show_checks([], pending=False)
        self._changed()
        self._apply_layout()
        if prefill:
            self.fill(prefill)
            self.rewrite_field.setVisible(self.mode == RESUBMIT and bool((prefill or {}).get("reject_reason") or (prefill or {}).get("status") == "REJECTED"))
            self._template = dict(prefill)
        if self.mode == NEW:
            lw = PlatformWorker("templates/library")
            lw.done.connect(self._on_library)
            lw.failed.connect(lambda _m, _d: (self.start_field.hide(), self.library_btn.hide()))       # no library, no choice to offer
            self._w_lib = lw
            lw.start()

    # ── pieces ───────────────────────────────────────────────────────────────
    def _field(self, label: str, content, hint: str = "") -> QWidget:
        box = QWidget()
        col = QVBoxLayout(box)
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(4)
        col.addWidget(C.label(label.upper(), level="LABEL", colour=theme.NEUTRAL[500]))
        if isinstance(content, (QHBoxLayout, QVBoxLayout)):
            col.addLayout(content)
        else:
            col.addWidget(content)
        if hint:
            col.addWidget(C.label(hint, level="META", colour=theme.NEUTRAL[500], wrap=True))
        return box

    def _button_row(self, index: int) -> QWidget:
        row = QWidget()
        rl = QHBoxLayout(row)
        rl.setContentsMargins(0, 0, 0, 0)
        rl.setSpacing(theme.SPACE_2)
        kind = QComboBox()
        kind.setMinimumHeight(38)
        kind.setMinimumWidth(150)
        kind.addItem(i18n.t("No button"), "")
        kind.addItem(i18n.t("Quick reply"), QUICK)
        kind.addItem(i18n.t("Visit website"), URL)
        kind.addItem(i18n.t("Call phone"), PHONE)
        kind.addItem(i18n.t("Copy code"), COPY)
        text = QLineEdit()
        text.setPlaceholderText(i18n.t("Button {n} text").format(n=index + 1))
        text.setMinimumHeight(38)
        text.setMaxLength(25)
        text.setEnabled(False)
        value = QLineEdit()
        value.setMinimumHeight(38)
        value.hide()
        for w in (text, value):
            w.textChanged.connect(self._changed)
        kind.currentIndexChanged.connect(lambda _i, k=kind, t=text, v=value: self._button_kind_changed(k, t, v))
        rl.addWidget(kind)
        rl.addWidget(text, stretch=1)
        rl.addWidget(value, stretch=1)
        self.button_rows.append((kind, text, value))
        return row

    def _button_kind_changed(self, kind: QComboBox, text: QLineEdit, value: QLineEdit):
        k = kind.currentData()
        text.setEnabled(bool(k))
        value.setVisible(k in (URL, PHONE, COPY))
        value.setPlaceholderText(i18n.t("https://…  (end with {{1}} to add something per person)") if k == URL
                                 else i18n.t("A sample code, like FEST25") if k == COPY else i18n.t("+919876543210"))
        if not k:
            text.clear()
            value.clear()
        self._changed()

    def _name_edited(self, text: str):
        """Make the name one Meta accepts as it is typed or pasted, and say so if a character had to go."""
        cleaned, dropped = clean_name(text)
        if cleaned != text and not self.name_edit.isReadOnly():
            cursor = self.name_edit.cursorPosition() - (len(text) - len(cleaned))
            self.name_edit.blockSignals(True)
            self.name_edit.setText(cleaned)
            self.name_edit.setCursorPosition(max(0, min(cursor, len(cleaned))))
            self.name_edit.blockSignals(False)
        self.name_note.setVisible(bool(dropped))
        if dropped:
            self.name_note.setText(i18n.t("Removed {chars} — a name can only use a to z, 0 to 9 and underscores.").format(chars=" ".join(dropped)))
        self._changed()

    def buttons(self) -> list:
        return [(k.currentData(), t.text(), v.text()) for k, t, v in self.button_rows if k.currentData()]

    def kind(self) -> str:
        return self.kind_box.currentData() or "text"

    def _media_kind(self) -> str:
        """The sample picker's kind: the template's own for a picture / video / document, the chosen one for an offer."""
        return self.offer_media.currentData() if self.kind() == "offer" else self.kind()

    def data(self) -> dict:
        category = self.category.currentData()
        base = {"name": self.name_edit.text().strip(), "language": self.lang.currentData(), "category": category}
        ttl = self.validity.currentData()
        if ttl not in (None, -1):
            base["ttl_seconds"] = ttl
        if category == "AUTHENTICATION":
            base["components"] = self.auth_panel.components()
            return base
        samples = {n: e.text() for n, e in self._sample_edits.items()}
        kind = self.kind()
        offer = None
        if kind == "offer":
            offer = {"offer": self.offer_panel.component()["limited_time_offer"], "media": self._media_kind()}
        base["components"] = components_from(self.header_edit.text(), self.body_edit.toPlainText(), self.footer_edit.text(), self.buttons(), samples,
                                             self.header_sample.text(), kind=kind, handle=self.sample_picker.handle(), offer=offer, cards=self.cards_editor)
        return base

    # ── what the category and the type change ────────────────────────────────
    def _fill_validity(self):
        category = self.category.currentData()
        keep = self.validity.currentData()
        self.validity.blockSignals(True)
        self.validity.clear()
        for seconds, label in TK.validity_choices(category):
            self.validity.addItem(label, seconds)
        i = self.validity.findData(keep)
        self.validity.setCurrentIndex(max(i, 0))
        self.validity.blockSignals(False)

    def _category_changed(self, _i=None):
        self._fill_validity()
        self._apply_layout()
        self._changed()

    def _kind_changed(self, _i=None):
        if self.kind() in TK.MEDIA_KINDS:
            self.sample_picker.set_kind(self.kind())
        elif self.kind() == "offer":
            self.sample_picker.set_kind(self.offer_media.currentData())
        self._apply_layout()
        self._changed()

    def _offer_media_changed(self, _i=None):
        self.sample_picker.set_kind(self.offer_media.currentData())
        self._changed()

    def _apply_layout(self):
        """Show only the parts the chosen category and type use."""
        auth = self.category.currentData() == "AUTHENTICATION"
        kind = self.kind()
        self.kind_field.setVisible(not auth)
        self.auth_field.setVisible(auth)
        self.header_field.setVisible(not auth and kind == "text")
        self.media_field.setVisible(not auth and kind in (*TK.MEDIA_KINDS, "offer"))
        self.offer_media_field.setVisible(kind == "offer")
        self.offer_field.setVisible(not auth and kind == "offer")
        self.cards_field.setVisible(not auth and kind == "carousel")
        self.body_field.setVisible(not auth)
        self.footer_field.setVisible(not auth and kind != "carousel")
        self.buttons_field.setVisible(not auth)

    # ── filling the form ─────────────────────────────────────────────────────
    def fill(self, template: dict):
        """Put a template (a library entry, or one on file) into the form."""
        name = template.get("name") or template.get("key") or ""
        if self.mode == RESUBMIT:
            self.name_edit.setReadOnly(True)                    # the name on file is Meta's, and Meta replaces the rejected version under it
            self.lang.setEnabled(False)
        if self.mode != DUPLICATE:
            self.name_edit.setText(name)
        elif name:
            self.name_edit.setText(name + "_copy")
        i = self.lang.findData(template.get("language"))
        if i >= 0:
            self.lang.setCurrentIndex(i)
        i = self.category.findData(template.get("category"))
        if i >= 0:
            self.category.setCurrentIndex(i)
        f = fields_from(template.get("components") or [])
        self._rejected_as = template.get("reject_reason") or ""
        if template.get("category") == "AUTHENTICATION":
            self.auth_panel.fill(template.get("components") or [])
        self.kind_box.blockSignals(True)
        self.kind_box.setCurrentIndex(max(self.kind_box.findData(f["kind"]), 0))
        self.kind_box.blockSignals(False)
        if f["kind"] in TK.MEDIA_KINDS:
            self.sample_picker.set_kind(f["kind"])
            self.sample_picker.set_handle(f["handle"])
        elif f["kind"] == "offer":
            media = "video" if any(c.get("format") == "VIDEO" for c in template.get("components") or [] if c.get("type") == "HEADER") else "image"
            self.offer_media.blockSignals(True)
            self.offer_media.setCurrentIndex(max(self.offer_media.findData(media), 0))
            self.offer_media.blockSignals(False)
            self.sample_picker.set_kind(media)
            self.sample_picker.set_handle(f["handle"])
            self.offer_panel.fill(f["offer"])
        elif f["kind"] == "carousel":
            self.cards_editor.fill(f["cards"])
        ttl = template.get("ttl_seconds")
        self._fill_validity()
        if ttl:
            if self.validity.findData(ttl) < 0:
                self.validity.addItem(i18n.t("{n} seconds").format(n=ttl), ttl)
            self.validity.setCurrentIndex(self.validity.findData(ttl))
        self._apply_layout()
        self.header_edit.setText(f["header"])
        self.body_edit.setPlainText(f["body"])
        self.footer_edit.setText(f["footer"])
        for k, (kind, text, value) in enumerate(self.button_rows):
            if k < len(f["buttons"]):
                b = f["buttons"][k]
                kind.setCurrentIndex(max(kind.findData(b[0]), 0))
                text.setText(b[1])
                value.setText(b[2])
            else:
                kind.setCurrentIndex(0)
        self._rebuild_samples()
        for n, v in f["samples"].items():
            if n in self._sample_edits:
                self._sample_edits[n].setText(v)
        self.header_sample.setText(f["header_sample"])
        self._changed()

    # ── the library and the AI writer ────────────────────────────────────────
    def _browse_library(self):
        from addons.whatsapp.template_dialogs import TemplateLibraryDialog
        dlg = TemplateLibraryDialog(parent=self)
        if dlg.exec() and dlg.chosen:
            self.fill(dlg.chosen)

    def _write_with_ai(self):
        from addons.whatsapp.template_dialogs import TemplateAIDialog
        dlg = TemplateAIDialog(parent=self)
        if dlg.exec() and dlg.chosen:
            self.fill(dlg.chosen)

    def _rewrite_with_ai(self):
        from addons.whatsapp.template_dialogs import TemplateAIDialog
        dlg = TemplateAIDialog(parent=self, rewrite=getattr(self, "_template", None))
        if dlg.exec() and dlg.chosen:
            self.fill({**dlg.chosen, "name": self.name_edit.text() or dlg.chosen.get("name")})

    def _on_library(self, reply: dict):
        for item in reply.get("library") or []:
            self.start_from.addItem(item.get("title") or item.get("key", ""), item)
        self.start_field.setVisible(self.start_from.count() > 1)

    def _on_library_pick(self, index: int):
        item = self.start_from.itemData(index)
        if item:
            self.fill(item)

    # ── sample values follow the variables in the text ───────────────────────
    def _rebuild_samples(self):
        found = variables_of(self.body_edit.toPlainText())
        if found == list(self._sample_edits):
            return
        old = {n: e.text() for n, e in self._sample_edits.items()}
        while self.samples_col.count():
            discard(self.samples_col.takeAt(0).widget())
        self._sample_edits = {}
        for n in found:
            row = QWidget()
            rl = QHBoxLayout(row)
            rl.setContentsMargins(0, 0, 0, 0)
            rl.setSpacing(theme.SPACE_2)
            lab = C.label("{{%d}}" % n, level="SUPPORT", weight=700)
            lab.setFixedWidth(44)
            rl.addWidget(lab)
            e = QLineEdit(old.get(n, ""))
            e.setPlaceholderText(i18n.t("An example, e.g. Asha"))
            e.setMinimumHeight(36)
            e.setAccessibleName(i18n.t("Sample value {n}").format(n=n))
            e.textChanged.connect(self._changed)
            rl.addWidget(e, stretch=1)
            self._sample_edits[n] = e
            self.samples_col.addWidget(row)
        self.samples_field.setVisible(bool(found))

    # ── checking while typing ────────────────────────────────────────────────
    def _changed(self, *_):
        self._rebuild_samples()
        self.header_sample.setVisible(bool(variables_of(self.header_edit.text())))
        n = len(self.body_edit.toPlainText())
        self.body_count.setText(i18n.t("{n} of 1024 characters").format(n=n))
        self.body_count.setStyleSheet(f"color: {theme.ERR_INK};" if n > 1024 else f"color: {theme.NEUTRAL[500]};")
        self._preview()
        self._issues = []
        self._update_submit()
        self._timer.start()

    def _preview(self):
        auth = self.category.currentData() == "AUTHENTICATION"
        kind = self.kind()
        if auth:
            minutes = self.auth_panel.minutes.value() if self.auth_panel.expires.isChecked() else 0
            text = i18n.t("123456 is your verification code.") + (" " + i18n.t("For your security, do not share this code.") if self.auth_panel.security.isChecked() else "")
            if minutes:
                text += " " + i18n.t("This code expires in {n} minutes.").format(n=minutes)
            self.preview.set_extra("")
            self.preview.set_content("", text, "", [(COPY, self.auth_panel.button_text.text() or i18n.t("Copy code"), "")], {}, "")
            return
        extra = {"image": i18n.t("A picture goes here"), "video": i18n.t("A video goes here"), "document": i18n.t("A document goes here"),
                 "location": i18n.t("A map location goes here"),
                 "offer": i18n.t("Limited-time offer · {t}").format(t=self.offer_panel.text.text().strip() or i18n.t("your offer")),
                 "carousel": i18n.t("{n} cards, side by side").format(n=self.cards_editor.count())}.get(kind, "")
        self.preview.set_extra(extra)
        footer = self.footer_edit.text() if kind != "carousel" else ""
        self.preview.set_content(self.header_edit.text() if kind == "text" else "", self.body_edit.toPlainText(), footer,
                                 self.buttons(), {k: e.text() for k, e in self._sample_edits.items()}, self.header_sample.text())

    def _lint(self):
        data = self.data()
        if not data["name"] and not self.body_edit.toPlainText().strip() and data["category"] != "AUTHENTICATION":
            self._show_checks([], pending=False)
            return
        self._lint_token += 1
        token = self._lint_token
        w = PlatformWorker("templates/lint", data)
        w.done.connect(lambda r, t=token: self._on_lint(t, r))
        w.failed.connect(lambda m, _d, t=token: self._on_lint_failed(t, m))
        self._w_lint = w
        w.start()

    def _on_lint(self, token: int, reply: dict):
        if token != self._lint_token:
            return
        self._issues = list(reply.get("issues") or [])
        self._show_checks(self._issues, pending=False)
        self._update_submit()

    def _on_lint_failed(self, token: int, message: str):
        if token == self._lint_token:
            self._show_checks([], pending=False, unavailable=message)

    def _show_checks(self, issues: list, *, pending: bool, unavailable: str = ""):
        while self.check_col.count():
            discard(self.check_col.takeAt(0).widget())
        errors = [i for i in issues if i.get("severity") == "error"]
        warns = [i for i in issues if i.get("severity") != "error"]
        if unavailable:
            tone_bg, line = theme.WARN_BG, theme.WARN
            self.check_col.addWidget(C.label(i18n.t("Couldn't check this just now — {e}").format(e=unavailable),
                                             level="SUPPORT", colour=theme.WARN_INK, wrap=True))
        elif errors:
            tone_bg, line = theme.ERR_BG, theme.ERR_LINE
            self.check_col.addWidget(C.label(i18n.t("Meta would refuse this"), level="SUPPORT", weight=700, colour=theme.ERR_INK))
        elif warns:
            tone_bg, line = theme.WARN_BG, theme.WARN
            self.check_col.addWidget(C.label(i18n.t("Worth a look"), level="SUPPORT", weight=700, colour=theme.WARN_INK))
        elif not self.name_edit.text().strip() and (self.body_edit.toPlainText().strip() or self.category.currentData() == "AUTHENTICATION"):
            tone_bg, line = theme.WARN_BG, theme.WARN
            self.check_col.addWidget(C.label(i18n.t("Give the template a name to continue."), level="SUPPORT", colour=theme.WARN_INK, wrap=True))
        elif (self.body_edit.toPlainText().strip() or self.category.currentData() == "AUTHENTICATION") and not self._missing_samples():
            tone_bg, line = theme.OK_BG, theme.OK
            self.check_col.addWidget(C.label(i18n.t("Nothing Meta is known to refuse — ready to submit"),
                                             level="SUPPORT", weight=700, colour=theme.OK_INK, wrap=True))
        elif self._missing_samples():
            tone_bg, line = theme.WARN_BG, theme.WARN
            media = self.kind() in (*TK.MEDIA_KINDS, "offer", "carousel")
            self.check_col.addWidget(C.label(i18n.t("Choose a sample file for Meta's reviewers to continue.") if media and not self._sample_edits
                                             else i18n.t("Fill in a sample value for each {{number}} to continue."),
                                             level="SUPPORT", colour=theme.WARN_INK, wrap=True))
        else:
            tone_bg, line = theme.NEUTRAL[100], theme.HAIRLINE
            self.check_col.addWidget(C.label(i18n.t("Meta's rules are checked here as you type."),
                                             level="SUPPORT", colour=theme.NEUTRAL[600], wrap=True))
        for issue in errors + warns:
            colour = theme.ERR_INK if issue.get("severity") == "error" else theme.WARN_INK
            self.check_col.addWidget(C.label("•  " + str(issue.get("message", "")), level="SUPPORT", colour=colour, wrap=True))
        self.check_box.setStyleSheet(
            f"#waCheck {{ background: {tone_bg}; border: 1px solid {line}; border-radius: {theme.R_CONTROL}px; }}")

    def _missing_samples(self) -> bool:
        if self.category.currentData() == "AUTHENTICATION":
            return False
        if any(not e.text().strip() for e in self._sample_edits.values()):
            return True
        kind = self.kind()
        if kind in (*TK.MEDIA_KINDS, "offer") and not self.sample_picker.handle():
            return True
        if kind == "carousel" and self.cards_editor.missing_samples():
            return True
        return kind == "text" and bool(variables_of(self.header_edit.text())) and not self.header_sample.text().strip()

    def _uploading(self) -> bool:
        return self.sample_picker.busy() or self.cards_editor.busy()

    def _update_submit(self):
        d = self.data()
        auth = d["category"] == "AUTHENTICATION"
        ready = bool(d["name"] and (auth or self.body_edit.toPlainText().strip())) and not self._busy \
            and not self._missing_samples() and not self._uploading() \
            and not any(i.get("severity") == "error" for i in self._issues)
        self.submit_btn.setEnabled(ready)

    # ── submit ───────────────────────────────────────────────────────────────
    def _submit(self):
        if self._busy:
            return
        self._busy = True
        self.submit_btn.setText(i18n.t("Submitting…"))
        self._update_submit()
        w = PlatformWorker("templates/create", self.data())
        w.done.connect(self._submitted)
        w.failed.connect(self._submit_failed)
        self._w_submit = w
        w.start()

    def _submitted(self, _reply: dict):
        self._busy = False
        self.accept()

    def _submit_failed(self, message: str, detail: dict):
        self._busy = False
        self.submit_btn.setText(i18n.t("Resubmit to Meta") if self.mode == RESUBMIT else i18n.t("Submit to Meta"))
        issues = list(detail.get("issues") or [])
        if issues:
            self._issues = issues
            self._show_checks(issues, pending=False)
        else:
            self._show_checks([{"severity": "error", "message": message}], pending=False)
        if "name" in " ".join(str(i.get("message", "")) for i in (issues or [{"message": message}])).lower():
            self._scroll.ensureWidgetVisible(self.name_edit)               # the form may be scrolled past the field Meta is objecting to
        self._update_submit()
