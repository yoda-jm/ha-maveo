#!/usr/bin/env python3
"""
bintools.py — binary analysis helpers for the Maveo .so reverse-engineering workflow.

Usage:
    python bintools.py strings <pattern>              # search for strings matching pattern (with context)
    python bintools.py strings <pattern> --raw        # only print matched strings, no offsets
    python bintools.py context <hex_offset> [--n N]   # dump N printable strings near offset
    python bintools.py qml <keyword>                  # extract QML source blocks containing keyword
    python bintools.py callers <symbol>               # find ARM Thumb BL callers of a symbol
    python bintools.py symbol <name>                  # look up symbol in dynamic symbol table
    python bintools.py ghidra-strings <pattern>       # grep the Ghidra-decompiled .c file
    python bintools.py --binary PATH ...              # override default binary path

Default binary:
    ../extracted/config_arm/lib/armeabi-v7a/libmaveo-app_armeabi-v7a.so
    (relative to this script's directory)

Default Ghidra decompile:
    ../../libmaveo-app_armeabi-v7a.so.c
"""

import argparse
import os
import re
import struct
import subprocess
import sys

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_DEFAULT_SO = os.path.join(
    _SCRIPT_DIR,
    "../extracted/config_arm/lib/armeabi-v7a/libmaveo-app_armeabi-v7a.so",
)
_DEFAULT_GHIDRA_C = os.path.join(_SCRIPT_DIR, "../libmaveo-app_armeabi-v7a.so.c")


def _resolve(path):
    return os.path.normpath(path)


# ---------------------------------------------------------------------------
# Binary helpers
# ---------------------------------------------------------------------------

def _read_binary(path):
    with open(path, "rb") as f:
        return f.read()


def _extract_strings(data, min_len=4):
    """Yield (offset, string) for every printable run >= min_len bytes."""
    printable = set(range(0x20, 0x7F)) | {0x09, 0x0A, 0x0D}
    start = None
    for i, b in enumerate(data):
        if b in printable:
            if start is None:
                start = i
        else:
            if start is not None and (i - start) >= min_len:
                yield start, data[start:i].decode("ascii", errors="replace")
            start = None
    if start is not None and (len(data) - start) >= min_len:
        yield start, data[start:].decode("ascii", errors="replace")


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------

def cmd_strings(binary_path, pattern, raw=False, context=3, min_len=4):
    """Search for strings matching pattern, with surrounding string context."""
    data = _read_binary(binary_path)
    strings = list(_extract_strings(data, min_len=min_len))

    pat = re.compile(pattern, re.IGNORECASE)
    hits = [(i, off, s) for i, (off, s) in enumerate(strings) if pat.search(s)]

    if not hits:
        print(f"No strings matching {pattern!r} found.")
        return

    if raw:
        for _, _, s in hits:
            print(s)
        return

    for idx, off, s in hits:
        lo = max(0, idx - context)
        hi = min(len(strings), idx + context + 1)
        print(f"--- match @ 0x{off:08x} ---")
        for j in range(lo, hi):
            o, t = strings[j]
            marker = ">>>" if j == idx else "   "
            print(f"  {marker} 0x{o:08x}  {t!r}")
        print()


def cmd_context(binary_path, hex_offset, n=10, min_len=4):
    """Dump n strings before and after a given binary offset."""
    offset = int(hex_offset, 16)
    data = _read_binary(binary_path)
    strings = list(_extract_strings(data, min_len=min_len))

    # Find insertion point
    idx = 0
    for i, (off, _) in enumerate(strings):
        if off >= offset:
            idx = i
            break

    lo = max(0, idx - n)
    hi = min(len(strings), idx + n + 1)
    print(f"Strings near 0x{offset:08x}:")
    for j in range(lo, hi):
        o, s = strings[j]
        marker = ">>>" if abs(o - offset) < 32 else "   "
        print(f"  {marker} 0x{o:08x}  {s!r}")


def cmd_qml(binary_path, keyword, min_len=4):
    """Extract QML source blocks containing keyword (looks for JS/QML syntax)."""
    data = _read_binary(binary_path)
    strings = list(_extract_strings(data, min_len=min_len))

    pat = re.compile(keyword, re.IGNORECASE)
    # QML-like strings: contain '.', '(', '=', ':', '{', or look like identifiers
    qml_pat = re.compile(r'[.\(\)=:{}\[\]"]')

    # Find runs of QML-looking strings
    results = []
    for i, (off, s) in enumerate(strings):
        if pat.search(s) and qml_pat.search(s):
            # Include surrounding context
            lo = max(0, i - 5)
            hi = min(len(strings), i + 6)
            block = strings[lo:hi]
            results.append((off, block))

    if not results:
        print(f"No QML strings matching {keyword!r} found.")
        return

    seen = set()
    for off, block in results:
        key = block[0][0]
        if key in seen:
            continue
        seen.add(key)
        print(f"--- QML block near 0x{off:08x} ---")
        for o, s in block:
            print(f"  0x{o:08x}  {s!r}")
        print()


