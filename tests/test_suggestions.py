"""Checking the Worker that receives the "I know more" suggestions (cloudflare/api.js), with a fake database and fake CAPTCHA
(node is needed for it). Run: py tests/test_suggestions.py"""
import shutil
import subprocess
import tempfile
from pathlib import Path
from test_common import ROOT, check, warn, end_

WORKER = ROOT / "cloudflare" / "api.js"
TESZT = Path(__file__).resolve().parent / "suggestions_api_test.mjs"


def main():
    print("[suggestions] cloudflare/api.js")
    node = shutil.which("node")
    if not node:
        warn("nincs node a gépen: a javaslat-teszt kimaradt")
        return end_("suggestions")
    if not WORKER.exists():
        warn(f"nincs meg: {WORKER}")
        return end_("suggestions")
    with tempfile.TemporaryDirectory() as d:
        (Path(d) / "api.mjs").write_text(WORKER.read_text(encoding="utf-8"), encoding="utf-8")      # a .js file with "export" needs a .mjs copy
        (Path(d) / "teszt.mjs").write_text(TESZT.read_text(encoding="utf-8"), encoding="utf-8")
        r = subprocess.run([node, str(Path(d) / "teszt.mjs")], capture_output=True, text=True, encoding="utf-8")
    for sor in r.stdout.splitlines():
        if sor.startswith("FAIL"):
            check(False, sor)
    check(r.returncode == 0 and "ALL OK" in r.stdout, "a Worker-teszt nem futott le rendben: " + (r.stderr.strip() or r.stdout.strip())[:300])
    print("  " + (r.stdout.strip().splitlines() or [""])[-1])
    return end_("suggestions")


if __name__ == "__main__":
    raise SystemExit(main())
