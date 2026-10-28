"""Framework-native tests for concordance_integrations: each file runs only where its framework is
installed (pytest.importorskip), against the in-process engine with a scratch data dir."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_INTEGRATIONS = Path(__file__).resolve().parent.parent
if str(_INTEGRATIONS) not in sys.path:
    sys.path.insert(0, str(_INTEGRATIONS))


@pytest.fixture(autouse=True)
def _scratch_data_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("CONCORDANCE_DATA_DIR", str(tmp_path))
    monkeypatch.delenv("CONCORDANCE_URL", raising=False)


RE = {"RE_VERIFY": {"loan_principal": 12_000_000, "annual_rate": 0.045, "loan_term_months": 240,
                    "claimed_monthly_payment": 75917.93}}
GOOD_STEPS = [{"id": "m", "domain": "real_estate", "spec": RE}]
BAD_STEPS = [{"id": "m", "domain": "real_estate",
              "spec": {"RE_VERIFY": dict(RE["RE_VERIFY"], claimed_monthly_payment=70000)}}]
UNCHECKABLE = "The sky was blue and the meeting went well."