def cmd_callers(binary_path, symbol_name):
    """Find ARM Thumb BL/BLX callers of a symbol in the .so."""
    # Step 1: find symbol vaddr
    try:
        nm_out = subprocess.check_output(
            ["nm", "-D", "--defined-only", binary_path],
            stderr=subprocess.DEVNULL,
        ).decode()
    except FileNotFoundError:
        print("nm not found — install binutils", file=sys.stderr)
        sys.exit(1)

    target_vaddr = None
    for line in nm_out.splitlines():
        if symbol_name in line:
            parts = line.split()
            if len(parts) >= 3:
                try:
                    target_vaddr = int(parts[0], 16)
                    print(f"Symbol: {parts[2]}  vaddr=0x{target_vaddr:08x}")
                    break
                except ValueError:
                    pass

    if target_vaddr is None:
        # Try with c++filt / partial match via readelf
        try:
            re_out = subprocess.check_output(
                ["readelf", "-Ws", binary_path],
                stderr=subprocess.DEVNULL,
            ).decode()
            for line in re_out.splitlines():
                if symbol_name in line:
                    m = re.search(r'\b([0-9a-f]{8})\b', line)
                    if m:
                        target_vaddr = int(m.group(1), 16)
                        print(f"Symbol found via readelf at vaddr=0x{target_vaddr:08x}")
                        print(f"  Line: {line.strip()}")
                        break
        except FileNotFoundError:
            pass

    if target_vaddr is None:
        print(f"Symbol {symbol_name!r} not found in dynamic symbol table.")
        print("Tip: try a partial name, e.g. 'insert' or 'AWSClient'")
        return

    # Step 2: find .text section offset using readelf
    try:
        re_out = subprocess.check_output(
            ["readelf", "-S", binary_path],
            stderr=subprocess.DEVNULL,
        ).decode()
    except FileNotFoundError:
        print("readelf not found — install binutils", file=sys.stderr)
        sys.exit(1)

    text_vaddr = None
    text_offset = None
    for line in re_out.splitlines():
        if ".text" in line and "PROGBITS" in line:
            parts = line.split()
            try:
                text_vaddr = int(parts[3], 16)
                text_offset = int(parts[4], 16)
                break
            except (ValueError, IndexError):
                pass

    if text_vaddr is None:
        print("Could not find .text section.")
        return

    data = _read_binary(binary_path)

    # Step 3: scan for Thumb BL/BLX encoding
    # Thumb-2 BL: 11110xxx xxxxxxxx 11x1xxxx xxxxxxxx
    # Target = PC + 4 + (S:I1:I2:imm10:imm11 << 1)
    callers = []
    base = text_offset
    vbase = text_vaddr
    size = len(data) - base

    i = 0
    while i < size - 3:
        hw1 = struct.unpack_from("<H", data, base + i)[0]
        hw2 = struct.unpack_from("<H", data, base + i + 2)[0]

        # Check for Thumb-2 BL/BLX
        if (hw1 & 0xF800) == 0xF000 and (hw2 & 0xC000) == 0xC000:
            # Decode
            S = (hw1 >> 10) & 1
            imm10 = hw1 & 0x3FF
            J1 = (hw2 >> 13) & 1
            J2 = (hw2 >> 11) & 1
            imm11 = hw2 & 0x7FF
            I1 = (~(J1 ^ S)) & 1
            I2 = (~(J2 ^ S)) & 1
            imm32 = (S << 24) | (I1 << 23) | (I2 << 22) | (imm10 << 12) | (imm11 << 1)
            if S:
                imm32 -= (1 << 25)
            caller_vaddr = vbase + i
            target = caller_vaddr + 4 + imm32

            # BLX clears bit 1 and targets ARM; BL stays Thumb
            is_blx = (hw2 & 0x1000) == 0
            if is_blx:
                target &= ~3

            if target == target_vaddr or target == (target_vaddr & ~1):
                callers.append((caller_vaddr, "BLX" if is_blx else "BL "))
            i += 4
        else:
            i += 2

    if not callers:
        print(f"No direct BL/BLX callers found for vaddr 0x{target_vaddr:08x}.")
        print("Note: indirect/thunk calls are not detected by this scan.")
    else:
        print(f"Found {len(callers)} caller(s):")
        for vaddr, instr in callers:
            print(f"  0x{vaddr:08x}  {instr} -> 0x{target_vaddr:08x}")


