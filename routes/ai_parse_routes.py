"""AI Parse Routes: Use Claude (Opus) vision to parse non-standard daily training reports
(images / PDFs) into the same shape the weekly Excel uploader produces, then save
into the existing weekly_uploads / weekly_report_data tables.

Endpoints:
  POST /api/pilots/ai-parse-image     — parse only, returns JSON for review
  POST /api/pilots/ai-parse-confirm   — save reviewed (and possibly edited) JSON
  POST /api/admin/cleanup-stale-photo-urls — admin: clear photo_url for pilots whose
                                              binary photo_data is missing (stops 404 spam
                                              from old file-based URLs that died with the
                                              ephemeral disk on Render free tier)
"""
import os
import io
import json
import uuid
import base64
import datetime
import traceback

from database import get_db, dict_from_row, dicts_from_rows
from auth import require_auth, get_current_user
from routes.auth_routes import BaseHandler

UPLOAD_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "public", "uploads")
WEEKLY_UPLOAD_DIR = os.path.join(UPLOAD_DIR, "weekly")

# Claude model — single source of truth, easy to swap later
CLAUDE_MODEL = os.getenv("CLAUDE_VISION_MODEL", "claude-opus-4-6")
MAX_FILE_SIZE = 10 * 1024 * 1024  # 10 MB

# Media types Claude vision supports
SUPPORTED_IMAGE_TYPES = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".webp": "image/webp",
}
SUPPORTED_PDF_TYPES = {".pdf": "application/pdf"}


# ──────────────────────────────────────────────────────────────────────
# Prompt — tells Claude exactly what shape we need back
# ──────────────────────────────────────────────────────────────────────
PARSE_PROMPT = """You are parsing a daily flight/simulator training schedule for the
Republic of Korea Air Force FA-50M conversion course. The image is a Korean
"조종사 결과보고" (pilot result report) showing one day's completed sorties.

Each row in the image represents ONE completed sortie for ONE pilot.
The two main blocks are:
  • SIMULATOR — columns are CPT 1, CPT 2, SIM 1, SIM 2 (training devices)
  • FLIGHT    — columns are squadron numbers (e.g., 189 SQ, 216 SQ)

For each occupied row, extract:
  - pilot_name      : the trainee pilot's name (e.g., "Jamil", "Samad", "Ashraf")
  - sortie_type     : "sim" if from the SIMULATOR block, "flight" if from the FLIGHT block
  - sortie_code     : the course code (e.g., "INST-4S", "FD-3S", "FD-1S", "FD-3")
  - instructor      : the instructor's name (e.g., "양재혁 대위", "조영욱 소령", "이기훈 대위")
  - device_or_squadron : the column header (e.g., "SIM 1", "CPT 1", "216 SQ")
  - time_slot       : the time range (e.g., "9:30~10:30", "10:10~11:04")

Also extract:
  - report_date     : the date shown in the title (return ISO yyyy-mm-dd; the year
                      is the current year unless the title says otherwise)
  - special_notes   : the contents of the 특이사항 (special notes) section, joined
                      with newlines. Empty string if none.

Return ONLY valid JSON in exactly this shape, no prose, no markdown fences:

{
  "report_date": "YYYY-MM-DD",
  "rows": [
    {
      "pilot_name": "...",
      "sortie_type": "sim" | "flight",
      "sortie_code": "...",
      "instructor": "...",
      "device_or_squadron": "...",
      "time_slot": "..."
    }
  ],
  "special_notes": "..."
}

If you cannot read a field for a given row, use an empty string for that field
but still include the row. Do not invent rows for empty/grey cells."""


def _aggregate_rows(parsed_rows):
    """Convert per-sortie rows -> per-pilot weekly_report_data shape.
    Counts sim sorties and flight sorties per pilot.
    """
    by_pilot = {}
    for r in parsed_rows:
        name = (r.get("pilot_name") or "").strip()
        if not name:
            continue
        if name not in by_pilot:
            by_pilot[name] = {
                "name": name,
                "flt_plan": 0, "flt_done": 0, "flt_remain": 0,
                "sim_plan": 0, "sim_done": 0, "sim_remain": 0,
                "remarks": "",
            }
        agg = by_pilot[name]
        stype = (r.get("sortie_type") or "").lower()
        code = r.get("sortie_code") or ""
        slot = r.get("time_slot") or ""
        instr = r.get("instructor") or ""
        if stype == "sim":
            agg["sim_done"] += 1
        elif stype == "flight":
            agg["flt_done"] += 1
        # Append a compact remark fragment so reviewers see the source detail
        frag = f"{code} ({slot} / {instr})".strip()
        agg["remarks"] = (agg["remarks"] + "; " + frag).strip("; ") if agg["remarks"] else frag
    return list(by_pilot.values())


