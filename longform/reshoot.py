"""Re-shoot screenshots from their saved JSON — same URL, size and marks.

    python -m longform.reshoot SHOTS_DIR name [name ...]

Use after changing ``longform.shoot`` (e.g. how marks are measured), or when
a page has changed and the marks need re-locating.
"""
import json
import subprocess
import sys
from pathlib import Path


def main():
    if len(sys.argv) < 3:
        sys.exit(__doc__)
    shots = Path(sys.argv[1])
    for name in sys.argv[2:]:
        meta = json.loads((shots / f"{name}.json").read_text(encoding="utf-8"))
        args = [sys.executable, "-m", "longform.shoot", str(shots / f"{name}.png"), meta["url"],
                "--width", str(meta["imgW"] // 2), "--height", str(meta["imgH"] // 2)]
        for mk in meta["marks"]:
            args += ["--mark", mk["phrase"]]
        r = subprocess.run(args, capture_output=True, text=True, encoding="utf-8",
                           cwd=Path(__file__).resolve().parent.parent)
        print(name, (r.stdout.strip().splitlines() or ["?"])[-1][:160], r.stderr.strip()[-200:])


if __name__ == "__main__":
    main()
