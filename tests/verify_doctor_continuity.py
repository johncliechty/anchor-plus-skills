"""Run the bounded Doctor continuity gate (isolated, no live model).

Browser tests use real app assets/Doctor HTML and real WS/SSE transport with
synthetic session output. This is not a claim about live-service activation.
"""
from pathlib import Path
import pytest

if __name__ == '__main__':
    root = Path(__file__).resolve().parent
    raise SystemExit(pytest.main(['-q', '-x', str(root / 'test_doctor_continuity.py'),
                                 str(root / 'test_doctor_model_policy_2026_09_08.py'),
                                 str(root / 'test_doctor_resolve_all_2026_09_03.py'),
                                 str(root / 'test_doctor_probe_on_open_2026_09_03.py')]))
