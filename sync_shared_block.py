"""
Keep the shared scrape block identical in both monitor scripts (rule 13)
------------------------------------------------------------------------
Rule 13 says a change to scraping logic lands in BOTH scripts in the same
commit. The last time that was done by hand they drifted anyway: the
local "reference implementation" ended up with none of the fixes it was
supposed to be the reference for -- no Arabic normalisation, no sorted
hashing, and a networkidle + fixed-sleep wait that rule 7 forbids.

alahly_ticket_check.py is the source of truth. Edit the block there, then:

    python sync_shared_block.py             copy into the monitor, verify
    python sync_shared_block.py --check     verify only; exit 1 if drifted

The --check form is what to run before committing.
"""

import sys
import hashlib

SOURCE = "alahly_ticket_check.py"
TARGET = "alahly_ticket_monitor.py"

BEGIN = "# BEGIN SHARED SCRAPE BLOCK (rule 13)"
END = "# END SHARED SCRAPE BLOCK (rule 13)"


def read_lines(path: str) -> list:
    with open(path, encoding="utf-8") as f:
        return f.readlines()


def block_bounds(lines: list, path: str) -> tuple:
    """Index of the BEGIN and END marker lines, inclusive."""
    start = end = None
    for i, line in enumerate(lines):
        if line.strip() == BEGIN:
            if start is not None:
                raise SystemExit(f"{path}: more than one {BEGIN!r}")
            start = i
        elif line.strip() == END:
            if end is not None:
                raise SystemExit(f"{path}: more than one {END!r}")
            end = i
    if start is None or end is None:
        raise SystemExit(f"{path}: missing the shared-block markers.")
    if end <= start:
        raise SystemExit(f"{path}: END marker appears before BEGIN.")
    return start, end


def extract(path: str) -> tuple:
    lines = read_lines(path)
    start, end = block_bounds(lines, path)
    return lines, start, end, lines[start:end + 1]


def digest(block: list) -> str:
    return hashlib.sha256("".join(block).encode("utf-8")).hexdigest()


def main() -> int:
    check_only = "--check" in sys.argv[1:]

    _, _, _, source_block = extract(SOURCE)
    target_lines, t_start, t_end, target_block = extract(TARGET)

    if source_block == target_block:
        print(f"In sync: {len(source_block)} lines, sha256 "
              f"{digest(source_block)[:12]}...")
        return 0

    if check_only:
        print(f"DRIFTED: the shared block in {TARGET} differs from {SOURCE}.",
              file=sys.stderr)
        print(f"  {SOURCE}: {len(source_block)} lines, "
              f"{digest(source_block)[:12]}...", file=sys.stderr)
        print(f"  {TARGET}: {len(target_block)} lines, "
              f"{digest(target_block)[:12]}...", file=sys.stderr)
        print("Run 'python sync_shared_block.py' to fix.", file=sys.stderr)
        return 1

    updated = target_lines[:t_start] + source_block + target_lines[t_end + 1:]
    with open(TARGET, "w", encoding="utf-8", newline="") as f:
        f.writelines(updated)

    # Re-extract and compare rather than trusting the write.
    _, _, _, written = extract(TARGET)
    if written != source_block:
        print("Copied, but the two blocks still differ. Do NOT commit.",
              file=sys.stderr)
        return 1

    print(f"Copied {len(source_block)} lines from {SOURCE} into {TARGET}. "
          f"Verified identical: sha256 {digest(source_block)[:12]}...")
    return 0


if __name__ == "__main__":
    sys.exit(main())
