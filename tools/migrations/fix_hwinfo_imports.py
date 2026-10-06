"""Point the two hwinfo_shared consumers at the module's new home.

hwinfo_shared.py moved from tools/ to src/common/, while its consumers are in
src/watchdog/ and src/common/. Both used to add their own directory to sys.path
and import it as a top-level module, which breaks once the files are not siblings.

Importing it as src.common.hwinfo_shared (via the repository root bootstrap) is
the version that keeps working, and it matters that BOTH consumers use the same
form: importing the same file under two different module names would load it
twice and give the two copies separate module-level state.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(r"C:\bobo_document\temp\optimize_system")

BOOTSTRAP = '''
# --- shared path resolution -------------------------------------------------
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from src.common import hwinfo_shared  # noqa: E402
from src.common import paths as _paths  # noqa: E402
'''

TARGETS = [
    r"src\watchdog\sidecar_sensors.py",
    r"src\common\read_memory_timings.py",
]


def main() -> int:
    for rel in TARGETS:
        path = ROOT / rel
        if not path.exists():
            print(f"MISSING {rel}")
            continue
        text = path.read_text(encoding="utf-8")
        original = text

        # Drop the old "add my own directory and import bare" preamble.
        text = re.sub(
            r'\nsys\.path\.insert\(0, str\(Path\(__file__\)\.resolve\(\)\.parent\)\)\n(?:\s*#[^\n]*\n)*\s*import hwinfo_shared[^\n]*\n',
            "\n", text)
        text = re.sub(r'^\s*import hwinfo_shared[^\n]*$', '', text, flags=re.M)

        # Move the bootstrap right after __future__/docstring if not present.
        if "_paths" not in text and "from src.common import hwinfo_shared" not in text:
            marker = "from __future__ import annotations\n"
            if marker in text:
                text = text.replace(marker, marker + BOOTSTRAP, 1)
            else:
                match = re.match(r'(\s*(?:#[^\n]*\n)*\s*(?:""".*?"""|\'\'\'.*?\'\'\')\s*\n)', text, re.S)
                text = (text[:match.end()] + BOOTSTRAP + text[match.end():]) if match else BOOTSTRAP + text

        # Collapse any blank-line runs the removals left behind.
        text = re.sub(r'\n{4,}', '\n\n\n', text)

        if text != original:
            path.write_text(text, encoding="utf-8")
            print(f"OK   {rel}")
        else:
            print(f"SKIP {rel} (unchanged)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
