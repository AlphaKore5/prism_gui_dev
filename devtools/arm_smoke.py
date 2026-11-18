#!/usr/bin/env python3
"""Headless functional smoke of what a Windows-on-ARM customer does first:
BOQ, STEP and Email, calling the real engine / add-on functions.

    python devtools/arm_smoke.py --out smoke-out [--dwg sample.dwg] [--only env,boq,step,email,screens]

Written for the `arm.yml` job (x64 Python on a `windows-11-arm` runner, i.e.
under Windows' x64 emulation, which is how the shipped x64 build runs on a
Snapdragon laptop) but it runs on any OS, so it can be tried locally.

Each check reports PASS / FAIL / SKIP. SKIP is never a pass: it means the
check could not be run here and says why. Exit status is 1 when anything
FAILED. Results go to <out>/results.json and <out>/results.md.

Safety: HOME / USERPROFILE point at a throw-away folder BEFORE anything of
Prism's is imported, and the run refuses to continue if the engine's config
folder is not inside it. The mail checks talk only to servers this script
starts on 127.0.0.1; the accounts and passwords are made up.
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import platform
import socket
import ssl
import struct
import subprocess
import sys
import tempfile
import threading
import time
import traceback

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SANDBOX = tempfile.mkdtemp(prefix="prism-arm-smoke-home-")
os.environ["HOME"] = SANDBOX
os.environ["USERPROFILE"] = SANDBOX
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.pop("PRISM_LICENSE_OFFLINE_DEV", None)
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "prism_terminal"))   # the engine (`core`)

RESULTS: list[dict] = []


def record(group: str, name: str, status: str, detail: str = "") -> None:
    RESULTS.append({"group": group, "name": name, "status": status, "detail": detail})
    print(f"[{status}] {group}: {name}" + (f" -- {detail}" if detail else ""), flush=True)


def check(group: str, name: str):
    """Decorator: run the function, PASS on return (its return value is the
    detail), SKIP on Skip, FAIL on anything else."""
    def wrap(fn):
        try:
            detail = fn()
            record(group, name, "PASS", str(detail or ""))
        except Skip as s:
            record(group, name, "SKIP", str(s))
        except BaseException as e:                      # noqa: BLE001
            record(group, name, "FAIL", f"{type(e).__name__}: {e}")
            traceback.print_exc()
        return fn
    return wrap


class Skip(Exception):
    pass


def sandbox_guard() -> None:
    from core import config
    inside = os.path.realpath(config.CONFIG_DIR).startswith(os.path.realpath(SANDBOX))
    if not inside:
        raise SystemExit(f"refusing to run: engine config folder {config.CONFIG_DIR} "
                         f"is outside the sandbox {SANDBOX}")


# ── environment: what architecture does everything think it is on? ─────────

def pe_machine(path: str) -> str:
    """The CPU a Windows .exe/.dll was built for, from its PE header."""
    with open(path, "rb") as f:
        head = f.read(4096)
        if head[:2] != b"MZ":
            return "not a PE file"
        off = struct.unpack_from("<I", head, 0x3C)[0]
        f.seek(off)
        sig = f.read(6)
    kinds = {0x8664: "x64", 0xAA64: "arm64", 0x14C: "x86", 0x1C4: "arm32"}
    return kinds.get(struct.unpack_from("<H", sig, 4)[0], hex(struct.unpack_from("<H", sig, 4)[0]))


def run_env() -> None:
    import sysconfig

    @check("env", "who am I")
    def _():
        import updater
        info = {
            "python": sys.version.split()[0], "build": sysconfig.get_platform(),
            "platform.machine()": platform.machine(),
            "PROCESSOR_ARCHITECTURE": os.environ.get("PROCESSOR_ARCHITECTURE"),
            "PROCESSOR_ARCHITEW6432": os.environ.get("PROCESSOR_ARCHITEW6432"),
            "updater.platform_tag()": updater.platform_tag(),
        }
        from core import boq
        info["boq dwg2dxf tag"] = boq._dwg2dxf_platform_tag()
        from core import ffmpeg
        info["ffmpeg wheel tag"] = ffmpeg.platform_tag()
        print(json.dumps(info, indent=1))
        if sys.platform.startswith("win") and sysconfig.get_platform() == "win-amd64":
            assert updater.platform_tag() == "windows-x64", \
                "an x64 build must stay on the windows-x64 update channel"
        return json.dumps(info)

    @check("env", "bundled dwg2dxf is the CPU we think")
    def _():
        d = os.path.join(ROOT, "prism_terminal", "core", "vendor", "dwg2dxf", "win64")
        exe = os.path.join(d, "dwg2dxf.exe")
        if not os.path.isfile(exe):
            raise Skip("no vendor/dwg2dxf/win64 in this checkout")
        return f"dwg2dxf.exe is {pe_machine(exe)}, libredwg-0.dll is {pe_machine(os.path.join(d, 'libredwg-0.dll'))}"

    @check("env", "native libraries load and compute")
    def _():
        import numpy as np
        out = []
        out.append(f"numpy {np.__version__}: {float((np.arange(9.0).reshape(3, 3) @ np.eye(3)).sum())}")
        from PIL import Image, ImageDraw
        im = Image.new("RGB", (64, 32), "white")
        ImageDraw.Draw(im).rectangle([4, 4, 40, 20], outline="black")
        out.append(f"pillow {Image.__version__ if hasattr(Image, '__version__') else ''} ok")
        import cv2
        g = cv2.cvtColor(np.array(im), cv2.COLOR_RGB2GRAY)
        out.append(f"cv2 {cv2.__version__} mean {g.mean():.1f}")
        import shapely
        from shapely.geometry import Polygon
        out.append(f"shapely {shapely.__version__} area {Polygon([(0, 0), (2, 0), (2, 2)]).area}")
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        fig = plt.figure(figsize=(2, 2))
        fig.add_subplot(111).plot([0, 1], [0, 1])
        fig.savefig(os.path.join(SANDBOX, "mpl.png"))
        plt.close(fig)
        out.append("matplotlib Agg png ok")
        import openpyxl
        out.append(f"openpyxl {openpyxl.__version__}")
        import cryptography
        from cryptography.fernet import Fernet
        k = Fernet.generate_key()
        assert Fernet(k).decrypt(Fernet(k).encrypt(b"x")) == b"x"
        out.append(f"cryptography {cryptography.__version__} fernet ok")
        import certifi
        assert os.path.isfile(certifi.where())
        out.append("certifi bundle present")
        return "; ".join(out)

    @check("env", "OCR (rapidocr + onnxruntime) reads a rendered word")
    def _():
        from PIL import Image, ImageDraw, ImageFont
        from core import ocr
        ok, why = ocr.available()
        if not ok:
            raise Skip(why)
        im = Image.new("RGB", (400, 120), "white")
        d = ImageDraw.Draw(im)
        try:
            font = ImageFont.truetype("arial.ttf", 56)
        except OSError:
            try:
                font = ImageFont.truetype("DejaVuSans.ttf", 56)
            except OSError:
                font = ImageFont.load_default()
        d.text((10, 20), "DUCT 450", fill="black", font=font)
        p = os.path.join(SANDBOX, "ocr.png")
        im.save(p)
        t0 = time.time()
        text = ocr.text_of(p)
        if "450" not in text:
            raise AssertionError(f"OCR read {text!r}")
        return f"read {text.strip()!r} in {time.time() - t0:.1f}s"

    @check("env", "OS credential store (keyring)")
    def _():
        import keyring
        name = keyring.get_keyring().__class__.__name__
        if "fail" in name.lower() or "null" in name.lower():
            raise AssertionError(f"no usable backend: {name}")
        keyring.set_password("prism-arm-smoke", "probe", "not-a-secret")
        got = keyring.get_password("prism-arm-smoke", "probe")
        keyring.delete_password("prism-arm-smoke", "probe")
        assert got == "not-a-secret"
        return name


def run_bundle(bundle: str) -> None:
    """What CPU is every native file in the shipped (unzipped) build for?"""
    @check("bundle", "the shipped build is x64 throughout, with dwg2dxf and the Python runtime")
    def _():
        if not bundle or not os.path.isdir(bundle):
            raise Skip("no --bundle folder given")
        from collections import Counter
        kinds: Counter = Counter()
        odd: list[str] = []
        for dp, _dn, fns in os.walk(bundle):
            for fn in fns:
                if fn.lower().endswith((".exe", ".dll", ".pyd")):
                    full = os.path.join(dp, fn)
                    try:
                        k = pe_machine(full)
                    except OSError:
                        continue
                    kinds[k] += 1
                    if k not in ("x64", "not a PE file") and len(odd) < 12:
                        odd.append(f"{os.path.relpath(full, bundle)}={k}")
        dwg = [os.path.join(dp, "dwg2dxf.exe") for dp, _d, f in os.walk(bundle) if "dwg2dxf.exe" in f]
        assert dwg, "dwg2dxf.exe is not in the build"
        assert kinds.get("x64", 0) > 100, dict(kinds)
        return f"PE files by CPU {dict(kinds)}; not-x64 examples {odd}; dwg2dxf at {os.path.relpath(dwg[0], bundle)} is {pe_machine(dwg[0])}"


# ── BOQ ────────────────────────────────────────────────────────────────────

def make_dxf(path: str) -> dict:
    import ezdxf
    doc = ezdxf.new("R2018", setup=True)
    doc.units = 6                                   # metres
    for layer in ("WALLS", "DUCT", "FIXTURES"):
        doc.layers.add(layer)
    msp = doc.modelspace()
    msp.add_lwpolyline([(0, 0), (10, 0), (10, 5), (0, 5)], close=True, dxfattribs={"layer": "WALLS"})
    msp.add_line((0, 2), (6, 2), dxfattribs={"layer": "DUCT"})
    blk = doc.blocks.new("CAM-01")
    blk.add_circle((0, 0), 0.2)
    for x in (1, 3, 5):
        msp.add_blockref("CAM-01", (x, 1), dxfattribs={"layer": "FIXTURES"})
    msp.add_text("CAM-01", dxfattribs={"layer": "FIXTURES", "height": 0.3}).set_placement((1, 1.5))
    doc.saveas(path)
    return {"WALLS": 30.0, "DUCT": 6.0, "CAM-01": 3}


def run_boq(out: str, dwg: str | None) -> None:
    from core import boq, boq_price
    work = os.path.join(out, "boq")
    os.makedirs(work, exist_ok=True)
    state: dict = {}

    @check("BOQ", "DXF measured (ezdxf)")
    def _():
        p = os.path.join(work, "plan.dxf")
        want = make_dxf(p)
        q = boq.measure(p)
        state["q"] = q
        got_w, got_d = q["lengths_by_layer"].get("WALLS", 0), q["lengths_by_layer"].get("DUCT", 0)
        assert abs(got_w - want["WALLS"]) < 1e-6, f"WALLS {got_w}"
        assert abs(got_d - want["DUCT"]) < 1e-6, f"DUCT {got_d}"
        assert q["block_counts"].get("CAM-01") == want["CAM-01"], q["block_counts"]
        return f"unit={q['unit']} layers={q['layers']} entities={q['entity_count']}"

    @check("BOQ", "summary text and quantities csv")
    def _():
        q = state.get("q") or (_ for _ in ()).throw(Skip("measure failed"))
        text = boq.summary_text(q)
        assert "WALLS" in text
        boq.write_quantities_csv(q, os.path.join(work, "quantities.csv"))
        return f"{len(text)} chars"

    @check("BOQ", "priced BOQ written to .xlsx and read back (openpyxl)")
    def _():
        q = state.get("q") or (_ for _ in ()).throw(Skip("measure failed"))
        b = boq_price.boq_from_measured(q, {"WALLS": {"rate": 100}})
        path = boq_price.write_boq_xlsx(b, os.path.join(work, "boq.xlsx"))
        import openpyxl
        wb = openpyxl.load_workbook(path)
        cells = [c.value for ws in wb for row in ws.iter_rows() for c in row if c.value is not None]
        assert any("WALLS" in str(v) for v in cells), "WALLS missing from the sheet"
        return f"{os.path.getsize(path)} bytes, {len(wb.sheetnames)} sheet(s)"

    @check("BOQ", "plan drawing rendered to PNG (matplotlib)")
    def _():
        from addons.boq import cad_render
        png = os.path.join(work, "plan.png")
        target = cad_render.render_dxf_to_png(os.path.join(work, "plan.dxf"), png, dpi=80)
        target = target if isinstance(target, str) and os.path.isfile(target) else png
        assert os.path.isfile(target) and os.path.getsize(target) > 500, "no image written"
        return f"{os.path.getsize(target)} bytes"

    @check("BOQ", "DWG converted by the bundled dwg2dxf, then measured")
    def _():
        if not dwg or not os.path.isfile(dwg):
            raise Skip("no --dwg sample given; DWG NOT tested")
        if not sys.platform.startswith("win"):
            raise Skip("bundled dwg2dxf is a Windows/macOS binary; not run on this OS")
        conv = boq.find_dwg_converter()
        assert conv, f"no converter found: {boq.BUNDLED_PROBLEM!r}"
        dxf, notes = boq.ensure_dxf(dwg)
        q = boq.measure(dxf)
        assert q["entity_count"] > 0, "converted file has no entities"
        from addons.boq import cad_render
        shot = cad_render.render_dxf_to_png(cad_render.dwg_to_drawing(dwg), os.path.join(work, "dwg-preview.png"), dpi=60)
        assert os.path.getsize(shot) > 500, "DWG preview is empty"
        return f"converter={conv} [{pe_machine(conv)}] entities={q['entity_count']} layers={len(q['layers'])} notes={notes}"


# ── STEP ───────────────────────────────────────────────────────────────────

def run_step(out: str) -> None:
    from core import stepfile as SF
    work = os.path.join(out, "step")
    os.makedirs(work, exist_ok=True)
    state: dict = {}

    @check("STEP", "OpenCascade (cadquery/OCP) is available")
    def _():
        ok, why = SF.available()
        assert ok, why
        import cadquery as cq
        import OCP
        return f"cadquery {cq.__version__}, OCP {getattr(OCP, '__version__', '?')}"

    @check("STEP", "a bracket with holes is written as STEP and read back")
    def _():
        import cadquery as cq
        part = (cq.Workplane("XY").box(60, 40, 3).faces(">Z").workplane()
                .pushPoints([(-20, 0), (20, 0)]).hole(6))
        p = os.path.join(work, "bracket.step")
        cq.exporters.export(part, p)
        state["path"] = p
        parts = SF.load_parts(p)
        assert parts, "no parts read"
        return f"{os.path.getsize(p)} bytes, {len(parts)} part(s)"

    @check("STEP", "analysed: volume, holes, report text")
    def _():
        p = state.get("path") or (_ for _ in ()).throw(Skip("no model"))
        report = SF.analyse(p, mode="metal")
        state["report"] = report
        part = report["parts"][0]
        text = SF.report_text(report)
        assert text.strip(), "empty report"
        holes = part.get("holes") or []
        return f"parts={len(report['parts'])} holes={len(holes)} keys={sorted(part)[:8]}"

    @check("STEP", "Excel sheet written and read back")
    def _():
        report = state.get("report") or (_ for _ in ()).throw(Skip("no report"))
        path = SF.write_xlsx(report, os.path.join(work, "bracket.xlsx"))
        import openpyxl
        openpyxl.load_workbook(path)
        return f"{os.path.getsize(path)} bytes"

    @check("STEP", "drawing sheet PNG rendered (HLR projection + Pillow)")
    def _():
        report = state.get("report") or (_ for _ in ()).throw(Skip("no report"))
        res = SF.render_sheet(report, work)
        png = res["png"]
        from PIL import Image
        with Image.open(png) as im:
            size = im.size
            extrema = im.convert("L").getextrema()
        assert extrema[0] != extrema[1], "the sheet is one flat colour"
        state["png"] = png
        return f"{size[0]}x{size[1]} {os.path.getsize(png)} bytes"


# ── Email, against a fake IMAP + SMTP server on 127.0.0.1 ───────────────────

def make_tls(dirpath: str):
    """A throw-away CA-less self-signed cert for localhost; returns (certfile, keyfile)."""
    import datetime
    import ipaddress
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import NameOID
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "localhost")])
    now = datetime.datetime.now(datetime.timezone.utc)
    cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name)
            .public_key(key.public_key()).serial_number(x509.random_serial_number())
            .not_valid_before(now - datetime.timedelta(minutes=5))
            .not_valid_after(now + datetime.timedelta(days=1))
            .add_extension(x509.SubjectAlternativeName(
                [x509.DNSName("localhost"), x509.IPAddress(ipaddress.ip_address("127.0.0.1"))]), False)
            .add_extension(x509.BasicConstraints(ca=True, path_length=None), True)
            .sign(key, hashes.SHA256()))
    cf, kf = os.path.join(dirpath, "cert.pem"), os.path.join(dirpath, "key.pem")
    with open(cf, "wb") as f:
        f.write(cert.public_bytes(serialization.Encoding.PEM))
    with open(kf, "wb") as f:
        f.write(key.private_bytes(serialization.Encoding.PEM,
                                  serialization.PrivateFormat.TraditionalOpenSSL,
                                  serialization.NoEncryption()))
    return cf, kf


class _Conn:
    """Line reader/writer that survives a STARTTLS upgrade."""

    def __init__(self, sock):
        self.sock, self.buf = sock, b""

    def send(self, data: bytes | str) -> None:
        self.sock.sendall(data if isinstance(data, bytes) else data.encode())

    def line(self) -> bytes | None:
        while b"\r\n" not in self.buf:
            chunk = self.sock.recv(65536)
            if not chunk:
                return None
            self.buf += chunk
        ln, self.buf = self.buf.split(b"\r\n", 1)
        return ln

    def literal(self, n: int) -> bytes:
        while len(self.buf) < n:
            self.buf += self.sock.recv(65536)
        data, self.buf = self.buf[:n], self.buf[n:]
        return data

    def starttls(self, ctx) -> None:
        self.sock = ctx.wrap_socket(self.sock, server_side=True)
        self.buf = b""


class FakeMail:
    """Just enough IMAP4 (STARTTLS, LOGIN, SELECT, UID SEARCH/FETCH, LIST,
    APPEND, LOGOUT) and SMTP (STARTTLS, AUTH PLAIN/LOGIN, DATA) for Prism's
    own code paths. Not a general server."""
    USER, PASSWORD = "sales@prism-arm.test", "fake-password-not-real"

    def __init__(self, certfile: str, keyfile: str, messages: list[bytes]):
        self.ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        self.ctx.load_cert_chain(certfile, keyfile)
        self.messages = messages
        self.received: list[bytes] = []
        self.log: list[str] = []
        self.imap_sock = self._listen()
        self.smtp_sock = self._listen()
        self.imap_port = self.imap_sock.getsockname()[1]
        self.smtp_port = self.smtp_sock.getsockname()[1]
        for sock, fn in ((self.imap_sock, self._imap), (self.smtp_sock, self._smtp)):
            threading.Thread(target=self._accept, args=(sock, fn), daemon=True).start()

    @staticmethod
    def _listen():
        s = socket.socket()
        s.bind(("127.0.0.1", 0))
        s.listen(8)
        return s

    def _accept(self, sock, fn):
        while True:
            try:
                c, _ = sock.accept()
            except OSError:
                return
            c.settimeout(30)
            threading.Thread(target=self._guard, args=(fn, c), daemon=True).start()

    def _guard(self, fn, c):
        try:
            fn(_Conn(c))
        except Exception as e:                           # noqa: BLE001
            self.log.append(f"server error: {e}")
        finally:
            try:
                c.close()
            except OSError:
                pass

    def close(self):
        for s in (self.imap_sock, self.smtp_sock):
            s.close()

    # IMAP
    def _imap(self, c: _Conn):
        c.send("* OK IMAP4rev1 fake ready\r\n")
        authed = False
        while True:
            ln = c.line()
            if ln is None:
                return
            text = ln.decode("utf-8", "replace")
            tag, _, rest = text.partition(" ")
            cmd = rest.split(" ", 1)[0].upper()
            args = rest[len(cmd):].strip()
            self.log.append(f"IMAP< {cmd}")
            if cmd == "CAPABILITY":
                c.send(f"* CAPABILITY IMAP4rev1 STARTTLS\r\n{tag} OK done\r\n")
            elif cmd == "STARTTLS":
                c.send(f"{tag} OK begin TLS\r\n")
                c.starttls(self.ctx)
            elif cmd == "LOGIN":
                ok = self.USER in args and self.PASSWORD in args
                authed = ok
                c.send(f"{tag} OK logged in\r\n" if ok else f"{tag} NO [AUTHENTICATIONFAILED] bad login\r\n")
            elif cmd == "SELECT" or cmd == "EXAMINE":
                n = len(self.messages)
                c.send(f"* {n} EXISTS\r\n* OK [UIDVALIDITY 77] ok\r\n{tag} OK [READ-ONLY] selected\r\n")
            elif cmd == "LIST":
                c.send(f'* LIST (\\HasNoChildren \\Sent) "/" "Sent"\r\n{tag} OK done\r\n')
            elif cmd == "UID":
                sub, _, a2 = args.partition(" ")
                if sub.upper() == "SEARCH":
                    ids = " ".join(str(i + 1) for i in range(len(self.messages)))
                    c.send(f"* SEARCH {ids}\r\n{tag} OK done\r\n")
                elif sub.upper() == "FETCH":
                    uid = int(a2.split(" ", 1)[0])
                    if 1 <= uid <= len(self.messages):
                        raw = self.messages[uid - 1]
                        c.send(f"* {uid} FETCH (UID {uid} BODY[] {{{len(raw)}}}\r\n".encode() + raw + b")\r\n")
                    c.send(f"{tag} OK done\r\n")
                else:
                    c.send(f"{tag} BAD unsupported\r\n")
            elif cmd == "APPEND":
                n = int(args.rsplit("{", 1)[1].rstrip("}+"))
                c.send("+ go ahead\r\n")
                self.received.append(c.literal(n))
                c.line()
                c.send(f"{tag} OK appended\r\n")
            elif cmd in ("NOOP", "CLOSE"):
                c.send(f"{tag} OK done\r\n")
            elif cmd == "LOGOUT":
                c.send(f"* BYE\r\n{tag} OK bye\r\n")
                return
            else:
                c.send(f"{tag} BAD unsupported {cmd}\r\n")
            _ = authed

    # SMTP
    def _smtp(self, c: _Conn):
        c.send("220 localhost fake ESMTP\r\n")
        authed = tls = False
        while True:
            ln = c.line()
            if ln is None:
                return
            text = ln.decode("utf-8", "replace")
            cmd = text.split(" ", 1)[0].upper()
            self.log.append(f"SMTP< {cmd}")
            if cmd in ("EHLO", "HELO"):
                lines = ["250-localhost"]
                lines.append("250-AUTH PLAIN LOGIN" if tls else "250-STARTTLS")
                lines.append("250 8BITMIME")
                c.send("\r\n".join(lines) + "\r\n")
            elif cmd == "STARTTLS":
                c.send("220 ready\r\n")
                c.starttls(self.ctx)
                tls = True
            elif cmd == "AUTH":
                parts = text.split()
                if parts[1].upper() == "PLAIN":
                    blob = parts[2] if len(parts) > 2 else (c.send("334 \r\n"), c.line().decode())[1]
                    _, user, pw = base64.b64decode(blob).decode().split("\x00")
                else:
                    c.send("334 VXNlcm5hbWU6\r\n")
                    user = base64.b64decode(c.line()).decode()
                    c.send("334 UGFzc3dvcmQ6\r\n")
                    pw = base64.b64decode(c.line()).decode()
                authed = (user, pw) == (self.USER, self.PASSWORD)
                c.send("235 ok\r\n" if authed else "535 5.7.8 bad credentials\r\n")
            elif cmd in ("MAIL", "RCPT"):
                c.send("250 ok\r\n" if authed else "530 auth first\r\n")
            elif cmd == "DATA":
                c.send("354 go\r\n")
                body = []
                while True:
                    ln2 = c.line()
                    if ln2 is None:
                        return
                    if ln2 == b".":
                        break
                    body.append(ln2[1:] if ln2.startswith(b"..") else ln2)
                self.received.append(b"\r\n".join(body) + b"\r\n")
                c.send("250 queued\r\n")
            elif cmd in ("RSET", "NOOP"):
                c.send("250 ok\r\n")
            elif cmd == "QUIT":
                c.send("221 bye\r\n")
                return
            else:
                c.send("502 unsupported\r\n")


def sample_inquiry_mail() -> list[bytes]:
    from email.message import EmailMessage
    a = EmailMessage()
    a["From"] = "Ravi Kumar <ravi@buyer.example>"
    a["To"] = FakeMail.USER
    a["Subject"] = "Inquiry: 40 brackets, drawing attached"
    a["Message-ID"] = "<one@buyer.example>"
    a["Date"] = "Mon, 16 Nov 2026 10:15:00 +0530"
    a.set_content("Hello,\nPlease quote 40 mounting brackets as per the attached drawing.\nRegards, Ravi")
    a.add_attachment(b"%PDF-1.4\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF\n", maintype="application",
                     subtype="pdf", filename="bracket drawing.pdf")
    b = EmailMessage()
    b["From"] = "Meera <meera@other.example>"
    b["To"] = FakeMail.USER
    b["Subject"] = "Re: lead time?"
    b["Message-ID"] = "<two@other.example>"
    b["Date"] = "Mon, 16 Nov 2026 11:00:00 +0530"
    b.set_content("Plain follow-up, no attachment.")
    return [a.as_bytes(policy=a.policy.clone(linesep="\r\n")), b.as_bytes(policy=b.policy.clone(linesep="\r\n"))]


def run_email(out: str) -> None:
    from core import inbox, mailer, register
    work = os.path.join(out, "email")
    os.makedirs(work, exist_ok=True)
    cf, kf = make_tls(work)
    srv = FakeMail(cf, kf, sample_inquiry_mail())

    # The real code builds its own default TLS context (OS trust store). The
    # fake server's certificate is not in it, so hand the same call a context
    # that trusts exactly that one certificate. Everything else (handshake,
    # hostname check, STARTTLS) is the real thing.
    real_default = ssl.create_default_context
    ssl.create_default_context = lambda *a, **k: real_default(cafile=cf)
    cfg = {
        "inbox": {"address": FakeMail.USER, "password": FakeMail.PASSWORD, "host": "localhost",
                  "port": srv.imap_port, "folder": "INBOX"},
        "email": {"address": FakeMail.USER, "password": FakeMail.PASSWORD, "host": "localhost",
                  "port": srv.smtp_port, "save_to_sent": False},
    }
    state: dict = {}
    try:
        @check("Email", "IMAP login over STARTTLS (verify)")
        def _():
            err = inbox.verify(cfg)
            assert err == "", err
            return "signed in and opened INBOX"

        @check("Email", "wrong password is explained, not a traceback")
        def _():
            bad = {"inbox": dict(cfg["inbox"], password="nope")}
            err = inbox.verify(bad)
            assert err and "Traceback" not in err, repr(err)
            return err[:90]

        @check("Email", "fetched, parsed, attachment kept")
        def _():
            msgs, st, err = inbox.fetch_new(cfg, None, timeout=30)
            assert err == "", err
            assert [m.subject for m in msgs] == ["Inquiry: 40 brackets, drawing attached", "Re: lead time?"], \
                [m.subject for m in msgs]
            m0 = msgs[0]
            assert m0.from_addr == "ravi@buyer.example" and "40 mounting brackets" in m0.body
            assert m0.attachment_names == ["bracket drawing.pdf"], m0.attachment_names
            saved = inbox.save_attachments(m0, os.path.join(work, "att"))
            assert saved and os.path.getsize(saved[0]) > 10
            state["msgs"], state["st"] = msgs, st
            return f"{len(msgs)} messages, last_uid={st.last_uid}, attachment saved ({os.path.basename(saved[0])})"

        @check("Email", "second check finds nothing new (bookmark honoured)")
        def _():
            st = state.get("st") or (_ for _ in ()).throw(Skip("first fetch failed"))
            # The fake server answers UID n:* with every id; Prism must filter.
            msgs, st2, err = inbox.fetch_new(cfg, st, timeout=30)
            assert err == "" and msgs == [], (err, len(msgs))
            return "0 new"

        @check("Email", "inquiry register row built, saved, reloaded")
        def _():
            msgs = state.get("msgs") or (_ for _ in ()).throw(Skip("no messages"))
            row = register.from_message(msgs[0], {"product": "mounting brackets", "quantity": "40"})
            path = register.path_in(work)
            register.save([row], path)
            back = register.load(path)
            assert back and back[0]["Email"] == "ravi@buyer.example" and back[0]["Drawing"] == "bracket drawing.pdf", back
            return f"{back[0]['Inquiry no']} at {os.path.basename(path)}"

        @check("Email", "drafting reply is parsed (offline half; the AI call itself is not run)")
        def _():
            got = mailer.parse_draft("SUBJECT: Quote for 40 brackets\nBODY:\nHi {name},\nPlease find our quote.\n")
            assert got and got[0] == "Quote for 40 brackets" and "{name}" in got[1], got
            assert mailer.draft_question("quote reply to a bracket inquiry").strip()
            return "parse_draft + draft_question ok"

        @check("Email", "SMTP login over STARTTLS (verify)")
        def _():
            err = mailer.verify(cfg)
            assert err == "", err
            return "ok"

        @check("Email", "message with attachment sent, arrives intact")
        def _():
            att = os.path.join(work, "quote.pdf")
            with open(att, "wb") as f:
                f.write(b"%PDF-1.4 quote\n")
            srv.received.clear()
            sent, failed = mailer.send_bulk(
                cfg, [{"email": "ravi@buyer.example", "name": "Ravi"}],
                "Quote Q-1 for {name}", "Dear {name}, quote attached.",
                [{"path": att, "name": "quote.pdf", "mime": "application/pdf"}], delay=0)
            assert sent == ["ravi@buyer.example"] and not failed, (sent, failed)
            import email
            got = email.message_from_bytes(srv.received[-1])
            assert got["Subject"] == "Quote Q-1 for Ravi", got["Subject"]
            names = [p.get_filename() for p in got.walk() if p.get_filename()]
            assert names == ["quote.pdf"], names
            return f"subject={got['Subject']!r} attachment={names[0]}"
    finally:
        ssl.create_default_context = real_default
        srv.close()


# ── screenshots (offscreen grab) ───────────────────────────────────────────

def run_screens(out: str) -> None:
    work = os.path.join(out, "screens")
    os.makedirs(work, exist_ok=True)
    try:
        from PySide6.QtWidgets import QApplication, QVBoxLayout, QWidget
    except Exception as e:                               # noqa: BLE001
        record("screens", "PySide6 imports", "FAIL", str(e))
        return
    app = QApplication.instance() or QApplication([])
    import theme
    theme.load_fonts()
    with open(os.path.join(ROOT, "style.qss"), encoding="utf-8") as f:
        app.setStyleSheet(f.read().replace("%ASSETS%", os.path.join(ROOT, "assets").replace(os.sep, "/")))
    keep: list = []

    def shot(name, make):
        @check("screens", name)
        def _():
            w = make()
            keep.append(w)
            w.resize(1100, 760)
            w.show()
            app.sendPostedEvents()
            img = w.grab().toImage()
            p = os.path.join(work, name.lower().replace(" ", "-") + ".png")
            assert img.save(p), "could not write the png"
            assert img.width() > 200 and not img.isNull()
            return f"{img.width()}x{img.height()} -> {os.path.basename(p)}"

    def boq():
        from addons.boq.dialog import BoqDialog
        d = BoqDialog({"api_key": "k"}, [], None, mode="boq")
        d._measure = lambda: None
        return d

    def step():
        from addons.step import dialog as SD
        host = QWidget()
        QVBoxLayout(host).setContentsMargins(0, 0, 0, 0)
        d = SD.StepDialog({"step_out_dir": tempfile.mkdtemp()}, [], host, embedded=True)
        host.layout().addWidget(d)
        return host

    def email():
        from addons.email.panel import EmailPanel
        acct = {"address": "sales@sample.example", "password": "pw", "host": "smtp.sample.example", "port": 587}
        return EmailPanel({"email": dict(acct, folder=tempfile.mkdtemp(), accounts=[acct])})

    shot("BOQ screen", boq)
    shot("STEP screen", step)
    shot("Email screen", email)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=os.path.join(ROOT, "arm-smoke-out"))
    ap.add_argument("--dwg", default="")
    ap.add_argument("--bundle", default="", help="unzipped shipped build, for the per-file CPU census")
    ap.add_argument("--only", default="env,bundle,boq,step,email,screens")
    args = ap.parse_args()
    out = os.path.abspath(args.out)
    os.makedirs(out, exist_ok=True)
    only = {s.strip() for s in args.only.split(",")}
    sandbox_guard()
    print(f"sandbox HOME={SANDBOX}\nout={out}\n", flush=True)
    for key, fn in (("env", lambda: run_env()), ("bundle", lambda: run_bundle(args.bundle)), ("boq", lambda: run_boq(out, args.dwg or None)),
                    ("step", lambda: run_step(out)), ("email", lambda: run_email(out)),
                    ("screens", lambda: run_screens(out))):
        if key in only:
            try:
                fn()
            except BaseException as e:                   # noqa: BLE001
                record(key, "group crashed", "FAIL", f"{type(e).__name__}: {e}")
                traceback.print_exc()
    with open(os.path.join(out, "results.json"), "w", encoding="utf-8") as f:
        json.dump({"machine": platform.machine(), "python": sys.version, "results": RESULTS}, f, indent=1)
    counts = {s: sum(1 for r in RESULTS if r["status"] == s) for s in ("PASS", "FAIL", "SKIP")}
    lines = [f"| {r['group']} | {r['name']} | {r['status']} | {r['detail'][:160].replace('|', '/')} |" for r in RESULTS]
    with open(os.path.join(out, "results.md"), "w", encoding="utf-8") as f:
        f.write(f"**{counts['PASS']} passed, {counts['FAIL']} failed, {counts['SKIP']} skipped** "
                f"(python {sys.version.split()[0]} {platform.machine()})\n\n"
                "| area | check | result | detail |\n|---|---|---|---|\n" + "\n".join(lines) + "\n")
    print(f"\n{counts}")
    return 1 if counts["FAIL"] else 0


if __name__ == "__main__":
    sys.exit(main())
