"""Schedule Management Routes"""
from routes.auth_routes import BaseHandler
from database import get_db, dict_from_row, dicts_from_rows
from auth import require_auth


class SchedulesHandler(BaseHandler):
    @require_auth()
    def get(self):
        start = self.get_argument("start_date", None) or self.get_argument("date_from", None)
        end = self.get_argument("end_date", None) or self.get_argument("date_to", None)
        instructor_id = self.get_argument("instructor_id", None)
        course_id = self.get_argument("course_id", None)

        db = get_db()
        query = """
            SELECT s.*, c.name as course_name, u.name as instructor_name
            FROM schedules s
            LEFT JOIN courses c ON s.course_id = c.id
            LEFT JOIN users u ON s.instructor_id = u.id
            WHERE 1=1
        """
        params = []
        if start:
            query += " AND s.schedule_date >= ?"
            params.append(start)
        if end:
            query += " AND s.schedule_date <= ?"
            params.append(end)
        if instructor_id:
            query += " AND s.instructor_id = ?"
            params.append(instructor_id)
        if course_id:
            query += " AND s.course_id = ?"
            params.append(course_id)

        query += " ORDER BY s.schedule_date, s.start_time"
        schedules = dicts_from_rows(db.execute(query, params).fetchall())
        db.close()
        self.success(schedules)

    @require_auth(roles=["admin", "ojt_admin"])
    def post(self):
        body = self.get_json_body()
        required = ["title", "schedule_date", "start_time", "end_time"]
        for f in required:
            if not body.get(f):
                return self.error(f"'{f}' is required")

        db = get_db()
        cur = db.execute("""
            INSERT INTO schedules (course_id, instructor_id, module_id, title, schedule_date, start_time, end_time, room, schedule_type, notes)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (body.get("course_id"), body.get("instructor_id"), body.get("module_id"),
              body["title"], body["schedule_date"], body["start_time"], body["end_time"],
              body.get("room", ""), body.get("schedule_type", "lecture"), body.get("notes", "")))
        db.commit()
        sid = cur.lastrowid
        db.close()
        self.success({"id": sid}, "Schedule created")


class ScheduleDetailHandler(BaseHandler):
    @require_auth(roles=["admin", "ojt_admin"])
    def put(self, schedule_id):
        body = self.get_json_body()
        allowed = ["course_id", "instructor_id", "module_id", "title", "schedule_date", "start_time", "end_time", "room", "schedule_type", "notes"]
        updates = {k: body[k] for k in allowed if k in body}
        if not updates:
            return self.error("No valid fields")

        set_clause = ", ".join(f"{k} = ?" for k in updates)
        values = list(updates.values()) + [schedule_id]
        db = get_db()
        db.execute(f"UPDATE schedules SET {set_clause} WHERE id = ?", values)
        db.commit()
        db.close()
        self.success(None, "Schedule updated")

    @require_auth(roles=["admin", "ojt_admin"])
    def delete(self, schedule_id):
        db = get_db()
        db.execute("DELETE FROM schedules WHERE id = ?", (schedule_id,))
        db.commit()
        db.close()
        self.success(None, "Schedule deleted")


class AttendanceHandler(BaseHandler):
    @require_auth(roles=["admin", "instructor", "ojt_admin"])
    def get(self, schedule_id):
        db = get_db()
        records = dicts_from_rows(db.execute("""
            SELECT a.*, u.name as trainee_name, u.employee_id
            FROM attendance a JOIN users u ON a.trainee_id = u.id
            WHERE a.schedule_id = ? ORDER BY u.name
        """, (schedule_id,)).fetchall())
        db.close()
        self.success(records)

    @require_auth(roles=["admin", "instructor", "ojt_admin"])
    def post(self, schedule_id):
        body = self.get_json_body()
        records = body.get("attendance", [])
        db = get_db()
        for rec in records:
            db.execute("""
                INSERT INTO attendance (schedule_id, trainee_id, status, check_in_time, notes)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(schedule_id, trainee_id) DO UPDATE SET status=?, check_in_time=?, notes=?
            """, (schedule_id, rec["trainee_id"], rec.get("status", "present"),
                  rec.get("check_in_time", ""), rec.get("notes", ""),
                  rec.get("status", "present"), rec.get("check_in_time", ""), rec.get("notes", "")))
        db.commit()
        db.close()
        self.success(None, "Attendance recorded")
