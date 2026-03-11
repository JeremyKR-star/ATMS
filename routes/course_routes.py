"""Course & Module Management Routes"""
import json
from routes.auth_routes import BaseHandler
from database import get_db, dict_from_row, dicts_from_rows
from auth import require_auth


class CoursesHandler(BaseHandler):
    @require_auth()
    def get(self):
        status = self.get_argument("status", None)
        ctype = self.get_argument("type", None)
        search = self.get_argument("search", None)

        db = get_db()
        query = """
            SELECT c.*,
                GROUP_CONCAT(DISTINCT u.name) as instructor_names,
                COUNT(DISTINCT e.trainee_id) as enrolled_count
            FROM courses c
            LEFT JOIN course_instructors ci ON c.id = ci.course_id
            LEFT JOIN users u ON ci.instructor_id = u.id
            LEFT JOIN enrollments e ON c.id = e.course_id AND e.status IN ('enrolled','in_progress')
            WHERE 1=1
        """
        params = []
        if status:
            query += " AND c.status = ?"
            params.append(status)
        if ctype:
            query += " AND c.type = ?"
            params.append(ctype)
        if search:
            query += " AND (c.name LIKE ? OR c.code LIKE ?)"
            params.extend([f"%{search}%", f"%{search}%"])

        query += " GROUP BY c.id ORDER BY c.start_date DESC"
        courses = dicts_from_rows(db.execute(query, params).fetchall())
        db.close()
        self.success(courses)

    @require_auth(roles=["admin", "ojt_admin"])
    def post(self):
        body = self.get_json_body()
        required = ["code", "name", "type"]
        for f in required:
            if not body.get(f):
                return self.error(f"'{f}' is required")

        db = get_db()
        try:
            cur = db.execute("""
                INSERT INTO courses (code, name, type, description, duration_weeks, max_trainees, aircraft_type, status, start_date, end_date)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (body["code"], body["name"], body["type"], body.get("description", ""),
                  body.get("duration_weeks"), body.get("max_trainees", 20),
                  body.get("aircraft_type", ""), body.get("status", "planned"),
                  body.get("start_date", ""), body.get("end_date", "")))
            db.commit()
            course_id = cur.lastrowid

            # Assign instructors
            for iid in body.get("instructor_ids", []):
                db.execute("INSERT OR IGNORE INTO course_instructors (course_id, instructor_id) VALUES (?, ?)", (course_id, iid))
            db.commit()
            db.close()
            self.success({"id": course_id}, "Course created")
        except Exception as e:
            db.close()
            self.error(str(e), 500)


class CourseDetailHandler(BaseHandler):
    @require_auth()
    def get(self, course_id):
        db = get_db()
        course = dict_from_row(db.execute("SELECT * FROM courses WHERE id = ?", (course_id,)).fetchone())
        if not course:
            db.close()
            return self.error("Course not found", 404)

        course["modules"] = dicts_from_rows(db.execute(
            "SELECT * FROM course_modules WHERE course_id = ? ORDER BY order_num", (course_id,)).fetchall())
        course["instructors"] = dicts_from_rows(db.execute("""
            SELECT u.id, u.name, u.specialty, ci.role
            FROM course_instructors ci JOIN users u ON ci.instructor_id = u.id
            WHERE ci.course_id = ?
        """, (course_id,)).fetchall())
        course["enrollments"] = dicts_from_rows(db.execute("""
            SELECT e.*, u.name as trainee_name, u.employee_id
            FROM enrollments e JOIN users u ON e.trainee_id = u.id
            WHERE e.course_id = ? ORDER BY u.name
        """, (course_id,)).fetchall())
        db.close()
        self.success(course)

    @require_auth(roles=["admin", "ojt_admin"])
    def put(self, course_id):
        body = self.get_json_body()
        allowed = ["name", "description", "duration_weeks", "max_trainees", "aircraft_type", "status", "start_date", "end_date"]
        updates = {k: body[k] for k in allowed if k in body}
        if updates:
            set_clause = ", ".join(f"{k} = ?" for k in updates)
            values = list(updates.values()) + [course_id]
            db = get_db()
            db.execute(f"UPDATE courses SET {set_clause}, updated_at = CURRENT_TIMESTAMP WHERE id = ?", values)
            db.commit()
            db.close()
        self.success(updates, "Course updated")

    @require_auth(roles=["admin"])
    def delete(self, course_id):
        db = get_db()
        db.execute("UPDATE courses SET status = 'cancelled', updated_at = CURRENT_TIMESTAMP WHERE id = ?", (course_id,))
        db.commit()
        db.close()
        self.success(None, "Course cancelled")


class ModulesHandler(BaseHandler):
    @require_auth()
    def get(self, course_id):
        db = get_db()
        modules = dicts_from_rows(db.execute(
            "SELECT * FROM course_modules WHERE course_id = ? ORDER BY order_num", (course_id,)).fetchall())
        db.close()
        self.success(modules)

    @require_auth(roles=["admin", "instructor"])
    def post(self, course_id):
        body = self.get_json_body()
        if not body.get("name"):
            return self.error("Module name is required")

        db = get_db()
        max_order = db.execute("SELECT COALESCE(MAX(order_num),0) FROM course_modules WHERE course_id = ?", (course_id,)).fetchone()[0]
        cur = db.execute("""
            INSERT INTO course_modules (course_id, name, description, order_num, duration_hours, module_type)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (course_id, body["name"], body.get("description", ""), max_order + 1,
              body.get("duration_hours"), body.get("module_type", "theory")))
        db.commit()
        module_id = cur.lastrowid
        db.close()
        self.success({"id": module_id}, "Module added")


class EnrollmentHandler(BaseHandler):
    @require_auth(roles=["admin", "ojt_admin"])
    def post(self, course_id):
        body = self.get_json_body()
        trainee_ids = body.get("trainee_ids", [])
        if not trainee_ids:
            return self.error("At least one trainee ID is required")

        db = get_db()
        enrolled = []
        for tid in trainee_ids:
            try:
                db.execute("INSERT OR IGNORE INTO enrollments (course_id, trainee_id, status) VALUES (?, ?, 'enrolled')",
                           (course_id, tid))
                enrolled.append(tid)
            except Exception:
                pass
        db.commit()
        db.close()
        self.success({"enrolled": enrolled}, f"{len(enrolled)} trainee(s) enrolled")

    @require_auth(roles=["admin", "ojt_admin", "instructor"])
    def put(self, course_id):
        """Update enrollment status / progress / score."""
        body = self.get_json_body()
        trainee_id = body.get("trainee_id")
        if not trainee_id:
            return self.error("trainee_id is required")

        allowed = ["status", "progress", "final_score"]
        updates = {k: body[k] for k in allowed if k in body}
        if not updates:
            return self.error("No valid fields")

        if "status" in updates and updates["status"] == "completed":
            updates["completed_at"] = "CURRENT_TIMESTAMP"

        set_parts = []
        values = []
        for k, v in updates.items():
            if v == "CURRENT_TIMESTAMP":
                set_parts.append(f"{k} = CURRENT_TIMESTAMP")
            else:
                set_parts.append(f"{k} = ?")
                values.append(v)
        values.extend([course_id, trainee_id])

        db = get_db()
        db.execute(f"UPDATE enrollments SET {', '.join(set_parts)} WHERE course_id = ? AND trainee_id = ?", values)
        db.commit()
        db.close()
        self.success(None, "Enrollment updated")
