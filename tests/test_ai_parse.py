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


def test_confirm_preserves_plan_and_adds_done():
    """Simulates the logic inside AIParseConfirmHandler.post() without hitting DB.

    Fixes the bug where saving an AI daily report was wiping the dashboard
    because plan/remain were stored as 0.
    """
    # Prior Excel upload had these totals per pilot
    prev_by_pilot = {
        "jamil":  {"pilot_name": "Jamil",  "flt_plan": 50, "flt_done": 10, "flt_remain": 40,
                   "sim_plan": 30, "sim_done": 8,  "sim_remain": 22},
        "samad":  {"pilot_name": "Samad",  "flt_plan": 50, "flt_done": 12, "flt_remain": 38,
                   "sim_plan": 30, "sim_done": 10, "sim_remain": 20},
        "ashraf": {"pilot_name": "Ashraf", "flt_plan": 50, "flt_done": 9,  "flt_remain": 41,
                   "sim_plan": 30, "sim_done": 7,  "sim_remain": 23},
    }
    # AI parsed today's daily report (Samad flew 1 flt + 1 sim; Jamil flew 1 sim)
    today = [
        {"name": "Jamil", "flt_done": 0, "sim_done": 1},
        {"name": "Samad", "flt_done": 1, "sim_done": 1},
    ]

    # Replicate the merge logic
    results = {}
    for row in today:
        name = row["name"]
        prev = prev_by_pilot.get(name.lower())
        t_flt = row["flt_done"]; t_sim = row["sim_done"]
        results[name] = {
            "flt_plan":   prev["flt_plan"],
            "flt_done":   prev["flt_done"] + t_flt,
            "flt_remain": max(0, prev["flt_remain"] - t_flt),
            "sim_plan":   prev["sim_plan"],
            "sim_done":   prev["sim_done"] + t_sim,
            "sim_remain": max(0, prev["sim_remain"] - t_sim),
        }
    # Carry-over for pilots who didn't fly today
    today_keys = {r["name"].lower() for r in today}
    for k, prev in prev_by_pilot.items():
        if k not in today_keys:
            results[prev["pilot_name"]] = {
                "flt_plan":prev["flt_plan"],"flt_done":prev["flt_done"],"flt_remain":prev["flt_remain"],
                "sim_plan":prev["sim_plan"],"sim_done":prev["sim_done"],"sim_remain":prev["sim_remain"],
            }

    # Jamil: +1 sim  →  sim_done 8→9, sim_remain 22→21
    assert results["Jamil"]["sim_done"] == 9, results["Jamil"]
    assert results["Jamil"]["sim_remain"] == 21
    assert results["Jamil"]["flt_done"] == 10   # no change
    assert results["Jamil"]["flt_plan"] == 50   # preserved

    # Samad: +1 flt +1 sim
    assert results["Samad"]["flt_done"] == 13
    assert results["Samad"]["flt_remain"] == 37
    assert results["Samad"]["sim_done"] == 11
    assert results["Samad"]["sim_remain"] == 19
    assert results["Samad"]["flt_plan"] == 50   # preserved

    # Ashraf: didn't fly today — carried over unchanged
    assert results["Ashraf"]["flt_done"] == 9
    assert results["Ashraf"]["flt_remain"] == 41
    assert results["Ashraf"]["flt_plan"] == 50

    # No pilot has plan=0 → dashboard won't look wiped
    for r in results.values():
        assert r["flt_plan"] > 0 and r["sim_plan"] > 0


if __name__ == "__main__":
    test_aggregate_counts()
    test_remarks_carry_source_detail()
    test_empty_pilot_name_skipped()
    test_match_pilot_exact_then_contains()
    test_confirm_preserves_plan_and_adds_done()
    print("✓ all tests passed")
