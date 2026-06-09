"""Canonical healthy and broken versions of demo-service's app/logic.py.

break_demo.py writes BROKEN_LOGIC to the target repo's main branch; reset_demo.py
writes HEALTHY_LOGIC back. Overwriting the whole file (rather than string-patching)
keeps break/reset robust across repeated demo takes.

Keep DEMO_FILE_PATH in sync with the real path in the demo-service repo.
"""

DEMO_FILE_PATH = "app/logic.py"

HEALTHY_LOGIC = '''"""Core business logic for demo-service."""


def compute(value: int) -> int:
    """Return double the input. Healthy, known-good implementation."""
    return value * 2


def describe() -> dict:
    return {
        "service": "demo-service",
        "capability": "compute(value) -> value * 2",
        "healthy": True,
    }
'''

BROKEN_LOGIC = '''"""Core business logic for demo-service."""


def compute(value: int) -> int:
    """Return double the input. STAGED BUG: raises ZeroDivisionError at runtime."""
    return value * 2 / 0  # bug: divide by zero crashes /compute and fails CI


def describe() -> dict:
    return {
        "service": "demo-service",
        "capability": "compute(value) -> value * 2",
        "healthy": True,
    }
'''
