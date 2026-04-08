"""Work Schedule Routes: Personal work schedule management for operators and instructors."""
import json
from routes.auth_routes import BaseHandler
from database import get_db, dicts_from_rows
from auth import require_auth, get_current_user


class WorkSchedulesHandler(BaseHandler):
    """GET list / POST create work schedules."""

    @require_auth
    def get(self):
        user = get_current_user(self)
        conn = get_db()
        c = conn.cursor()

        page = int(self.get_argument('page', 1))
        per_page = int(self.get_argument('per_page', 50))
        offset = (page - 1) * per_page
        user_id = self.get_argument('user_id', '')
        date_from = self.get_argument('date_from', '')
        date_to = self.get_argument('date_to', '')
        schedule_type = self.get_argument('type', '')

        conditions = []
        params = []

        # Admin/ojt_admin can see all; others see only their own
        if user['role'] not in ('admin', 'ojt_admin', 'manager', 'staff', 'customer'):
            conditions.append("ws.user_id = ?")
            params.append(user['id'])
        elif user_id:
            conditions.append("ws.user_id = ?")
            params.append(int(user_id))

        if date_from:
            conditions.append("ws.schedule_date >= ?")
            params.append(date_from)
        if date_to:
            conditions.append("ws.schedule_date <= ?")
            params.append(date_to)
        if schedule_type:
            conditions.append("ws.schedule_type = ?")
            params.append(schedule_type)

        where_clause = " WHERE " + " AND ".join(conditions) if conditions else ""

        # Count
        c.execute(f"SELECT COUNT(*) FROM work_schedules ws{where_clause}", params)
        total = c.fetchone()[0]

        # Fetch with user name join
        c.execute(f"""
            SELECT ws.*, u.name as user_name, u.role as user_role, u.department as user_department
            FROM work_schedules ws
            LEFT JOIN users u ON ws.user_id = u.id
            {where_clause}
            ORDER BY ws.schedule_date DESC, ws.start_time ASC
            LIMIT ? OFFSET ?
        """, params + [per_page, offset])
        rows = dicts_from_rows(c)

        import math
        total_pages = math.ceil(total / per_page) if per_page > 0 else 1

        conn.close()
        self.success({
            "data": rows,
            "pagination": {
                "page": page,
                "per_page": per_page,
                "total": total,
                "total_pages": total_pages
            }
        })

    @require_auth
    def post(self):
        user = get_current_user(self)
        body = self.get_json_body()

        title = body.get('title', '').strip()
        schedule_date = body.get('schedule_date', '').strip()
        start_time = body.get('start_time', '').strip()
        end_time = body.get('end_time', '').strip()
        schedule_type = body.get('schedule_type', 'work')
        notes = body.get('notes', '').strip()

        # Admin can assign to others; otherwise self
        target_user_id = user['id']
        if user['role'] in ('admin', 'ojt_admin') and body.get('user_id'):
            target_user_id = int(body['user_id'])

        if not schedule_date:
            return self.error("날짜를 입력하세요")
        if not start_time or not end_time:
            return self.error("시작 시간과 종료 시간을 입력하세요")

        valid_types = ('work', 'leave', 'holiday', 'overtime', 'duty', 'half_day')
        if schedule_type not in valid_types:
            return self.error(f"유효한 유형: {', '.join(valid_types)}")

        conn = get_db()
        c = conn.cursor()

        c.execute("""
            INSERT INTO work_schedules (user_id, title, schedule_date, start_time, end_time, schedule_type, notes)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, [target_user_id, title, schedule_date, start_time, end_time, schedule_type, notes])

        new_id = c.lastrowid
        conn.commit()
        conn.close()

        self.success({"id": new_id}, "근무 스케줄이 등록되었습니다")


class WorkScheduleDetailHandler(BaseHandler):
    """GET/PUT/DELETE a single work schedule entry."""

    @require_auth
    def get(self, ws_id):
        conn = get_db()
        c = conn.cursor()
        c.execute("""
            SELECT ws.*, u.name as user_name, u.role as user_role
            FROM work_schedules ws
            LEFT JOIN users u ON ws.user_id = u.id
            WHERE ws.id = ?
        """, [int(ws_id)])
        rows = dicts_from_rows(c)
        conn.close()

        if not rows:
            return self.error("스케줄을 찾을 수 없습니다", 404)
        self.success(rows[0])

    @require_auth
    def put(self, ws_id):
        user = get_current_user(self)
        body = self.get_json_body()
        conn = get_db()
        c = conn.cursor()

        # Check ownership or admin
        c.execute("SELECT user_id FROM work_schedules WHERE id = ?", [int(ws_id)])
        row = c.fetchone()
        if not row:
            conn.close()
            return self.error("스케줄을 찾을 수 없습니다", 404)

        owner_id = row[0]
        if user['role'] not in ('admin', 'ojt_admin') and user['id'] != owner_id:
            conn.close()
            return self.error("수정 권한이 없습니다", 403)

        updates = []
        params = []
        for field in ('title', 'schedule_date', 'start_time', 'end_time', 'schedule_type', 'notes'):
            if field in body:
                updates.append(f"{field} = ?")
                params.append(body[field])

        if not updates:
            conn.close()
            return self.error("수정할 항목이 없습니다")

        params.append(int(ws_id))
        c.execute(f"UPDATE work_schedules SET {', '.join(updates)} WHERE id = ?", params)
        conn.commit()
        conn.close()
        self.success(None, "근무 스케줄이 수정되었습니다")

    @require_auth
    def delete(self, ws_id):
        user = get_current_user(self)
        conn = get_db()
        c = conn.cursor()

        c.execute("SELECT user_id FROM work_schedules WHERE id = ?", [int(ws_id)])
        row = c.fetchone()
        if not row:
            conn.close()
            return self.error("스케줄을 찾을 수 없습니다", 404)

        owner_id = row[0]
        if user['role'] not in ('admin', 'ojt_admin') and user['id'] != owner_id:
            conn.close()
            return self.error("삭제 권한이 없습니다", 403)

        c.execute("DELETE FROM work_schedules WHERE id = ?", [int(ws_id)])
        conn.commit()
        conn.close()
        self.success(None, "근무 스케줄이 삭제되었습니다")


class WorkScheduleSummaryHandler(BaseHandler):
    """GET work schedule summary/attendance stats for a user."""

    @require_auth
    def get(self):
        user = get_current_user(self)
        user_id = self.get_argument('user_id', str(user['id']))

        # Non-admin can only view own summary
        if user['role'] not in ('admin', 'ojt_admin', 'manager', 'staff', 'customer'):
            user_id = str(user['id'])

        month = self.get_argument('month', '')  # YYYY-MM format

        conn = get_db()
        c = conn.cursor()

        conditions = ["user_id = ?"]
        params = [int(user_id)]

        if month:
            conditions.append("schedule_date LIKE ?")
            params.append(month + '%')

        where_clause = " WHERE " + " AND ".join(conditions)

        c.execute(f"""
            SELECT schedule_type, COUNT(*) as count
            FROM work_schedules
            {where_clause}
            GROUP BY schedule_type
        """, params)
        type_counts = dicts_from_rows(c)

        c.execute(f"""
            SELECT COUNT(*) as total_days,
                   SUM(CASE WHEN schedule_type = 'work' THEN 1 ELSE 0 END) as work_days,
                   SUM(CASE WHEN schedule_type = 'leave' THEN 1 ELSE 0 END) as leave_days,
                   SUM(CASE WHEN schedule_type = 'holiday' THEN 1 ELSE 0 END) as holiday_days,
                   SUM(CASE WHEN schedule_type = 'overtime' THEN 1 ELSE 0 END) as overtime_days,
                   SUM(CASE WHEN schedule_type = 'half_day' THEN 1 ELSE 0 END) as half_days
            FROM work_schedules
            {where_clause}
        """, params)
        summary = dicts_from_rows(c)

        conn.close()
        self.success({
            "type_counts": type_counts,
            "summary": summary[0] if summary else {}
        })