def _duration_from_slot(time_slot):
    """Convert '9:30~10:30' or '10:10~11:04' into 'H:MM' duration string.
    Returns '1:00' as a sensible default if parsing fails."""
    if not time_slot:
        return "1:00"
    s = str(time_slot).strip()
    # Normalize various tilde / dash separators
    for sep in ("~", "-", "–", "—"):
        if sep in s:
            parts = s.split(sep, 1)
            break
    else:
        return "1:00"
    if len(parts) != 2:
        return "1:00"
    def _hm(t):
        t = t.strip()
        if ":" not in t:
            return None
        try:
            h, m = t.split(":", 1)
            return int(h) * 60 + int(m)
        except (ValueError, TypeError):
            return None
    a = _hm(parts[0]); b = _hm(parts[1])
    if a is None or b is None:
        return "1:00"
    diff = b - a
    if diff <= 0:
        return "1:00"
    return f"{diff // 60}:{diff % 60:02d}"


def _match_pilot_id(name, pilots):
    """Same matching strategy the Excel handler uses."""
    if not name:
        return None
    pr_lower = name.lower().strip()
    # Pass 1: exact
    for p in pilots:
        sn = (p.get("short_name") or "").lower().strip()
        fn = (p.get("name") or "").lower().strip()
        if (sn and sn == pr_lower) or (fn and fn == pr_lower):
            return p["id"]
    # Pass 2: contains
    for p in pilots:
        sn = (p.get("short_name") or "").lower().strip()
        fn = (p.get("name") or "").lower().strip()
        if (sn and (sn in pr_lower or pr_lower in sn)) or \
           (fn and (fn in pr_lower or pr_lower in fn)):
            return p["id"]
    return None


