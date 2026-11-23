"""Running all the checking tests. From the project folder:   py tests/run_all.py
Exit code: 0 = everything is fine, 1 = at least one test found an error."""
import importlib
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import test_common

TESZTEK = ["test_client", "test_datasheets", "test_data", "test_estimate", "test_estimate_threshold", "test_local_quota", "test_search", "test_parts", "test_server", "test_download_size", "test_explore", "test_sharing", "test_feedback"]


def main():
    eredmeny = {}
    for nev in TESZTEK:
        test_common.HIBAK.clear()
        test_common.FIGYELMEZTETESEK.clear()
        try:
            eredmeny[nev] = importlib.import_module(nev).main()
        except FileNotFoundError as e:
            print(f"  kihagyva ({e.filename}): nincs meg a fájl")
            eredmeny[nev] = None
        print()
    print("Összegzés:")
    for nev, r in eredmeny.items():
        print(f"  {nev}: {'kihagyva' if r is None else ('SIKERES' if r == 0 else 'SIKERTELEN')}")
    return 1 if any(r for r in eredmeny.values() if r) else 0


if __name__ == "__main__":
    raise SystemExit(main())
