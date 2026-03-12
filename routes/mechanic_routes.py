"""Mechanic Routes: Mechanic Personal Records, OJT Items, OJT Records, Certifications"""
import os
import uuid
from database import get_db, dict_from_row, dicts_from_rows
from auth import require_auth, get_current_user
from routes.auth_routes import BaseHandler

UPLOAD_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "public", "uploads")

MECHANIC_FIELDS = [
    'name', 'short_name', 'rank', 'employee_id', 'specialty',
    'team', 'date_of_birth', 'certification_date', 'phone', 'email',
    'photo_url', 'notes', 'sort_order', 'status',
]

MECHANIC_OJT_ITEM_FIELDS = [
    'category', 'item_no', 'subject', 'description', 'sort_order',
]

MECHANIC_OJT_RECORD_FIELDS = [
    'mechanic_id', 'ojt_item_id', 'completed_date', 'evaluator', 'score', 'notes',
]

MECHANIC_CERT_FIELDS = [
    'cert_name', 'cert_type', 'issued_date', 'expiry_date', 'issuer', 'status', 'notes',
]


class MechanicsHandler(BaseHandler):
    """GET list, POST create"""

    @require_auth()
    def get(self):
        conn = get_db()
        status = self.get_argument("status", None)
        if status:
            mechanics = dicts_from_rows(conn.execute(
                "SELECT * FROM mechanics WHERE status=? ORDER BY sort_order, id", (status,)
            ).fetchall())
        else:
            mechanics = dicts_from_rows(conn.execute(
                "SELECT * FROM mechanics ORDER BY sort_order, id"
            ).fetchall())
        conn.close()
        self.success(mechanics)

    @require_auth(roles=['admin', 'ojt_admin'])
    def post(self):
        body = self.get_json_body()
        name = body.get('name', '').strip()
        short_name = body.get('short_name', '').strip()
        if not name or not short_name:
            return self.error("Name and short name are required")

        conn = get_db()
        cur = conn.execute(
            """INSERT INTO mechanics (name, short_name, rank, employee_id, specialty,
               team, date_of_birth, certification_date, phone, email, notes, sort_order)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
            (name, short_name, body.get('rank', 'Staff'),
             body.get('employee_id', ''), body.get('specialty', 'Airframe'),
             body.get('team', ''), body.get('date_of_birth', ''),
             body.get('certification_date', ''), body.get('phone', ''),
             body.get('email', ''), body.get('notes', ''),
             body.get('sort_order', 0))
        )
        conn.commit()
        mechanic = dict_from_row(conn.execute("SELECT * FROM mechanics WHERE id=?", (cur.lastrowid,)).fetchone())
        conn.close()
        self.success(mechanic, "Mechanic created")


class MechanicDetailHandler(BaseHandler):
    """GET one, PUT update, DELETE deactivate"""

    @require_auth()
    def get(self, mechanic_id):
        conn = get_db()
        mechanic = dict_from_row(conn.execute("SELECT * FROM mechanics WHERE id=?", (mechanic_id,)).fetchone())
        conn.close()
        if not mechanic:
            return self.error("Mechanic not found", 404)
        self.success(mechanic)

    @require_auth(roles=['admin', 'ojt_admin'])
    def put(self, mechanic_id):
        body = self.get_json_body()
        conn = get_db()
        existing = conn.execute("SELECT id FROM mechanics WHERE id=?", (mechanic_id,)).fetchone()
        if not existing:
            conn.close()
            return self.error("Mechanic not found", 404)

        fields, vals = [], []
        for k in MECHANIC_FIELDS:
            if k in body:
                fields.append(f"{k}=?")
                vals.append(body[k])
        if not fields:
            conn.close()
            return self.error("No fields to update")

        fields.append("updated_at=CURRENT_TIMESTAMP")
        vals.append(mechanic_id)
        conn.execute(f"UPDATE mechanics SET {','.join(fields)} WHERE id=?", vals)
        conn.commit()
        mechanic = dict_from_row(conn.execute("SELECT * FROM mechanics WHERE id=?", (mechanic_id,)).fetchone())
        conn.close()
        self.success(mechanic, "Mechanic updated")

    @require_auth(roles=['admin', 'ojt_admin'])
    def delete(self, mechanic_id):
        conn = get_db()
        existing = conn.execute("SELECT id, name FROM mechanics WHERE id=?", (mechanic_id,)).fetchone()
        if not existing:
            conn.close()
            return self.error("Mechanic not found", 404)
        conn.execute("UPDATE mechanics SET status='inactive', updated_at=CURRENT_TIMESTAMP WHERE id=?", (mechanic_id,))
        conn.commit()
        conn.close()
        self.success(message="Mechanic deactivated")


class MechanicPhotoHandler(BaseHandler):
    """POST upload mechanic photo"""

    @require_auth(roles=['admin', 'ojt_admin'])
    def post(self, mechanic_id):
        conn = get_db()
        mechanic = conn.execute("SELECT id FROM mechanics WHERE id=?", (mechanic_id,)).fetchone()
        if not mechanic:
            conn.close()
            return self.error("Mechanic not found", 404)

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
        fname = f"mechanic_{mechanic_id}_{uuid.uuid4().hex[:8]}{ext}"
        fpath = os.path.join(UPLOAD_DIR, fname)
        with open(fpath, "wb") as fp:
            fp.write(f["body"])

        photo_url = f"/uploads/{fname}"
        conn.execute("UPDATE mechanics SET photo_url=?, updated_at=CURRENT_TIMESTAMP WHERE id=?", (photo_url, mechanic_id))
        conn.commit()
        conn.close()
        self.success({"photo_url": photo_url}, "Photo uploaded")


class MechanicOJTItemsHandler(BaseHandler):
    """GET list, POST create"""

    @require_auth()
    def get(self):
        conn = get_db()
        items = dicts_from_rows(conn.execute(
            "SELECT * FROM mechanic_ojt_items ORDER BY category, sort_order, id"
        ).fetchall())
        conn.close()
        self.success(items)

    @require_auth(roles=['admin', 'ojt_admin'])
    def post(self):
        body = self.get_json_body()
        category = body.get('category', '').strip()
        item_no = body.get('item_no', '').strip()
        subject = body.get('subject', '').strip()
        if not category or not subject:
            return self.error("Category and subject are required")

        conn = get_db()
        cur = conn.execute(
            """INSERT INTO mechanic_ojt_items (category, item_no, subject, description, sort_order)
               VALUES (?,?,?,?,?)""",
            (category, item_no, subject, body.get('description', ''),
             body.get('sort_order', 0))
        )
        conn.commit()
        item = dict_from_row(conn.execute("SELECT * FROM mechanic_ojt_items WHERE id=?", (cur.lastrowid,)).fetchone())
        conn.close()
        self.success(item, "OJT item created")


class MechanicOJTRecordsHandler(BaseHandler):
    """GET all records, POST upsert"""

    @require_auth()
    def get(self):
        conn = get_db()
        records = dicts_from_rows(conn.execute("""
            SELECT mor.id, mor.mechanic_id, mor.ojt_item_id, mor.completed_date,
                   mor.evaluator, mor.score, mor.notes, mor.updated_at,
                   m.short_name as mechanic_name,
                   moi.category, moi.item_no, moi.subject
            FROM mechanic_ojt_records mor
            JOIN mechanics m ON mor.mechanic_id = m.id
            JOIN mechanic_ojt_items moi ON mor.ojt_item_id = moi.id
            ORDER BY m.sort_order, moi.sort_order
        """).fetchall())
        conn.close()
        self.success(records)

    @require_auth(roles=['admin', 'ojt_admin', 'instructor'])
    def post(self):
        body = self.get_json_body()
        mechanic_id = body.get('mechanic_id')
        ojt_item_id = body.get('ojt_item_id')
        completed_date = body.get('completed_date')
        evaluator = body.get('evaluator', '')
        score = body.get('score', 'N/A')
        notes = body.get('notes', '')

        if not mechanic_id or not ojt_item_id:
            return self.error("mechanic_id and ojt_item_id required")

        conn = get_db()
        existing = conn.execute(
            "SELECT id FROM mechanic_ojt_records WHERE mechanic_id=? AND ojt_item_id=?",
            (mechanic_id, ojt_item_id)
        ).fetchone()

        if existing:
            if completed_date:
                conn.execute(
                    """UPDATE mechanic_ojt_records SET completed_date=?, evaluator=?,
                       score=?, notes=?, updated_at=CURRENT_TIMESTAMP
                       WHERE mechanic_id=? AND ojt_item_id=?""",
                    (completed_date, evaluator, score, notes, mechanic_id, ojt_item_id)
                )
            else:
                conn.execute(
                    "DELETE FROM mechanic_ojt_records WHERE mechanic_id=? AND ojt_item_id=?",
                    (mechanic_id, ojt_item_id)
                )
        elif completed_date:
            conn.execute(
                """INSERT INTO mechanic_ojt_records
                   (mechanic_id, ojt_item_id, completed_date, evaluator, score, notes)
                   VALUES (?,?,?,?,?,?)""",
                (mechanic_id, ojt_item_id, completed_date, evaluator, score, notes)
            )
        conn.commit()
        conn.close()
        self.success(message="OJT record updated")


class MechanicCertificationsHandler(BaseHandler):
    """GET all, POST create"""

    @require_auth()
    def get(self):
        conn = get_db()
        certs = dicts_from_rows(conn.execute("""
            SELECT mc.id, mc.mechanic_id, mc.cert_name, mc.cert_type,
                   mc.issued_date, mc.expiry_date, mc.issuer, mc.status,
                   mc.notes, mc.created_at,
                   m.short_name as mechanic_name
            FROM mechanic_certifications mc
            JOIN mechanics m ON mc.mechanic_id = m.id
            ORDER BY m.sort_order, mc.created_at DESC
        """).fetchall())
        conn.close()
        self.success(certs)

    @require_auth(roles=['admin', 'ojt_admin'])
    def post(self):
        body = self.get_json_body()
        mechanic_id = body.get('mechanic_id')
        cert_name = body.get('cert_name', '').strip()
        if not mechanic_id or not cert_name:
            return self.error("mechanic_id and cert_name are required")

        conn = get_db()
        mechanic = conn.execute("SELECT id FROM mechanics WHERE id=?", (mechanic_id,)).fetchone()
        if not mechanic:
            conn.close()
            return self.error("Mechanic not found", 404)

        cur = conn.execute(
            """INSERT INTO mechanic_certifications
               (mechanic_id, cert_name, cert_type, issued_date, expiry_date, issuer, status, notes)
               VALUES (?,?,?,?,?,?,?,?)""",
            (mechanic_id, cert_name, body.get('cert_type', 'license'),
             body.get('issued_date', ''), body.get('expiry_date', ''),
             body.get('issuer', ''), body.get('status', 'active'),
             body.get('notes', ''))
        )
        conn.commit()
        cert = dict_from_row(conn.execute("SELECT * FROM mechanic_certifications WHERE id=?", (cur.lastrowid,)).fetchone())
        conn.close()
        self.success(cert, "Certification created")


class MechanicCertDetailHandler(BaseHandler):
    """PUT update, DELETE remove"""

    @require_auth(roles=['admin', 'ojt_admin'])
    def put(self, cert_id):
        body = self.get_json_body()
        conn = get_db()
        existing = conn.execute("SELECT id FROM mechanic_certifications WHERE id=?", (cert_id,)).fetchone()
        if not existing:
            conn.close()
            return self.error("Certification not found", 404)

        fields, vals = [], []
        for k in MECHANIC_CERT_FIELDS:
            if k in body:
                fields.append(f"{k}=?")
                vals.append(body[k])
        if not fields:
            conn.close()
            return self.error("No fields to update")

        vals.append(cert_id)
        conn.execute(f"UPDATE mechanic_certifications SET {','.join(fields)} WHERE id=?", vals)
        conn.commit()
        cert = dict_from_row(conn.execute("SELECT * FROM mechanic_certifications WHERE id=?", (cert_id,)).fetchone())
        conn.close()
        self.success(cert, "Certification updated")

    @require_auth(roles=['admin', 'ojt_admin'])
    def delete(self, cert_id):
        conn = get_db()
        existing = conn.execute("SELECT id FROM mechanic_certifications WHERE id=?", (cert_id,)).fetchone()
        if not existing:
            conn.close()
            return self.error("Certification not found", 404)
        conn.execute("DELETE FROM mechanic_certifications WHERE id=?", (cert_id,))
        conn.commit()
        conn.close()
        self.success(message="Certification deleted")


class MechanicSummaryHandler(BaseHandler):
    """GET computed summary: per mechanic OJT completion stats"""

    @require_auth()
    def get(self):
        conn = get_db()
        mechanics = dicts_from_rows(conn.execute(
            "SELECT id, name, short_name, specialty FROM mechanics WHERE status='active' ORDER BY sort_order, id"
        ).fetchall())

        result = []
        for m in mechanics:
            # Get total OJT items by category
            categories = dicts_from_rows(conn.execute("""
                SELECT DISTINCT category FROM mechanic_ojt_items
            """).fetchall())

            summary_by_category = {}
            for cat_row in categories:
                category = cat_row['category']
                total = conn.execute(
                    "SELECT COUNT(*) as cnt FROM mechanic_ojt_items WHERE category=?",
                    (category,)
                ).fetchone()['cnt']

                completed = conn.execute("""
                    SELECT COUNT(*) as cnt FROM mechanic_ojt_records mor
                    JOIN mechanic_ojt_items moi ON mor.ojt_item_id = moi.id
                    WHERE mor.mechanic_id=? AND moi.category=? AND mor.completed_date IS NOT NULL
                """, (m['id'], category)).fetchone()['cnt']

                summary_by_category[category] = {
                    'total': total,
                    'completed': completed,
                    'pending': total - completed,
                    'completion_rate': round(100 * completed / total, 1) if total > 0 else 0
                }

            # Overall stats
            total_all = conn.execute(
                "SELECT COUNT(*) as cnt FROM mechanic_ojt_items"
            ).fetchone()['cnt']

            completed_all = conn.execute("""
                SELECT COUNT(*) as cnt FROM mechanic_ojt_records
                WHERE mechanic_id=? AND completed_date IS NOT NULL
            """, (m['id'],)).fetchone()['cnt']

            result.append({
                'mechanic_id': m['id'],
                'name': m['name'],
                'short_name': m['short_name'],
                'specialty': m['specialty'],
                'summary_by_category': summary_by_category,
                'overall': {
                    'total': total_all,
                    'completed': completed_all,
                    'pending': total_all - completed_all,
                    'completion_rate': round(100 * completed_all / total_all, 1) if total_all > 0 else 0
                }
            })

        conn.close()
        self.success(result)