# ──────────────────────────────────────────────────────────────────────
# Endpoint 1: parse only
# ──────────────────────────────────────────────────────────────────────
class AIParseImageHandler(BaseHandler):
    """POST: upload an image/PDF, get parsed JSON back. Does NOT save to DB."""

    @require_auth(roles=["admin", "ojt_admin", "instructor"])
    def post(self):
        api_key = os.getenv("ANTHROPIC_API_KEY")
        if not api_key:
            return self.error(
                "ANTHROPIC_API_KEY is not set on the server. "
                "Add it to your .env file and restart.",
                500,
            )

        files = self.request.files.get("file", [])
        if not files:
            return self.error("No file uploaded")

        f = files[0]
        orig_name = f["filename"]
        ext = os.path.splitext(orig_name)[1].lower()
        body = f["body"]

        if len(body) > MAX_FILE_SIZE:
            return self.error("File too large (max 10MB)")

        if ext in SUPPORTED_IMAGE_TYPES:
            media_type = SUPPORTED_IMAGE_TYPES[ext]
            source_type = "base64"
            content_type = "image"
        elif ext in SUPPORTED_PDF_TYPES:
            media_type = SUPPORTED_PDF_TYPES[ext]
            source_type = "base64"
            content_type = "document"
        else:
            return self.error(
                "Unsupported file type. Use png, jpg, jpeg, gif, webp, or pdf."
            )

        try:
            from anthropic import Anthropic
        except ImportError:
            return self.error(
                "anthropic SDK not installed. Run: pip install 'anthropic>=0.40'",
                500,
            )

        b64_data = base64.standard_b64encode(body).decode("utf-8")

        try:
            client = Anthropic(api_key=api_key)
            message = client.messages.create(
                model=CLAUDE_MODEL,
                max_tokens=4096,
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": content_type,
                                "source": {
                                    "type": source_type,
                                    "media_type": media_type,
                                    "data": b64_data,
                                },
                            },
                            {"type": "text", "text": PARSE_PROMPT},
                        ],
                    }
                ],
            )
        except Exception as ex:
            traceback.print_exc()
            return self.error(f"Claude API call failed: {ex}", 500)

        # Concatenate text blocks from the model's response
        raw_text = ""
        for block in message.content:
            if getattr(block, "type", None) == "text":
                raw_text += block.text

        # Strip any accidental code fences and parse JSON
        cleaned = raw_text.strip()
        if cleaned.startswith("```"):
            # Remove first fence (and optional language tag) and trailing fence
            cleaned = cleaned.split("\n", 1)[1] if "\n" in cleaned else cleaned
            if cleaned.endswith("```"):
                cleaned = cleaned.rsplit("```", 1)[0]
        cleaned = cleaned.strip()

        try:
            parsed = json.loads(cleaned)
        except Exception as ex:
            return self.error(
                f"Claude returned non-JSON output: {ex}. Raw: {raw_text[:500]}", 500
            )

        per_sortie_rows = parsed.get("rows", [])
        report_date = parsed.get("report_date") or datetime.date.today().isoformat()
        special_notes = parsed.get("special_notes", "") or ""

        # Aggregate to per-pilot totals (the shape the existing dashboard expects)
        aggregated = _aggregate_rows(per_sortie_rows)

        # Try matching against active pilots so the UI can flag unmatched names,
        # and detect any sortie codes that aren't in pilot_courses yet (so the UI
        # can prompt the admin to approve/add them before saving).
        conn = get_db()
        try:
            pilots = dicts_from_rows(
                conn.execute(
                    "SELECT id, name, short_name FROM pilots WHERE status='active'"
                ).fetchall()
            )
            existing_courses = dicts_from_rows(conn.execute(
                "SELECT id, course_no, subject, category FROM pilot_courses"
            ).fetchall())
        finally:
            conn.close()

        for row in aggregated:
            pid = _match_pilot_id(row["name"], pilots)
            row["matched_pilot_id"] = pid
            row["matched"] = pid is not None

        # ── Detect unknown subjects (sortie codes Claude found that don't exist in DB) ──
        # Build a normalized set of known subjects for fast lookup. We compare on subject
        # (e.g. "FD-3S") because the AI returns sortie_code, which is the operational
        # name pilots use, and matches the 'subject' column in pilot_courses.
        known_subjects = set()
        for c in existing_courses:
            for field in ("subject", "course_no"):
                v = (c.get(field) or "").strip().upper()
                if v:
                    known_subjects.add(v)

        # Collect unknown subjects (with type guess from the per-sortie rows)
        unknown_by_code = {}
        for r in per_sortie_rows:
            code = (r.get("sortie_code") or "").strip()
            if not code:
                continue
            key = code.upper()
            if key in known_subjects:
                continue
            # AI's classification (sim/flight) for this row
            stype = (r.get("sortie_type") or "").lower()
            category = "sim" if stype == "sim" else ("flight" if stype == "flight" else "")
            if key not in unknown_by_code:
                unknown_by_code[key] = {
                    "subject": code,
                    "category": category,
                    "sample_rows": [],
                }
            entry = unknown_by_code[key]
            # Keep up to 3 sample rows so admin sees the context
            if len(entry["sample_rows"]) < 3:
                entry["sample_rows"].append({
                    "pilot_name": r.get("pilot_name") or "",
                    "instructor": r.get("instructor") or "",
                    "device_or_squadron": r.get("device_or_squadron") or "",
                    "time_slot": r.get("time_slot") or "",
                })
        unknown_subjects = list(unknown_by_code.values())

        # Echo the original filename + base64 back so the confirm step can store
        # the source image without re-uploading. Small files (<10MB) — fine to send.
        self.success({
            "report_date": report_date,
            "special_notes": special_notes,
            "per_sortie_rows": per_sortie_rows,
            "aggregated_rows": aggregated,
            "unknown_subjects": unknown_subjects,
            "model_used": CLAUDE_MODEL,
            "source_filename": orig_name,
            "source_b64": b64_data,
            "source_ext": ext,
            "source_size": len(body),
        }, "Parsed by Claude vision")


