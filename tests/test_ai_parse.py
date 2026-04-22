"""Offline tests for the AI parse aggregation logic.

Verifies that per-sortie rows (the shape Claude Opus returns) are correctly
aggregated into the per-pilot weekly_report_data shape used by the existing
dashboard.

Reference: 4/22 (수), FA-50M 조종사 결과보고 sample image.
Expected per-sortie rows:
  • Jamil   — SIM 1, INST-4S, 9:30~10:30,  instructor 양재혁 대위
  • Ikhwan  — SIM 1, FD-3S,  10:30~11:30, instructor 양재혁 대위
  • Faiz    — SIM 1, INST-4S, 11:30~12:30, instructor 양재혁 대위
  • Ashraf  — SIM 1, FD-1S,  12:30~13:30, instructor 조영욱 소령
  • Samad   — CPT 1, FD-3S,  13:30~14:30, instructor 이경한 대위
  • Samad   — 216 SQ, FD-3,  10:10~11:04, instructor 이기훈 대위 (flight)

Expected aggregation:
  Jamil  → sim_done=1, flt_done=0
  Ikhwan → sim_done=1, flt_done=0
  Faiz   → sim_done=1, flt_done=0
  Ashraf → sim_done=1, flt_done=0
  Samad  → sim_done=1, flt_done=1
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from routes.ai_parse_routes import _aggregate_rows, _match_pilot_id


SAMPLE_PER_SORTIE = [
    {"pilot_name": "Jamil",  "sortie_type": "sim",    "sortie_code": "INST-4S",
     "instructor": "양재혁 대위", "device_or_squadron": "SIM 1", "time_slot": "9:30~10:30"},
    {"pilot_name": "Ikhwan", "sortie_type": "sim",    "sortie_code": "FD-3S",
     "instructor": "양재혁 대위", "device_or_squadron": "SIM 1", "time_slot": "10:30~11:30"},
    {"pilot_name": "Faiz",   "sortie_type": "sim",    "sortie_code": "INST-4S",
     "instructor": "양재혁 대위", "device_or_squadron": "SIM 1", "time_slot": "11:30~12:30"},
    {"pilot_name": "Ashraf", "sortie_type": "sim",    "sortie_code": "FD-1S",
     "instructor": "조영욱 소령", "device_or_squadron": "SIM 1", "time_slot": "12:30~13:30"},
    {"pilot_name": "Samad",  "sortie_type": "sim",    "sortie_code": "FD-3S",
     "instructor": "이경한 대위", "device_or_squadron": "CPT 1", "time_slot": "13:30~14:30"},
    {"pilot_name": "Samad",  "sortie_type": "flight", "sortie_code": "FD-3",
     "instructor": "이기훈 대위", "device_or_squadron": "216 SQ", "time_slot": "10:10~11:04"},
]


def test_aggregate_counts():
    agg = {r["name"]: r for r in _aggregate_rows(SAMPLE_PER_SORTIE)}
    assert set(agg.keys()) == {"Jamil", "Ikhwan", "Faiz", "Ashraf", "Samad"}, \
        f"Pilots: {set(agg.keys())}"
    assert agg["Jamil"]["sim_done"] == 1 and agg["Jamil"]["flt_done"] == 0
    assert agg["Ikhwan"]["sim_done"] == 1 and agg["Ikhwan"]["flt_done"] == 0
    assert agg["Faiz"]["sim_done"] == 1 and agg["Faiz"]["flt_done"] == 0
    assert agg["Ashraf"]["sim_done"] == 1 and agg["Ashraf"]["flt_done"] == 0
    assert agg["Samad"]["sim_done"] == 1 and agg["Samad"]["flt_done"] == 1
    # Plan/remain are zero — they aren't in the daily image
    for r in agg.values():
        assert r["flt_plan"] == 0 and r["sim_plan"] == 0
        assert r["flt_remain"] == 0 and r["sim_remain"] == 0


def test_remarks_carry_source_detail():
    agg = {r["name"]: r for r in _aggregate_rows(SAMPLE_PER_SORTIE)}
    # Samad has two sorties so remarks should mention both
    assert "FD-3S" in agg["Samad"]["remarks"]
    assert "FD-3" in agg["Samad"]["remarks"]
    assert "이기훈" in agg["Samad"]["remarks"] or "이경한" in agg["Samad"]["remarks"]


def test_empty_pilot_name_skipped():
    rows = SAMPLE_PER_SORTIE + [{"pilot_name": "", "sortie_type": "sim",
                                  "sortie_code": "X", "instructor": "", "time_slot": ""}]
    agg = _aggregate_rows(rows)
    assert "" not in {r["name"] for r in agg}
    assert len(agg) == 5  # still just the 5 unique pilots


def test_match_pilot_exact_then_contains():
    pilots = [
        {"id": 10, "name": "Mohd Jamil bin Abdul", "short_name": "Jamil"},
        {"id": 11, "name": "Mohd Ikhwan bin Hassan", "short_name": "Ikhwan"},
        {"id": 12, "name": "Abdul Samad bin Ali", "short_name": "Samad"},
    ]
    assert _match_pilot_id("Jamil", pilots) == 10            # exact short_name
    assert _match_pilot_id("Ikhwan", pilots) == 11
    assert _match_pilot_id("Mohd Jamil bin Abdul", pilots) == 10  # exact full name
    assert _match_pilot_id("samad", pilots) == 12            # case-insensitive
    assert _match_pilot_id("Unknown", pilots) is None


if __name__ == "__main__":
    test_aggregate_counts()
    test_remarks_carry_source_detail()
    test_empty_pilot_name_skipped()
    test_match_pilot_exact_then_contains()
    print("✓ all tests passed")
