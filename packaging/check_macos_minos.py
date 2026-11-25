#!/usr/bin/env python3
"""Does anything in the built Prism.app need a newer macOS than we promise?

    python packaging/check_macos_minos.py dist/Prism.app 13.0

Every Mac program and library records the oldest macOS it was built for. One
library that needs macOS 14 inside an app sold as "macOS 13 and later" opens
fine on the build Mac and fails on the customer's, so this reads every binary in
the bundle and exits 1 if any needs more than the target.

The target (MACOSX_DEPLOYMENT_TARGET in .github/workflows/build.yml) only
controls what the build itself compiles. Libraries downloaded ready-made from
PyPI bring their own minimum; when one is listed here, either pin an older
version in constraints/macos-arm64.txt or raise the target.

It reads the Mach-O headers directly (what `otool -l` prints as LC_BUILD_VERSION
minos, or the older LC_VERSION_MIN_MACOSX), so its test runs on every platform.
"""
from __future__ import annotations

import os
import struct
import sys

MH_MAGIC_64 = 0xFEEDFACF
FAT_MAGIC, FAT_MAGIC_64 = 0xCAFEBABE, 0xCAFEBABF
CPU_ARM64 = 0x0100000C
LC_VERSION_MIN_MACOSX, LC_BUILD_VERSION = 0x24, 0x32
PLATFORM_MACOS = 1


def _version(packed: int) -> tuple[int, int, int]:
    return packed >> 16, (packed >> 8) & 0xFF, packed & 0xFF


def _thin(f, base: int) -> tuple[int, int, int] | None:
    f.seek(base)
    head = f.read(32)
    if len(head) < 32 or struct.unpack("<I", head[:4])[0] != MH_MAGIC_64:
        return None
    ncmds, size = struct.unpack("<II", head[16:24])
    cmds, at = f.read(size), 0
    for _ in range(ncmds):
        cmd, length = struct.unpack_from("<II", cmds, at)
        if cmd == LC_BUILD_VERSION:
            platform, minos = struct.unpack_from("<II", cmds, at + 8)
            if platform == PLATFORM_MACOS:
                return _version(minos)
        elif cmd == LC_VERSION_MIN_MACOSX:
            return _version(struct.unpack_from("<I", cmds, at + 8)[0])
        at += length
    return None


def minimum_macos(path: str) -> tuple[bool, tuple[int, int, int] | None]:
    """(is it a Mac binary, the oldest macOS its Apple Silicon code runs on)."""
    with open(path, "rb") as f:
        head = f.read(8)
        if len(head) < 8:
            return False, None
        if struct.unpack("<I", head[:4])[0] == MH_MAGIC_64:
            return True, _thin(f, 0)
        magic, count = struct.unpack(">II", head)
        # 0xCAFEBABE also opens a Java class file; its "count" is a version >= 45.
        if magic not in (FAT_MAGIC, FAT_MAGIC_64) or not 0 < count < 20:
            return False, None
        entry = ">IIIII" if magic == FAT_MAGIC else ">IIQQII"
        table = f.read(struct.calcsize(entry) * count)
        for cpu, _sub, offset, *_rest in struct.iter_unpack(entry, table):
            if cpu == CPU_ARM64:
                return True, _thin(f, offset)
    return True, None


def scan(root: str) -> list[tuple[str, tuple[int, int, int] | None]]:
    found = []
    for folder, _dirs, files in os.walk(root):
        for name in sorted(files):
            path = os.path.join(folder, name)
            if os.path.islink(path) or not os.path.isfile(path):
                continue
            is_macho, minos = minimum_macos(path)
            if is_macho:
                found.append((os.path.relpath(path, root), minos))
    return found


def main(argv: list[str]) -> int:
    root, target = argv
    want = (tuple(int(p) for p in target.split(".")) + (0, 0))[:3]
    found = scan(root)
    if not found:
        print(f"::error::no Mac binaries found under {root}: nothing was checked")
        return 2
    newer = sorted((m, p) for p, m in found if m and m > want)
    unknown = [p for p, m in found if m is None]
    print(f"{len(found)} Mac binaries, target macOS {target}: {len(newer)} need a newer macOS, "
          f"{len(unknown)} record no minimum for Apple Silicon")
    for path in unknown:
        print(f"  no minimum recorded: {path}")
    for minos, path in newer:
        print(f"  needs macOS {'.'.join(map(str, minos))}: {path}")
    if newer:
        print(f"::error::{len(newer)} file(s) in {os.path.basename(root)} need a newer macOS than "
              f"{target}. Pin an older version of that library in constraints/macos-arm64.txt, or "
              "raise MACOSX_DEPLOYMENT_TARGET in .github/workflows/build.yml "
              "(docs/MAC_BUILD_RUNNER.md, part 7).")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