# ──────────────────────────────────────────────────────────────────────
# Endpoint 2: confirm and save
# ──────────────────────────────────────────────────────────────────────
class AIParseConfirmHandler(BaseHandler):
    """POST JSON: { report_date, special_notes, aggregated_rows, source_filename,
                    source_b64, source_ext } -> saves to weekly_uploads / weekly_report_data."""

    @require_auth(roles=["admin", "ojt_admin", "instructor"])
    def post(self):
        try:
            payload = json.loads(self.request.body)
        except Exception:
            return self.error("Invalid JSON body")

        aggregated = payload.get("aggregated_rows") or []
        if not aggregated:
            return self.error("No rows to save")

        report_date = payload.get("report_date") or datetime.date.today().isoformat()
        special_notes = (payload.get("special_notes") or "").strip()
        # Approved new courses to insert into pilot_courses before save.
        # Each item: {subject: 'FD-3S', category: 'sim'|'flight', course_no?, contents?}
        approved_new_courses = payload.get("new_courses") or []
        # Per-sortie rows from the AI parse — used to UPSERT pilot_training records
        # so the 개인별 현황 tab shows the daily completion dates/times.
        per_sortie_rows = payload.get("per_sortie_rows") or []
        raw_orig_name = payload.get("source_filename") or "ai_parsed_image"
        ext = payload.get("source_ext") or os.path.splitext(raw_orig_name)[1].lower() or ".png"
        source_b64 = payload.get("source_b64") or ""

        # ── Auto-rename: use the AI-detected report date as the canonical filename
        # so the upload history shows meaningful names like
        # "2026-04-22 일일보고 (AI).png" instead of "screenshot_2026.png".
        # Honour an explicit override from the client (lets the UI offer custom names later).
        client_override = (payload.get("custom_filename") or "").strip()
        if client_override:
            orig_name = client_override
            if not os.path.splitext(orig_name)[1]:
                orig_name = orig_name + ext
        else:
            orig_name = f"{report_date} 일일보고 (AI){ext}"

        # Decode the original image bytes (so it appears in upload history & download)
        try:
            file_binary = base64.standard_b64decode(source_b64) if source_b64 else b""
        except Exception:
            file_binary = b""

        # Persist the original image alongside the Excel uploads
        os.makedirs(WEEKLY_UPLOAD_DIR, exist_ok=True)
        fname = f"weekly_ai_{uuid.uuid4().hex[:8]}{ext}"
        fpath = os.path.join(WEEKLY_UPLOAD_DIR, fname)
        if file_binary:
            with open(fpath, "wb") as fp:
                fp.write(file_binary)

        user = get_current_user(self)
        uploader = user["name"] if user else "Unknown"
        # Tag the upload so it's distinguishable from Excel uploads in history
        notes = ("[AI-parsed] " + special_notes).strip()

        conn = get_db()
        try:
            from database import IS_POSTGRES

            # ── Insert any admin-approved new courses first ──
            created_courses = []
            if approved_new_courses:
                # Find current max sort_order so new ones append at the end
                row = conn.execute(
                    "SELECT COALESCE(MAX(sort_order), 0) AS m FROM pilot_courses"
                ).fetchone()
                next_sort = (row["m"] if row else 0) + 1
                for nc in approved_new_courses:
                    subj = (nc.get("subject") or "").strip()
                    cat = (nc.get("category") or "").strip().lower()
                    if not subj or cat not in ("sim", "flight"):
                        continue
                    course_no = (nc.get("course_no") or "").strip()
                    if not course_no:
                        cnt_row = conn.execute(
                            "SELECT COUNT(*) AS cnt FROM pilot_courses"
                        ).fetchone()
                        course_no = f"C-{(cnt_row['cnt'] if cnt_row else 0) + 1:02d}"
                    seq_row = conn.execute(
                        "SELECT COALESCE(MAX(seq_no), 0) AS m FROM pilot_courses WHERE category=?",
                        (cat,),
                    ).fetchone()
                    seq_no = (seq_row["m"] if seq_row else 0) + 1
                    cur_c = conn.execute(
                        """INSERT INTO pilot_courses
                           (course_no, category, seq_no, subject, contents, duration, sort_order)
                           VALUES (?,?,?,?,?,?,?)""",
                        (course_no, cat, seq_no, subj, nc.get("contents") or "",
                         nc.get("duration") or "1:00", next_sort),
                    )
                    next_sort += 1
                    created_courses.append({
                        "id": cur_c.lastrowid, "course_no": course_no,
                        "subject": subj, "category": cat,
                    })
                conn.commit()

            # ── CRITICAL: carry forward plan/remain from the most recent prior
            # upload, otherwise the dashboard (which reads the latest weekly_uploads
            # only) will appear wiped. Daily AI reports only know today's done counts;
            # the syllabus plan and the running remaining count come from the most
            # recent Excel weekly upload (or a previous AI upload).
            prev_upload_row = conn.execute(
                "SELECT id FROM weekly_uploads ORDER BY created_at DESC LIMIT 1"
            ).fetchone()
            prev_by_pilot = {}
            if prev_upload_row:
                prev_id = prev_upload_row["id"] if isinstance(prev_upload_row, dict) else prev_upload_row[0]
                prev_rows = dicts_from_rows(conn.execute(
                    """SELECT pilot_name, flt_plan, flt_done, flt_remain,
                              sim_plan, sim_done, sim_remain
                       FROM weekly_report_data WHERE upload_id=?""",
                    (prev_id,),
                ).fetchall())
                for pr in prev_rows:
                    key = (pr.get("pilot_name") or "").lower().strip()
                    if key:
                        prev_by_pilot[key] = pr

            # Snapshot of the AI parse for later 미리보기 re-rendering.
            ai_parse_snapshot = json.dumps({
                "report_date": report_date,
                "special_notes": special_notes,
                "model_used": payload.get("model_used") or CLAUDE_MODEL,
                "per_sortie_rows": per_sortie_rows,
                "aggregated_rows": aggregated,
                "saved_at": datetime.datetime.utcnow().isoformat() + "Z",
            }, ensure_ascii=False)

            if IS_POSTGRES and file_binary:
                import psycopg2
                cur = conn.execute(
                    """INSERT INTO weekly_uploads
                       (filename, original_filename, uploaded_by, report_date,
                        file_size, row_count, notes, file_data, ai_parse_json)
                       VALUES (?,?,?,?,?,?,?,?,?)""",
                    (fname, orig_name, uploader, report_date,
                     len(file_binary), len(aggregated), notes,
                     psycopg2.Binary(file_binary), ai_parse_snapshot),
                )
            else:
                cur = conn.execute(
                    """INSERT INTO weekly_uploads
                       (filename, original_filename, uploaded_by, report_date,
                        file_size, row_count, notes, file_data, ai_parse_json)
                       VALUES (?,?,?,?,?,?,?,?,?)""",
                    (fname, orig_name, uploader, report_date,
                     len(file_binary), len(aggregated), notes,
                     file_binary if file_binary else None, ai_parse_snapshot),
                )
            upload_id = cur.lastrowid

            pilots = dicts_from_rows(
                conn.execute(
                    "SELECT id, name, short_name FROM pilots WHERE status='active'"
                ).fetchall()
            )

            matched_count = 0
            unmatched_names = []
            # Track which prev_keys have been consumed by today's AI rows so we
            # don't double-insert the same pilot under different names during carry-over.
            consumed_prev_keys = set()

            for row in aggregated:
                name = (row.get("name") or "").strip()
                if not name:
                    continue
                # Honour the user's edit: if they (re)assigned matched_pilot_id, use it
                pilot_id = row.get("matched_pilot_id")
                if pilot_id is None:
                    pilot_id = _match_pilot_id(name, pilots)
                if pilot_id:
                    matched_count += 1
                else:
                    unmatched_names.append(name)

                # Today's daily count from the AI image (possibly user-edited)
                today_flt = int(row.get("flt_done") or 0)
                today_sim = int(row.get("sim_done") or 0)

                # Look up previous totals for this pilot (try exact name, then
                # fall back to fuzzy match on prev rows since names may vary
                # — Excel uses full names like "Mohd Jamil bin Awang", AI uses short "Jamil")
                nl = name.lower().strip()
                prev = prev_by_pilot.get(nl)
                matched_prev_key = nl if prev else None
                if prev is None:
                    for k, v in prev_by_pilot.items():
                        if k and (k in nl or nl in k):
                            prev = v
                            matched_prev_key = k
                            break

                # CRITICAL: use the prev row's canonical pilot_name when matched,
                # so we don't end up with both "Jamil" AND "Mohd Jamil bin Awang"
                # rows on the dashboard.
                canonical_name = name
                if prev and prev.get("pilot_name"):
                    canonical_name = prev["pilot_name"]
                    consumed_prev_keys.add(matched_prev_key)

                if prev:
                    final_flt_plan = int(prev.get("flt_plan") or 0)
                    final_sim_plan = int(prev.get("sim_plan") or 0)
                    final_flt_done = int(prev.get("flt_done") or 0) + today_flt
                    final_sim_done = int(prev.get("sim_done") or 0) + today_sim
                    final_flt_remain = max(0, int(prev.get("flt_remain") or 0) - today_flt)
                    final_sim_remain = max(0, int(prev.get("sim_remain") or 0) - today_sim)
                else:
                    # No prior data for this pilot — just record today's counts
                    final_flt_plan = int(row.get("flt_plan") or 0)
                    final_sim_plan = int(row.get("sim_plan") or 0)
                    final_flt_done = today_flt
                    final_sim_done = today_sim
                    final_flt_remain = int(row.get("flt_remain") or 0)
                    final_sim_remain = int(row.get("sim_remain") or 0)

                conn.execute(
                    """INSERT INTO weekly_report_data
                       (upload_id, pilot_id, pilot_name, flt_plan, flt_done, flt_remain,
                        sim_plan, sim_done, sim_remain, remarks)
                       VALUES (?,?,?,?,?,?,?,?,?,?)""",
                    (upload_id, pilot_id, canonical_name,
                     final_flt_plan, final_flt_done, final_flt_remain,
                     final_sim_plan, final_sim_done, final_sim_remain,
                     (row.get("remarks") or "")),
                )

            # ── Carry over pilots who didn't fly today, so the dashboard
            # (which reads the latest weekly_uploads only) still shows them.
            # Skip any prev_key that was already consumed by an AI row above
            # (so we don't insert the same pilot twice under different names).
            carried_over = 0
            for prev_key, prev in prev_by_pilot.items():
                if prev_key in consumed_prev_keys:
                    continue  # already inserted above as part of today's AI rows
                # No fly today — preserve previous totals as-is
                pname = prev.get("pilot_name") or prev_key
                pid = _match_pilot_id(pname, pilots)
                conn.execute(
                    """INSERT INTO weekly_report_data
                       (upload_id, pilot_id, pilot_name, flt_plan, flt_done, flt_remain,
                        sim_plan, sim_done, sim_remain, remarks)
                       VALUES (?,?,?,?,?,?,?,?,?,?)""",
                    (upload_id, pid, pname,
                     int(prev.get("flt_plan") or 0), int(prev.get("flt_done") or 0),
                     int(prev.get("flt_remain") or 0),
                     int(prev.get("sim_plan") or 0), int(prev.get("sim_done") or 0),
                     int(prev.get("sim_remain") or 0),
                     "(carried over — no flight today)"),
                )
                carried_over += 1

            conn.commit()

            # ── Write pilot_training records so 개인별 현황 tab shows the daily
            # completion dates/times. Each per-sortie row maps to one
            # (pilot_id, course_id) UPSERT with completed_date = report_date.
            training_inserted = 0
            training_updated = 0
            training_skipped = []
            if per_sortie_rows:
                # Build current course list (includes any new ones we just added)
                courses_now = dicts_from_rows(conn.execute(
                    "SELECT id, course_no, subject, category FROM pilot_courses"
                ).fetchall())
                # Index by upper-case subject and course_no
                course_by_key = {}
                for c in courses_now:
                    for field in ("subject", "course_no"):
                        v = (c.get(field) or "").strip().upper()
                        if v and v not in course_by_key:
                            course_by_key[v] = c

                for r in per_sortie_rows:
                    pname = (r.get("pilot_name") or "").strip()
                    code = (r.get("sortie_code") or "").strip()
                    if not pname or not code:
                        continue
                    pid = _match_pilot_id(pname, pilots)
                    course = course_by_key.get(code.upper())
                    if not pid or not course:
                        training_skipped.append({
                            "pilot_name": pname, "sortie_code": code,
                            "reason": ("no pilot match" if not pid else "no course match"),
                        })
                        continue
                    duration = _duration_from_slot(r.get("time_slot") or "")
                    # UPSERT — does this row already exist?
                    existing = conn.execute(
                        "SELECT id FROM pilot_training WHERE pilot_id=? AND course_id=?",
                        (pid, course["id"]),
                    ).fetchone()
                    if existing:
                        conn.execute(
                            """UPDATE pilot_training
                               SET completed_date=?, completed_time=?, updated_at=CURRENT_TIMESTAMP
                               WHERE pilot_id=? AND course_id=?""",
                            (report_date, duration, pid, course["id"]),
                        )
                        training_updated += 1
                    else:
                        conn.execute(
                            """INSERT INTO pilot_training
                               (pilot_id, course_id, completed_date, completed_time, notes)
                               VALUES (?,?,?,?,?)""",
                            (pid, course["id"], report_date, duration, ""),
                        )
                        training_inserted += 1
                conn.commit()

            upload = dict_from_row(conn.execute(
                """SELECT id, filename, original_filename, uploaded_by, report_date,
                          file_size, row_count, notes, created_at
                   FROM weekly_uploads WHERE id=?""", (upload_id,)
            ).fetchone())

            self.success({
                "upload": upload,
                "saved_rows": len(aggregated),
                "matched": matched_count,
                "unmatched_names": unmatched_names,
                "carried_over": carried_over,
                "created_courses": created_courses,
                "training_inserted": training_inserted,
                "training_updated": training_updated,
                "training_skipped": training_skipped,
            }, f"AI-parsed report saved: {len(aggregated)} rows updated, "
               f"{matched_count} matched, {carried_over} carried over, "
               f"{len(created_courses)} new course(s) added, "
               f"{training_inserted} training records inserted, "
               f"{training_updated} updated")

        except Exception as ex:
            conn.rollback()
            traceback.print_exc()
            self.error(f"Failed to save AI-parsed data: {ex}", 500)
        finally:
            conn.close()


