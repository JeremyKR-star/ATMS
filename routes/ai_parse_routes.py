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

        # Try matching against active pilots so the UI can flag unmatched names
        conn = get_db()
        try:
            pilots = dicts_from_rows(
                conn.execute(
                    "SELECT id, name, short_name FROM pilots WHERE status='active'"
                ).fetchall()
            )
        finally:
            conn.close()

        for row in aggregated:
            pid = _match_pilot_id(row["name"], pilots)
            row["matched_pilot_id"] = pid
            row["matched"] = pid is not None

        # Echo the original filename + base64 back so the confirm step can store
        # the source image without re-uploading. Small files (<10MB) — fine to send.
        self.success({
            "report_date": report_date,
            "special_notes": special_notes,
            "per_sortie_rows": per_sortie_rows,
            "aggregated_rows": aggregated,
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
        orig_name = payload.get("source_filename") or "ai_parsed_image"
        ext = payload.get("source_ext") or os.path.splitext(orig_name)[1].lower() or ".png"
        source_b64 = payload.get("source_b64") or ""

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
            if IS_POSTGRES and file_binary:
                import psycopg2
                cur = conn.execute(
                    """INSERT INTO weekly_uploads
                       (filename, original_filename, uploaded_by, report_date,
                        file_size, row_count, notes, file_data)
                       VALUES (?,?,?,?,?,?,?,?)""",
                    (fname, orig_name, uploader, report_date,
                     len(file_binary), len(aggregated), notes,
                     psycopg2.Binary(file_binary)),
                )
            else:
                cur = conn.execute(
                    """INSERT INTO weekly_uploads
                       (filename, original_filename, uploaded_by, report_date,
                        file_size, row_count, notes, file_data)
                       VALUES (?,?,?,?,?,?,?,?)""",
                    (fname, orig_name, uploader, report_date,
                     len(file_binary), len(aggregated), notes,
                     file_binary if file_binary else None),
                )
            upload_id = cur.lastrowid

            pilots = dicts_from_rows(
                conn.execute(
                    "SELECT id, name, short_name FROM pilots WHERE status='active'"
                ).fetchall()
            )

            matched_count = 0
            unmatched_names = []
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

                conn.execute(
                    """INSERT INTO weekly_report_data
                       (upload_id, pilot_id, pilot_name, flt_plan, flt_done, flt_remain,
                        sim_plan, sim_done, sim_remain, remarks)
                       VALUES (?,?,?,?,?,?,?,?,?,?)""",
                    (upload_id, pilot_id, name,
                     int(row.get("flt_plan") or 0), int(row.get("flt_done") or 0),
                     int(row.get("flt_remain") or 0),
                     int(row.get("sim_plan") or 0), int(row.get("sim_done") or 0),
                     int(row.get("sim_remain") or 0),
                     (row.get("remarks") or "")),
                )

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
            }, f"AI-parsed report saved: {len(aggregated)} rows, {matched_count} matched")

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
        conn = get_db()
        try:
            # Find pilots with a stale URL (set, but no binary backing it)
            rows = dicts_from_rows(conn.execute(
                """SELECT id, name, short_name, photo_url
                   FROM pilots
                   WHERE photo_url IS NOT NULL AND photo_url <> ''
                     AND photo_data IS NULL"""
            ).fetchall())

            cleared = []
            for r in rows:
                conn.execute(
                    "UPDATE pilots SET photo_url=NULL, updated_at=CURRENT_TIMESTAMP WHERE id=?",
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
