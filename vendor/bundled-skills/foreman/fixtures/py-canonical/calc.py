# calc.py — the Python canonical fixture's source under test.
#
# add() and multiply() are correct (Wave 1, known-good baseline).
# subtract() carries the deliberately planted bug (Wave 2).


def add(a, b):
    return a + b


def multiply(a, b):
    return a * b


def subtract(a, b):
    # BUG (planted, Phase 3d): should be `a - b`. Returning `a + b` makes the
    # subtract test fail. The one-line fix is to change `+` to `-`.
    return a + b