# ──────────────────────────────────────────────────────────────────────
# Endpoint 3: cleanup stale photo_url values
# ──────────────────────────────────────────────────────────────────────
class CleanupStalePhotoUrlsHandler(BaseHandler):
    """POST: clear photo_url for any pilot whose photo_data is missing.

    Why this exists: Render's free tier has an ephemeral filesystem — every
    redeploy wipes /public/uploads. Old pilot photos that were saved as files
    (URL like /uploads/pilot_X_Y.png) still have those URLs in the DB but
    the files are gone, so the browser hits 404 forever. Newer photos go
    into pilots.photo_data BYTEA which survives. This endpoint detects
    pilots whose URL is dead (photo_data IS NULL) and nulls the URL so
    the UI falls back to showing initials. Re-upload to get the photo back.
    """

    @require_auth(roles=["admin", "ojt_admin"])
    def post(self):
        from database import IS_POSTGRES
        # Use the right length function for the backend
        len_fn = "octet_length" if IS_POSTGRES else "length"

        conn = get_db()
        try:
            # Stale = URL is set AND (no binary OR binary is too small to be a real image).
            # The "too small" check catches old uploads from before psycopg2.Binary() was
            # used — those wrote empty/garbled bytes that aren't NULL but aren't valid images.
            query = f"""SELECT id, name, short_name, photo_url
                        FROM pilots
                        WHERE photo_url IS NOT NULL AND photo_url <> ''
                          AND (photo_data IS NULL OR {len_fn}(photo_data) < 100)"""
            rows = dicts_from_rows(conn.execute(query).fetchall())

            cleared = []
            for r in rows:
                conn.execute(
                    "UPDATE pilots SET photo_url=NULL, photo_data=NULL, updated_at=CURRENT_TIMESTAMP WHERE id=?",
                    (r["id"],),
                )
                cleared.append({
                    "id": r["id"],
                    "name": r.get("name") or r.get("short_name"),
                    "old_url": r["photo_url"],
                })
            conn.commit()
            self.success(
                {"cleared_count": len(cleared), "cleared": cleared},
                f"Cleared {len(cleared)} stale photo URL(s)",
            )
        except Exception as ex:
            conn.rollback()
            traceback.print_exc()
            self.error(f"Cleanup failed: {ex}", 500)
        finally:
            conn.close()


