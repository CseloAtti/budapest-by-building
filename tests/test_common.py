"""Shared helpers for the checking tests (it uses only Python's standard library)."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent       # the project folder
ERRORS = []
WARNINGS = []


def error_(message):
    ERRORS.append(message)
    print("  HIBA:", message)


def warn(message):
    WARNINGS.append(message)
    print("  figyelem:", message)


def check(condition, message):
    if not condition:
        error_(message)
    return bool(condition)


def end_(name_):
    print(f"[{name_}] {'SIKERES' if not ERRORS else 'SIKERTELEN: ' + str(len(ERRORS)) + ' hiba'}"
          f"{', ' + str(len(WARNINGS)) + ' figyelmeztetés' if WARNINGS else ''}")
    return 1 if ERRORS else 0
