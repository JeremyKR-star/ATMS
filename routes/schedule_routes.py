"""Schedule Management Routes"""
from routes.auth_routes import BaseHandler
from database import get_db, dict_from_row, dicts_from_rows
from auth import require_auth

try:
    from websocket_handler import broadcast_to_all
except ImportError:
    broadcast_to_all = None


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
        page = int(self.get_argument("page", 1))
        per_page = int(self.get_argument("per_page", 50))
        offset = (page - 1) * per_page

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

        # Count total before pagination
        count_q = query.replace("SELECT s.*, c.name as course_name, u.name as instructor_name", "SELECT COUNT(*)")
        total = db.execute(count_q, params).fetchone()[0]

        query += " ORDER BY s.schedule_date, s.start_time LIMIT ? OFFSET ?"
        params.extend([per_page, offset])
        schedules = dicts_from_rows(db.execute(query, params).fetchall())
        db.close()
        self.success({"schedules": schedules, "pagination": {"page": page, "per_page": per_page, "total": total, "total_pages": (total + per_page - 1) // per_page}})

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
        # Broadcast schedule creation to all connected users
        if broadcast_to_all:
            try:
                broadcast_to_all({
                    "type": "schedule_update",
                    "action": "created",
                    "data": {"id": sid, "title": body["title"], "date": body["schedule_date"]}
                })
            except Exception:
                pass
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


class ScheduleEnrollmentsHandler(BaseHandler):
    """Get enrolled students for a specific schedule's course"""
    @require_auth()
    def get(self, schedule_id):
        db = get_db()
        # Get the course_id for this schedule
        schedule = db.execute("SELECT course_id FROM schedules WHERE id = ?", (schedule_id,)).fetchone()
        if not schedule:
            db.close()
            return self.error("Schedule not found", 404)
        course_id = schedule[0]
        if not course_id:
            db.close()
            return self.success([])
        # Get enrolled students for this course
        students = dicts_from_rows(db.execute("""
            SELECT u.id, u.name, u.employee_id, u.department, e.status as enrollment_status
            FROM enrollments e
            JOIN users u ON e.trainee_id = u.id
            WHERE e.course_id = ? AND e.status IN ('enrolled','in_progress','completed')
            ORDER BY u.name
        """, (course_id,)).fetchall())
        db.close()
        self.success(students)


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


class ScheduleOptimizeHandler(BaseHandler):
    """Generate optimized schedule suggestions for a course"""

    @require_auth(roles=["admin", "ojt_admin"])
    def post(self):
        body = self.get_json_body()
        course_id = body.get("course_id")
        date_from = body.get("date_from")
        date_to = body.get("date_to")
        preferred_times = body.get("preferred_times", ["09:00-12:00", "13:00-17:00"])
        preferred_rooms = body.get("preferred_rooms", [])

        if not course_id or not date_from or not date_to:
            return self.error("course_id, date_from, and date_to are required")

        db = get_db()

        # Get all instructors assigned to this course
        instructors = dicts_from_rows(db.execute("""
            SELECT DISTINCT ci.instructor_id, u.name, u.id
            FROM course_instructors ci
            JOIN users u ON ci.instructor_id = u.id
            WHERE ci.course_id = ?
            ORDER BY u.name
        """, (course_id,)).fetchall())

        if not instructors:
            db.close()
            return self.error("No instructors assigned to this course", 404)

        # Get all course modules that need scheduling
        modules = dicts_from_rows(db.execute("""
            SELECT * FROM course_modules
            WHERE course_id = ?
            ORDER BY module_order ASC
        """, (course_id,)).fetchall())

        if not modules:
            db.close()
            return self.error("No modules found for this course", 404)

        # Get existing schedules in the date range to identify busy slots
        existing_schedules = dicts_from_rows(db.execute("""
            SELECT * FROM schedules
            WHERE schedule_date >= ? AND schedule_date <= ?
            AND (instructor_id IS NOT NULL OR room IS NOT NULL)
            ORDER BY schedule_date, start_time
        """, (date_from, date_to)).fetchall())

        db.close()

        # Build a map of busy slots: {(instructor_id, date, start_time): True}
        busy_slots = {}
        for schedule in existing_schedules:
            instr_id = schedule.get("instructor_id")
            room = schedule.get("room")
            date = schedule.get("schedule_date")
            start = schedule.get("start_time")
            end = schedule.get("end_time")

            if instr_id:
                busy_slots[(instr_id, date, start, end)] = True
            if room:
                busy_slots[(room, date, start, end)] = True

        # Generate available time slots
        available_times = self._parse_time_ranges(preferred_times)

        # Generate optimization suggestions
        suggestions = []
        instructor_module_count = {}

        # Initialize module counts per instructor
        for instr in instructors:
            instructor_module_count[instr["instructor_id"]] = 0

        # Sort modules by order
        sorted_modules = sorted(modules, key=lambda m: m.get("module_order", 0))

        # Generate date range
        from datetime import datetime, timedelta
        current_date = datetime.strptime(date_from, "%Y-%m-%d")
        end_date = datetime.strptime(date_to, "%Y-%m-%d")

        # Try to distribute modules across the date range
        for module in sorted_modules:
            module_id = module.get("id")
            module_name = module.get("module_name", f"Module {module_id}")

            # Find instructor with least modules assigned
            best_instructor = min(instructors,
                                 key=lambda x: instructor_module_count[x["instructor_id"]])

            # Find the best available slot
            slot_found = False
            temp_date = current_date

            while temp_date <= end_date and not slot_found:
                date_str = temp_date.strftime("%Y-%m-%d")

                for time_slot in available_times:
                    start_time, end_time = time_slot

                    # Check if slot is available for instructor
                    slot_key = (best_instructor["instructor_id"], date_str, start_time, end_time)

                    # Check if this slot conflicts with any existing schedules
                    has_conflict = False
                    for busy_key in busy_slots:
                        if (busy_key[0] == best_instructor["instructor_id"] and
                            busy_key[1] == date_str):
                            busy_start, busy_end = busy_key[2], busy_key[3]
                            # Check for time overlap
                            if start_time < busy_end and end_time > busy_start:
                                has_conflict = True
                                break

                    # Check if preferred room is available
                    room = ""
                    if preferred_rooms:
                        room = preferred_rooms[len(suggestions) % len(preferred_rooms)]
                        for busy_key in busy_slots:
                            if (busy_key[0] == room and
                                busy_key[1] == date_str):
                                busy_start, busy_end = busy_key[2], busy_key[3]
                                if start_time < busy_end and end_time > busy_start:
                                    has_conflict = True
                                    break

                    if not has_conflict:
                        suggestions.append({
                            "module_id": module_id,
                            "module_name": module_name,
                            "instructor_id": best_instructor["instructor_id"],
                            "instructor_name": best_instructor["name"],
                            "schedule_date": date_str,
                            "start_time": start_time,
                            "end_time": end_time,
                            "room": room,
                            "title": f"{module_name} - {best_instructor['name']}",
                            "schedule_type": "lecture"
                        })
                        instructor_module_count[best_instructor["instructor_id"]] += 1
                        slot_found = True
                        break

                temp_date += timedelta(days=1)

        # Sort by date and start time
        suggestions.sort(key=lambda x: (x["schedule_date"], x["start_time"]))

        self.success({
            "suggestions": suggestions,
            "instructor_count": len(instructors),
            "module_count": len(modules),
            "suggested_count": len(suggestions)
        }, "Schedule optimization completed")

    def _parse_time_ranges(self, time_ranges):
        """Parse time range strings like '09:00-12:00' into tuples"""
        parsed = []
        for time_range in time_ranges:
            if '-' in time_range:
                start, end = time_range.split('-')
                parsed.append((start.strip(), end.strip()))
        return parsed if parsed else [("09:00", "12:00"), ("13:00", "17:00")]