# ──────────────────────────────────────────────────────────────────────
# Endpoint: AI parse preview — re-render an AI upload as it looked at parse time
# ──────────────────────────────────────────────────────────────────────
class AIParsePreviewHandler(BaseHandler):
    """GET: returns the saved AI parse snapshot + original image (base64) for an upload.
    The frontend uses this to re-render the side-by-side image+table preview later.
    """

    @require_auth()
    def get(self, upload_id):
        conn = get_db()
        try:
            # Metadata row (no binary)
            meta = dict_from_row(conn.execute(
                """SELECT id, filename, original_filename, uploaded_by, report_date,
                          file_size, row_count, notes, ai_parse_json, created_at
                   FROM weekly_uploads WHERE id=?""",
                (upload_id,),
            ).fetchone())
            if not meta:
                return self.error("Upload not found", 404)
            if not meta.get("ai_parse_json"):
                return self.error("This upload doesn't have an AI parse snapshot (likely an Excel upload)", 400)

            # Pull the binary image via fetchone_raw so DictRow doesn't strip it
            cur = conn.execute(
                "SELECT file_data FROM weekly_uploads WHERE id=?", (upload_id,)
            )
            raw = cur.fetchone_raw()
            file_data = None
            if raw:
                try:
                    file_data = raw["file_data"]
                except (KeyError, TypeError):
                    file_data = raw[0]
                if isinstance(file_data, memoryview):
                    file_data = bytes(file_data)

            try:
                parse_data = json.loads(meta["ai_parse_json"])
            except Exception:
                parse_data = {}

            # Guess extension from the original filename
            orig = meta.get("original_filename") or ""
            ext = os.path.splitext(orig)[1].lower() or ".png"
            mime_map = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
                        ".gif": "image/gif", ".webp": "image/webp", ".pdf": "application/pdf"}
            mime = mime_map.get(ext, "application/octet-stream")

            source_b64 = base64.standard_b64encode(file_data).decode("utf-8") if file_data else ""

            self.success({
                "upload": {k: meta[k] for k in meta.keys() if k != "ai_parse_json"},
                "parse": parse_data,
                "source_b64": source_b64,
                "source_ext": ext,
                "source_mime": mime,
                "source_size": len(file_data) if file_data else 0,
            }, "AI parse preview")
        except Exception as ex:
            traceback.print_exc()
            self.error(f"Failed to load preview: {ex}", 500)
        finally:
            conn.close()