def cmd_symbol(binary_path, name):
    """Look up symbols in the .so dynamic/static tables."""
    for flag in ["-D", "-a"]:
        try:
            out = subprocess.check_output(
                ["nm", flag, "--defined-only", binary_path],
                stderr=subprocess.DEVNULL,
            ).decode()
            hits = [l for l in out.splitlines() if name in l]
            if hits:
                label = "dynamic" if flag == "-D" else "all"
                print(f"--- {label} symbols matching {name!r} ---")
                for h in hits[:50]:
                    print(" ", h)
        except FileNotFoundError:
            print("nm not found — install binutils", file=sys.stderr)
            sys.exit(1)

    # Also try c++filt on readelf output
    try:
        out = subprocess.check_output(
            ["readelf", "-Ws", "--wide", binary_path],
            stderr=subprocess.DEVNULL,
        ).decode()
        hits = [l for l in out.splitlines() if name in l]
        if hits:
            print(f"--- readelf symbols matching {name!r} ---")
            for h in hits[:50]:
                print(" ", h)
    except FileNotFoundError:
        pass


def cmd_ghidra_strings(ghidra_c, pattern, context=3):
    """Grep the Ghidra-decompiled .c file for pattern with line context."""
    if not os.path.exists(ghidra_c):
        print(f"Ghidra .c file not found: {ghidra_c}", file=sys.stderr)
        sys.exit(1)

    pat = re.compile(pattern, re.IGNORECASE)
    with open(ghidra_c, "r", errors="replace") as f:
        lines = f.readlines()

    hits = [(i, l.rstrip()) for i, l in enumerate(lines) if pat.search(l)]
    if not hits:
        print(f"No lines matching {pattern!r} in {ghidra_c}")
        return

    shown = set()
    for lineno, _ in hits:
        lo = max(0, lineno - context)
        hi = min(len(lines), lineno + context + 1)
        if lo in shown:
            continue
        shown.add(lo)
        print(f"--- line {lineno + 1} ---")
        for j in range(lo, hi):
            marker = ">>>" if j == lineno else "   "
            print(f"  {marker} {j+1:6d}  {lines[j].rstrip()}")
        print()


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Maveo binary analysis toolkit",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--binary", default=_resolve(_DEFAULT_SO),
        help="Path to libmaveo-app_armeabi-v7a.so",
    )
    parser.add_argument(
        "--ghidra-c", default=_resolve(_DEFAULT_GHIDRA_C),
        help="Path to Ghidra-decompiled .c file",
    )

    sub = parser.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("strings", help="Search strings matching pattern with context")
    p.add_argument("pattern", help="Regex pattern")
    p.add_argument("--raw", action="store_true", help="Only print matched strings")
    p.add_argument("--context", type=int, default=3, metavar="N",
                   help="Number of surrounding strings to show (default: 3)")
    p.add_argument("--min-len", type=int, default=4, metavar="N",
                   help="Minimum string length (default: 4)")

    p = sub.add_parser("context", help="Dump strings near a binary offset")
    p.add_argument("offset", help="Hex offset (e.g. 0x233e29)")
    p.add_argument("--n", type=int, default=10, help="Strings before/after (default: 10)")

    p = sub.add_parser("qml", help="Find QML source blocks containing keyword")
    p.add_argument("keyword", help="Regex keyword to find")

    p = sub.add_parser("callers", help="Find ARM Thumb BL/BLX callers of a symbol")
    p.add_argument("symbol", help="Symbol name (partial match ok)")

    p = sub.add_parser("symbol", help="Look up symbol in .so symbol tables")
    p.add_argument("name", help="Symbol name (partial match ok)")

    p = sub.add_parser("ghidra-strings", help="Grep the Ghidra .c decompile")
    p.add_argument("pattern", help="Regex pattern")
    p.add_argument("--context", type=int, default=3, metavar="N",
                   help="Lines of context (default: 3)")

    args = parser.parse_args()

    if args.cmd == "strings":
        cmd_strings(args.binary, args.pattern, raw=args.raw,
                    context=args.context, min_len=args.min_len)
    elif args.cmd == "context":
        cmd_context(args.binary, args.offset, n=args.n)
    elif args.cmd == "qml":
        cmd_qml(args.binary, args.keyword)
    elif args.cmd == "callers":
        cmd_callers(args.binary, args.symbol)
    elif args.cmd == "symbol":
        cmd_symbol(args.binary, args.name)
    elif args.cmd == "ghidra-strings":
        cmd_ghidra_strings(args.ghidra_c, args.pattern, context=args.context)


if __name__ == "__main__":
    main()
