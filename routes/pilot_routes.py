"""Pilot Routes: RMAF Pilot Personal Records, Training Syllabus, Training Status, Weekly Report"""
import os
import time
import uuid
from database import get_db, dict_from_row, dicts_from_rows
from auth import require_auth, get_current_user
from routes.auth_routes import BaseHandler

UPLOAD_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "public", "uploads")

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
             body.get('nationality', 'Malaysian'), body.get('squadron', ''),
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
    """GET weekly summary per pilot (computed from training records)"""

    @require_auth()
    def get(self):
        conn = get_db()
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
