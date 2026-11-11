#!/usr/bin/env python3
"""Apply the small MinGW compatibility fixes needed by e2fsck 1.47.4."""
from __future__ import annotations

import re
import sys
from pathlib import Path


def replace_one(pattern: re.Pattern[str], replacement: str, text: str, label: str) -> str:
    updated, count = pattern.subn(replacement, text, count=1)
    if count != 1:
        raise RuntimeError(f"Expected exactly one {label} match; found {count}.")
    return updated


def main() -> int:
    if len(sys.argv) != 2:
        print("Usage: patch-e2fsck-windows.py PATH/TO/e2fsck/unix.c", file=sys.stderr)
        return 2

    source = Path(sys.argv[1])
    if not source.is_file():
        raise FileNotFoundError(source)

    text = source.read_text(encoding="utf-8").replace("\r\n", "\n")

    # This routine only reads Linux /sys and /proc battery interfaces. Do not
    # compile those POSIX-only paths into the native Windows executable.
    batt_pattern = re.compile(
        r"(?ms)^static int is_on_batt\(void\)\n\{(?P<body>.*?)^\}"
    )
    batt_match = batt_pattern.search(text)
    if not batt_match:
        raise RuntimeError("Could not locate the upstream is_on_batt() function.")
    batt_body = batt_match.group("body")
    batt_replacement = (
        "static int is_on_batt(void)\n{\n"
        "#ifdef _WIN32\n"
        "\t/* Linux /sys and /proc power-supply interfaces are unavailable. */\n"
        "\treturn 0;\n"
        "#else"
        + batt_body.rstrip("\n")
        + "\n#endif\n}"
    )
    text = batt_pattern.sub(batt_replacement, text, count=1)

    # MinGW's signal.h has signal(), but not the POSIX sigaction API or
    # SIGUSR1/SIGUSR2. Keep the POSIX setup for Unix and use CRT signal()
    # for Ctrl+C / termination on Windows.
    decl_pattern = re.compile(
        r"(?m)^#ifdef HAVE_SIGNAL_H\n(?P<decl>[ \t]*struct sigaction[ \t]+sa;)\n#endif$"
    )
    decl_match = decl_pattern.search(text)
    if not decl_match:
        raise RuntimeError("Could not locate the sigaction declaration in PRS().")
    decl = decl_match.group("decl")
    text = decl_pattern.sub(
        "#if defined(HAVE_SIGNAL_H) && !defined(_WIN32)\n" + decl + "\n#endif",
        text,
        count=1,
    )

    signal_pattern = re.compile(
        r"(?ms)^#ifdef HAVE_SIGNAL_H\n"
        r"(?P<body>[ \t]*/\*\n[ \t]*\* Set up signal action\n[ \t]*\*/"
        r".*?^[ \t]*sigaction\(SIGUSR2,\s*&sa,\s*0\);\n)"
        r"^#endif\b"
    )
    signal_match = signal_pattern.search(text)
    if not signal_match:
        raise RuntimeError("Could not locate the POSIX signal setup block in PRS().")
    posix_signal_setup = signal_match.group("body")
    signal_replacement = (
        "#ifdef HAVE_SIGNAL_H\n"
        "#ifdef _WIN32\n"
        "\tsignal(SIGINT, signal_cancel);\n"
        "\tsignal(SIGTERM, signal_cancel);\n"
        "#else\n"
        + posix_signal_setup
        + "#endif /* !_WIN32 */\n"
        "#endif /* HAVE_SIGNAL_H */"
    )
    text = signal_pattern.sub(signal_replacement, text, count=1)

    # ext2_io.h maps default_io_manager to windows_io_manager under _WIN32
    # and to unix_io_manager on Unix. Use that upstream abstraction at all
    # three call sites (including the optional test-I/O backing manager).
    manager_refs = text.count("unix_io_manager")
    if manager_refs != 3:
        raise RuntimeError(
            f"Expected exactly 3 unix_io_manager references in upstream 1.47.4; found {manager_refs}."
        )
    text = text.replace("unix_io_manager", "default_io_manager")

    if "unix_io_manager" in text:
        raise RuntimeError("A unix_io_manager reference remains after patching.")
    if text.count("default_io_manager") != 3:
        raise RuntimeError("The expected default_io_manager references were not installed.")

    source.write_text(text, encoding="utf-8", newline="\n")
    print("Patched e2fsck/unix.c for native MinGW-w64:")
    print("  - bypass Linux-only battery status probing on Windows")
    print("  - use Windows CRT signal() for SIGINT/SIGTERM")
    print("  - select default_io_manager (windows_io_manager on _WIN32)")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:  # make CI failures actionable
        print(f"PATCH ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)
