"""short.py — a short, descriptive script: opens as a notebook (sign-off fixture)."""
import math


def area(r):
    """Area of a circle of radius r."""
    return math.pi * r * r


for r in (1, 2, 3):
    print(r, round(area(r), 3))