# Need memoryview in scope for the handler above
import builtins as _b
memoryview = _b.memoryview


# ──────────────────────────────────────────────────────────────────────
# Endpoint 4: diagnose photo_data state (admin debug)
# ──────────────────────────────────────────────────────────────────────
class DiagnosePhotosHandler(BaseHandler):
    """GET: returns each pilot's photo_url, length, and first-byte hex.

    Lets us see exactly whether photo_data is NULL, garbled (text-encoded bytes),
    or proper PNG/JPEG. PNG starts with 89 50 4E 47, JPEG with FF D8 FF.
    """

    @require_auth(roles=["admin", "ojt_admin"])
    def get(self):
        from database import IS_POSTGRES
        len_fn = "octet_length" if IS_POSTGRES else "length"
        conn = get_db()
        try:
            rows = dicts_from_rows(conn.execute(
                f"""SELECT id, name, short_name, photo_url, photo_mime,
                           {len_fn}(photo_data) AS bytes_len
                    FROM pilots ORDER BY id"""
            ).fetchall())
            # For each row, also fetch the first 16 bytes as hex
            for r in rows:
                if r.get("bytes_len") and r["bytes_len"] > 0:
                    if IS_POSTGRES:
                        # ENCODE(SUBSTRING(...), 'hex') returns hex string
                        peek = conn.execute(
                            "SELECT ENCODE(SUBSTRING(photo_data FROM 1 FOR 16), 'hex') AS hex FROM pilots WHERE id=?",
                            (r["id"],),
                        ).fetchone()
                    else:
                        peek = conn.execute(
                            "SELECT HEX(SUBSTR(photo_data, 1, 16)) AS hex FROM pilots WHERE id=?",
                            (r["id"],),
                        ).fetchone()
                    r["first16_hex"] = (peek["hex"] if peek else None) if peek else None
                    # Identify image type from magic bytes
                    h = (r["first16_hex"] or "").lower()
                    if h.startswith("89504e47"):
                        r["image_type"] = "PNG ✓"
                    elif h.startswith("ffd8ff"):
                        r["image_type"] = "JPEG ✓"
                    elif h.startswith("47494638"):
                        r["image_type"] = "GIF ✓"
                    elif h.startswith("52494646"):
                        r["image_type"] = "WebP ✓"
                    elif h.startswith("5c"):  # backslash — text-encoded bytes!
                        r["image_type"] = "❌ text-encoded (\\x...) — Binary() not applied"
                    else:
                        r["image_type"] = f"❓ unknown magic {h[:8]}"
                else:
                    r["first16_hex"] = None
                    r["image_type"] = "(empty / NULL)"
            self.success({"pilots": rows, "backend": "postgres" if IS_POSTGRES else "sqlite"})
        except Exception as ex:
            traceback.print_exc()
            self.error(f"Diagnose failed: {ex}", 500)
        finally:
            conn.close()
