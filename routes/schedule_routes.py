"""Schedule Management Routes"""
from routes.auth_routes import BaseHandler
from database import get_db, dict_from_row, dicts_from_rows
from auth import require_auth


def check_schedule_conflicts(db, schedule_date, start_time, end_time, instructor_id=None, room=None, exclude_schedule_id=None):
    """
    Check if a schedule conflicts with existing schedules.
    Returns list of conflicting schedules if any are found.
    
    Conflict criteria:
    - Same date AND
    - Overlapping time AND
    - Same instructor OR same room
    """
    # Time overlap logic: two time ranges overlap if:
    # start_time1 < end_time2 AND start_time2 < end_time1
    
    query = """
        SELECT s.*, c.name as course_name, u.name as instructor_name
        FROM schedules s
        LEFT JOIN courses c ON s.course_id = c.id
        LEFT JOIN users u ON s.instructor_id = u.id
        WHERE s.schedule_date = ?
        AND s.start_time < ?
        AND s.end_time > ?
    """
    params = [schedule_date, end_time, start_time]
    
    # Filter by instructor or room
    if instructor_id or room:
        query += " AND ("
        conditions = []
        if instructor_id:
            conditions.append("s.instructor_id = ?")
            params.append(instructor_id)
        if room:
            conditions.append("s.room = ?")
            params.append(room)
        query += " OR ".join(conditions) + ")"
    
    # Exclude the current schedule if updating
    if exclude_schedule_id:
        query += " AND s.id != ?"
        params.append(exclude_schedule_id)
    
    conflicts = dicts_from_rows(db.execute(query, params).fetchall())
    return conflicts


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

        # Check for conflicts
        db = get_db()
        conflicts = check_schedule_conflicts(
            db,
            body["schedule_date"],
            body["start_time"],
            body["end_time"],
            instructor_id=body.get("instructor_id"),
            room=body.get("room")
        )
        
        if conflicts:
            db.close()
            return self.error(
                f"Schedule conflict detected. {len(conflicts)} existing schedule(s) overlap this time slot.",
                409,  # Conflict status code
            )

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

        # Check for conflicts if date/time/instructor/room changed
        db = get_db()
        should_check_conflicts = any(k in updates for k in ["schedule_date", "start_time", "end_time", "instructor_id", "room"])
        
        if should_check_conflicts:
            # Get current schedule to use existing values if not updating
            current = dict_from_row(db.execute("SELECT * FROM schedules WHERE id = ?", (schedule_id,)).fetchone())
            if not current:
                db.close()
                return self.error("Schedule not found", 404)
            
            check_date = updates.get("schedule_date", current["schedule_date"])
            check_start = updates.get("start_time", current["start_time"])
            check_end = updates.get("end_time", current["end_time"])
            check_instructor = updates.get("instructor_id", current["instructor_id"])
            check_room = updates.get("room", current["room"])
            
            conflicts = check_schedule_conflicts(
                db, check_date, check_start, check_end,
                instructor_id=check_instructor,
                room=check_room,
                exclude_schedule_id=schedule_id
            )
            
            if conflicts:
                db.close()
                return self.error(
                    f"Schedule conflict detected. {len(conflicts)} existing schedule(s) overlap this time slot.",
                    409
                )

        set_clause = ", ".join(f"{k} = ?" for k in updates)
        values = list(updates.values()) + [schedule_id]
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


class ScheduleConflictCheckHandler(BaseHandler):
    """Check for schedule conflicts before creating/updating"""
    
    @require_auth()
    def get(self):
        """
        Check for conflicts with query parameters:
        - schedule_date: the date to check (required)
        - start_time: start time (required)
        - end_time: end time (required)
        - instructor_id: instructor ID (optional)
        - room: room name (optional)
        """
        schedule_date = self.get_argument("schedule_date", None)
        start_time = self.get_argument("start_time", None)
        end_time = self.get_argument("end_time", None)
        instructor_id = self.get_argument("instructor_id", None)
        room = self.get_argument("room", None)
        
        if not schedule_date or not start_time or not end_time:
            return self.error("schedule_date, start_time, and end_time are required")
        
        db = get_db()
        conflicts = check_schedule_conflicts(
            db, schedule_date, start_time, end_time,
            instructor_id=instructor_id,
            room=room
        )
        db.close()
        
        self.success({
            "has_conflict": len(conflicts) > 0,
            "conflict_count": len(conflicts),
            "conflicts": conflicts
        })


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
                ON CONFLICT (schedule_id, trainee_id) DO UPDATE SET
                    status = EXCLUDED.status,
                    check_in_time = EXCLUDED.check_in_time,
                    notes = EXCLUDED.notes
            """, (schedule_id, rec["trainee_id"], rec.get("status", "present"),
                  rec.get("check_in_time", ""), rec.get("notes", "")))
        db.commit()
        db.close()
        self.success(None, "Attendance recorded")
