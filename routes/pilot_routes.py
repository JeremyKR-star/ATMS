"""Pilot Routes: Pilot Personal Records, Training Syllabus, Training Status, Weekly Report"""
import os
import io
import json
import time
import uuid
import datetime
from database import get_db, dict_from_row, dicts_from_rows
from auth import require_auth, get_current_user
from routes.auth_routes import BaseHandler

UPLOAD_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "public", "uploads")
WEEKLY_UPLOAD_DIR = os.path.join(UPLOAD_DIR, "weekly")

PILOT_FIELDS = [
    'name', 'short_name', 'rank', 'service_number', 'callsign', 'nationality',
    'squadron', 'date_of_birth', 'course_class', 'training_start_date',
    'training_end_date', 'phone', 'email', 'photo_url', 'notes', 'sort_order', 'status',
]


class PilotsHandler(BaseHandler):
    """GET list, POST create"""

    @require_auth()
    def get(self):
        conn = get_db()
        status = self.get_argument("status", None)
        if status:
            pilots = dicts_from_rows(conn.execute(
                "SELECT * FROM pilots WHERE status=? ORDER BY sort_order, id", (status,)
            ).fetchall())
        else:
            pilots = dicts_from_rows(conn.execute(
                "SELECT * FROM pilots ORDER BY sort_order, id"
            ).fetchall())
        conn.close()
        self.success(pilots)

    @require_auth(roles=['admin', 'ojt_admin'])
    def post(self):
        body = self.get_json_body()
        name = body.get('name', '').strip()
        short_name = body.get('short_name', '').strip()
        if not name or not short_name:
            return self.error("Name and short name are required")

        conn = get_db()
        cur = conn.execute(
            """INSERT INTO pilots (name, short_name, rank, service_number, callsign,
               nationality, squadron, date_of_birth, course_class,
               training_start_date, training_end_date, phone, email, notes, sort_order)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (name, short_name, body.get('rank', 'Major'),
             body.get('service_number', ''), body.get('callsign', ''),
             body.get('nationality', 'Malaysia'), body.get('squadron', ''),
             body.get('date_of_birth', ''), body.get('course_class', ''),
             body.get('training_start_date', ''), body.get('training_end_date', ''),
             body.get('phone', ''), body.get('email', ''),
             body.get('notes', ''), body.get('sort_order', 0))
        )
        conn.commit()
        pilot = dict_from_row(conn.execute("SELECT * FROM pilots WHERE id=?", (cur.lastrowid,)).fetchone())
        conn.close()
        self.success(pilot, "Pilot created")


class PilotDetailHandler(BaseHandler):
    """GET one, PUT update, DELETE deactivate"""

    @require_auth()
    def get(self, pilot_id):
        conn = get_db()
        pilot = dict_from_row(conn.execute("SELECT * FROM pilots WHERE id=?", (pilot_id,)).fetchone())
        conn.close()
        if not pilot:
            return self.error("Pilot not found", 404)
        self.success(pilot)

    @require_auth(roles=['admin', 'ojt_admin'])
    def put(self, pilot_id):
        body = self.get_json_body()
        conn = get_db()
        existing = conn.execute("SELECT id FROM pilots WHERE id=?", (pilot_id,)).fetchone()
        if not existing:
            conn.close()
            return self.error("Pilot not found", 404)

        fields, vals = [], []
        for k in PILOT_FIELDS:
            if k in body:
                fields.append(f"{k}=?")
                vals.append(body[k])
        if not fields:
            conn.close()
            return self.error("No fields to update")

        fields.append("updated_at=CURRENT_TIMESTAMP")
        vals.append(pilot_id)
        conn.execute(f"UPDATE pilots SET {','.join(fields)} WHERE id=?", vals)
        conn.commit()
        pilot = dict_from_row(conn.execute("SELECT * FROM pilots WHERE id=?", (pilot_id,)).fetchone())
        conn.close()
        self.success(pilot, "Pilot updated")

    @require_auth(roles=['admin', 'ojt_admin'])
    def delete(self, pilot_id):
        conn = get_db()
        existing = conn.execute("SELECT id, name FROM pilots WHERE id=?", (pilot_id,)).fetchone()
        if not existing:
            conn.close()
            return self.error("Pilot not found", 404)
        conn.execute("UPDATE pilots SET status='inactive', updated_at=CURRENT_TIMESTAMP WHERE id=?", (pilot_id,))
        conn.commit()
        conn.close()
        self.success(message="Pilot deactivated")


class PilotPhotoHandler(BaseHandler):
    """POST upload pilot photo"""

    @require_auth(roles=['admin', 'ojt_admin'])
    def post(self, pilot_id):
        conn = get_db()
        pilot = conn.execute("SELECT id FROM pilots WHERE id=?", (pilot_id,)).fetchone()
        if not pilot:
            conn.close()
            return self.error("Pilot not found", 404)

        files = self.request.files.get("photo", [])
        if not files:
            conn.close()
            return self.error("No photo file uploaded")

        f = files[0]
        ext = os.path.splitext(f["filename"])[1].lower()
        if ext not in ('.jpg', '.jpeg', '.png', '.gif', '.webp'):
            conn.close()
            return self.error("Unsupported file type")
        if len(f["body"]) > 5 * 1024 * 1024:
            conn.close()
            return self.error("File too large (max 5MB)")

        os.makedirs(UPLOAD_DIR, exist_ok=True)
        fname = f"pilot_{pilot_id}_{uuid.uuid4().hex[:8]}{ext}"
        fpath = os.path.join(UPLOAD_DIR, fname)
        with open(fpath, "wb") as fp:
            fp.write(f["body"])

        photo_url = f"/uploads/{fname}"
        conn.execute("UPDATE pilots SET photo_url=?, updated_at=CURRENT_TIMESTAMP WHERE id=?", (photo_url, pilot_id))
        conn.commit()
        conn.close()
        self.success({"photo_url": photo_url}, "Photo uploaded")


class PilotCoursesHandler(BaseHandler):
    """GET all training syllabus courses"""

    @require_auth()
    def get(self):
        conn = get_db()
        courses = dicts_from_rows(conn.execute(
            "SELECT * FROM pilot_courses ORDER BY sort_order, id"
        ).fetchall())
        conn.close()
        self.success(courses)


class PilotTrainingHandler(BaseHandler):
    """GET all training records, POST upsert a record"""

    @require_auth()
    def get(self):
        conn = get_db()
        records = dicts_from_rows(conn.execute("""
            SELECT pt.id, pt.pilot_id, pt.course_id, pt.completed_date,
                   pt.completed_time, pt.notes, pt.updated_at,
                   p.short_name as pilot_name,
                   pc.subject, pc.category, pc.course_no
            FROM pilot_training pt
            JOIN pilots p ON pt.pilot_id = p.id
            JOIN pilot_courses pc ON pt.course_id = pc.id
            ORDER BY p.sort_order, pc.sort_order
        """).fetchall())
        conn.close()
        self.success(records)

    @require_auth(roles=['admin', 'ojt_admin', 'instructor'])
    def post(self):
        body = self.get_json_body()
        pilot_id = body.get('pilot_id')
        course_id = body.get('course_id')
        completed_date = body.get('completed_date')
        completed_time = body.get('completed_time', '1:00')
        notes = body.get('notes', '')

        if not pilot_id or not course_id:
            return self.error("pilot_id and course_id required")

        conn = get_db()
        existing = conn.execute(
            "SELECT id FROM pilot_training WHERE pilot_id=? AND course_id=?",
            (pilot_id, course_id)
        ).fetchone()

        if existing:
            if completed_date:
                conn.execute(
                    """UPDATE pilot_training SET completed_date=?, completed_time=?,
                       notes=?, updated_at=CURRENT_TIMESTAMP
                       WHERE pilot_id=? AND course_id=?""",
                    (completed_date, completed_time, notes, pilot_id, course_id)
                )
            else:
                conn.execute(
                    "DELETE FROM pilot_training WHERE pilot_id=? AND course_id=?",
                    (pilot_id, course_id)
                )
        elif completed_date:
            conn.execute(
                """INSERT INTO pilot_training
                   (pilot_id, course_id, completed_date, completed_time, notes)
                   VALUES (?,?,?,?,?)""",
                (pilot_id, course_id, completed_date, completed_time, notes)
            )
        conn.commit()
        conn.close()
        self.success(message="Training record updated")


class PilotWeeklyHandler(BaseHandler):
    """GET weekly summary per pilot — uses latest upload if available, otherwise computed from training records"""

    @require_auth()
    def get(self):
        conn = get_db()

        # Check if there's uploaded weekly data
        latest_upload = conn.execute(
            "SELECT id FROM weekly_uploads ORDER BY created_at DESC LIMIT 1"
        ).fetchone()

        if latest_upload:
            # Use data from latest upload
            upload_data = dicts_from_rows(conn.execute(
                "SELECT * FROM weekly_report_data WHERE upload_id=? ORDER BY id",
                (latest_upload['id'],)
            ).fetchall())
            result = []
            for d in upload_data:
                result.append({
                    'id': d['pilot_id'] or 0,
                    'name': d['pilot_name'],
                    'simPlan': d['sim_plan'], 'simDone': d['sim_done'], 'simRemain': d['sim_remain'],
                    'fltPlan': d['flt_plan'], 'fltDone': d['flt_done'], 'fltRemain': d['flt_remain'],
                })
            conn.close()
            return self.success(result)

        # Fallback: compute from training records
        pilots = dicts_from_rows(conn.execute(
            "SELECT * FROM pilots WHERE status='active' ORDER BY sort_order, id"
        ).fetchall())

        sim_total = conn.execute("SELECT COUNT(*) as cnt FROM pilot_courses WHERE category='sim'").fetchone()['cnt']
        flt_total = conn.execute("SELECT COUNT(*) as cnt FROM pilot_courses WHERE category='flight'").fetchone()['cnt']

        result = []
        for p in pilots:
            sim_done = conn.execute("""
                SELECT COUNT(*) as cnt FROM pilot_training pt
                JOIN pilot_courses pc ON pt.course_id = pc.id
                WHERE pt.pilot_id=? AND pc.category='sim' AND pt.completed_date IS NOT NULL
            """, (p['id'],)).fetchone()['cnt']
            flt_done = conn.execute("""
                SELECT COUNT(*) as cnt FROM pilot_training pt
                JOIN pilot_courses pc ON pt.course_id = pc.id
                WHERE pt.pilot_id=? AND pc.category='flight' AND pt.completed_date IS NOT NULL
            """, (p['id'],)).fetchone()['cnt']
            result.append({
                'id': p['id'], 'name': p['short_name'],
                'simPlan': sim_total, 'simDone': sim_done, 'simRemain': sim_total - sim_done,
                'fltPlan': flt_total, 'fltDone': flt_done, 'fltRemain': flt_total - flt_done,
            })
        conn.close()
        self.success(result)


class PilotNationalitiesHandler(BaseHandler):
    """GET list of nationalities, POST add new nationality"""

    @require_auth()
    def get(self):
        conn = get_db()
        rows = dicts_from_rows(conn.execute(
            "SELECT * FROM pilot_nationalities ORDER BY sort_order, id"
        ).fetchall())
        conn.close()
        self.success(rows)

    @require_auth()
    def post(self):
        body = self.get_json_body()
        code = (body.get('code') or '').strip()
        label_ko = (body.get('label_ko') or '').strip()
        if not code or not label_ko:
            return self.error("code and label_ko are required")
        conn = get_db()
        existing = conn.execute("SELECT id FROM pilot_nationalities WHERE code=?", (code,)).fetchone()
        if existing:
            conn.close()
            return self.error("Nationality already exists")
        sort_order = body.get('sort_order', 0)
        cur = conn.execute(
            "INSERT INTO pilot_nationalities (code, label_ko, sort_order) VALUES (?,?,?)",
            (code, label_ko, sort_order)
        )
        conn.commit()
        row = dict_from_row(conn.execute("SELECT * FROM pilot_nationalities WHERE id=?", (cur.lastrowid,)).fetchone())
        conn.close()
        self.success(row, "Nationality added")


class WeeklyUploadHandler(BaseHandler):
    """GET list uploads, POST upload new Excel file"""

    @require_auth()
    def get(self):
        conn = get_db()
        uploads = dicts_from_rows(conn.execute(
            "SELECT * FROM weekly_uploads ORDER BY created_at DESC"
        ).fetchall())
        conn.close()
        self.success(uploads)

    @require_auth(roles=['admin', 'ojt_admin', 'instructor'])
    def post(self):
        files = self.request.files.get("file", [])
        if not files:
            return self.error("No file uploaded")

        f = files[0]
        orig_name = f["filename"]
        ext = os.path.splitext(orig_name)[1].lower()
        if ext not in ('.xlsx', '.xls', '.xlsm'):
            return self.error("Only .xlsx, .xls, .xlsm files are supported")
        if len(f["body"]) > 10 * 1024 * 1024:
            return self.error("File too large (max 10MB)")

        # Parse Excel
        try:
            import openpyxl
        except ImportError:
            return self.error("openpyxl not installed on server")

        try:
            wb = openpyxl.load_workbook(io.BytesIO(f["body"]), data_only=True)
            ws = wb.active

            # Find header row - look for 'Pilot' or 'Name' or similar
            header_row = None
            headers = {}
            for row_idx, row in enumerate(ws.iter_rows(min_row=1, max_row=10, values_only=False), 1):
                for cell in row:
                    val = str(cell.value or '').strip().lower()
                    if val in ('pilot', 'name', 'pilot name', '조종사', '이름'):
                        header_row = row_idx
                        break
                if header_row:
                    break

            if not header_row:
                # Try first row as header
                header_row = 1

            # Map column indices
            col_map = {}
            for cell in ws[header_row]:
                val = str(cell.value or '').strip().lower()
                col = cell.column
                if val in ('pilot', 'name', 'pilot name', '조종사', '이름'):
                    col_map['name'] = col
                elif val in ('flt plan', 'flight plan', 'flt_plan', 'flight_plan'):
                    col_map['flt_plan'] = col
                elif val in ('flt done', 'flight done', 'flt_done', 'flight_done'):
                    col_map['flt_done'] = col
                elif val in ('flt remain', 'flight remain', 'flt_remain', 'flight_remain'):
                    col_map['flt_remain'] = col
                elif val in ('sim plan', 'sim_plan', 'simulator plan'):
                    col_map['sim_plan'] = col
                elif val in ('sim done', 'sim_done', 'simulator done'):
                    col_map['sim_done'] = col
                elif val in ('sim remain', 'sim_remain', 'simulator remain'):
                    col_map['sim_remain'] = col
                elif val in ('plan',) and 'flt_plan' not in col_map:
                    col_map['flt_plan'] = col
                elif val in ('done',) and 'flt_done' not in col_map:
                    col_map['flt_done'] = col
                elif val in ('remain',) and 'flt_remain' not in col_map:
                    col_map['flt_remain'] = col
                elif val in ('remarks', 'note', 'notes', '비고'):
                    col_map['remarks'] = col

            if 'name' not in col_map:
                return self.error("Cannot find 'Pilot' or 'Name' column in Excel file")

            # Parse data rows
            parsed_rows = []
            for row in ws.iter_rows(min_row=header_row + 1, values_only=False):
                name_val = row[col_map['name'] - 1].value
                if not name_val or str(name_val).strip() == '':
                    continue
                name_str = str(name_val).strip()
                # Skip total/summary rows
                if name_str.lower() in ('total', 'sum', '합계', '소계'):
                    continue

                def safe_int(col_key):
                    if col_key not in col_map:
                        return 0
                    v = row[col_map[col_key] - 1].value
                    try:
                        return int(float(v)) if v is not None else 0
                    except (ValueError, TypeError):
                        return 0

                parsed_rows.append({
                    'name': name_str,
                    'flt_plan': safe_int('flt_plan'),
                    'flt_done': safe_int('flt_done'),
                    'flt_remain': safe_int('flt_remain'),
                    'sim_plan': safe_int('sim_plan'),
                    'sim_done': safe_int('sim_done'),
                    'sim_remain': safe_int('sim_remain'),
                    'remarks': str(row[col_map['remarks'] - 1].value or '') if 'remarks' in col_map else '',
                })
            wb.close()

        except Exception:
            return self.error("Failed to parse Excel file. Please check the file format.")

        if not parsed_rows:
            return self.error("No data rows found in Excel file")

        # Save file
        os.makedirs(WEEKLY_UPLOAD_DIR, exist_ok=True)
        fname = f"weekly_{uuid.uuid4().hex[:8]}{ext}"
        fpath = os.path.join(WEEKLY_UPLOAD_DIR, fname)
        with open(fpath, "wb") as fp:
            fp.write(f["body"])

        # Get uploader info
        user = get_current_user(self)
        uploader = user['name'] if user else 'Unknown'
        report_date = self.get_argument('report_date', datetime.date.today().isoformat())
        notes = self.get_argument('notes', '')

        # Save to DB
        conn = get_db()
        try:
            cur = conn.execute(
                """INSERT INTO weekly_uploads
                   (filename, original_filename, uploaded_by, report_date, file_size, row_count, notes)
                   VALUES (?,?,?,?,?,?,?)""",
                (fname, orig_name, uploader, report_date, len(f["body"]), len(parsed_rows), notes)
            )
            upload_id = cur.lastrowid

            # Match pilot names and save parsed data
            pilots = dicts_from_rows(conn.execute(
                "SELECT id, name, short_name FROM pilots WHERE status='active'"
            ).fetchall())

            for pr in parsed_rows:
                # Try to match pilot by short_name or name
                pilot_id = None
                for p in pilots:
                    if (p['short_name'] and p['short_name'].lower() == pr['name'].lower()) or \
                       (p['name'] and p['name'].lower() == pr['name'].lower()):
                        pilot_id = p['id']
                        break
                conn.execute(
                    """INSERT INTO weekly_report_data
                       (upload_id, pilot_id, pilot_name, flt_plan, flt_done, flt_remain,
                        sim_plan, sim_done, sim_remain, remarks)
                       VALUES (?,?,?,?,?,?,?,?,?,?)""",
                    (upload_id, pilot_id, pr['name'],
                     pr['flt_plan'], pr['flt_done'], pr['flt_remain'],
                     pr['sim_plan'], pr['sim_done'], pr['sim_remain'],
                     pr['remarks'])
                )

            conn.commit()
            upload = dict_from_row(conn.execute("SELECT * FROM weekly_uploads WHERE id=?", (upload_id,)).fetchone())
            matched = sum(1 for r in parsed_rows if any(
                (p['short_name'] and p['short_name'].lower() == r['name'].lower()) or
                (p['name'] and p['name'].lower() == r['name'].lower()) for p in pilots
            ))
            self.success({'upload': upload, 'parsed_rows': parsed_rows, 'matched': matched},
                         f"Uploaded successfully: {len(parsed_rows)} rows parsed")
        except Exception as e:
            conn.rollback()
            self.error("Failed to save upload data", 500)
        finally:
            conn.close()


class WeeklyUploadDetailHandler(BaseHandler):
    """GET one upload detail, DELETE remove upload"""

    @require_auth()
    def get(self, upload_id):
        conn = get_db()
        upload = dict_from_row(conn.execute("SELECT * FROM weekly_uploads WHERE id=?", (upload_id,)).fetchone())
        if not upload:
            conn.close()
            return self.error("Upload not found", 404)
        data = dicts_from_rows(conn.execute(
            "SELECT * FROM weekly_report_data WHERE upload_id=? ORDER BY id", (upload_id,)
        ).fetchall())
        conn.close()
        self.success({'upload': upload, 'data': data})

    @require_auth(roles=['admin', 'ojt_admin'])
    def delete(self, upload_id):
        conn = get_db()
        upload = dict_from_row(conn.execute("SELECT * FROM weekly_uploads WHERE id=?", (upload_id,)).fetchone())
        if not upload:
            conn.close()
            return self.error("Upload not found", 404)

        # Delete file
        fpath = os.path.join(WEEKLY_UPLOAD_DIR, upload['filename'])
        if os.path.exists(fpath):
            os.remove(fpath)

        # Delete DB records
        conn.execute("DELETE FROM weekly_report_data WHERE upload_id=?", (upload_id,))
        conn.execute("DELETE FROM weekly_uploads WHERE id=?", (upload_id,))
        conn.commit()
        conn.close()
        self.success(message="Upload deleted")


class WeeklyUploadDownloadHandler(BaseHandler):
    """GET download original Excel file (supports token in query param for window.open)"""

    def get(self, upload_id):
        # Support token in query param for file downloads via window.open
        from auth import decode_token
        token = self.get_argument('token', None)
        auth = self.request.headers.get("Authorization", "")
        user = None
        if auth.startswith("Bearer "):
            user = decode_token(auth[7:])
        elif token:
            user = decode_token(token)
        if not user:
            self.set_status(401)
            self.write({"error": "Authentication required"})
            return

        conn = get_db()
        upload = dict_from_row(conn.execute("SELECT * FROM weekly_uploads WHERE id=?", (upload_id,)).fetchone())
        conn.close()
        if not upload:
            return self.error("Upload not found", 404)

        fpath = os.path.join(WEEKLY_UPLOAD_DIR, upload['filename'])
        if not os.path.exists(fpath):
            return self.error("File not found on server", 404)

        self.set_header('Content-Type', 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
        self.set_header('Content-Disposition', f'attachment; filename="{upload["original_filename"]}"')
        with open(fpath, 'rb') as fp:
            self.write(fp.read())
        self.finish()


class WeeklyUploadLatestHandler(BaseHandler):
    """GET latest weekly report data (from most recent upload)"""

    @require_auth()
    def get(self):
        conn = get_db()
        latest = conn.execute(
            "SELECT id FROM weekly_uploads ORDER BY created_at DESC LIMIT 1"
        ).fetchone()
        if not latest:
            conn.close()
            return self.success([])

        data = dicts_from_rows(conn.execute(
            """SELECT wrd.*, wu.report_date, wu.original_filename
               FROM weekly_report_data wrd
               JOIN weekly_uploads wu ON wrd.upload_id = wu.id
               WHERE wrd.upload_id=? ORDER BY wrd.id""",
            (latest['id'],)
        ).fetchall())
        conn.close()
        self.success(data)
