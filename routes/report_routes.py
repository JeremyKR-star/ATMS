"""Reporting & Analytics Routes"""
from routes.auth_routes import BaseHandler
from database import get_db, dicts_from_rows
from auth import require_auth


class DashboardHandler(BaseHandler):
    @require_auth()
    def get(self):
        db = get_db()
        stats = {}

        # Total counts
        stats["total_users"] = db.execute("SELECT COUNT(*) FROM users WHERE status='active'").fetchone()[0]
        stats["total_courses"] = db.execute("SELECT COUNT(*) FROM courses").fetchone()[0]
        stats["active_courses"] = db.execute("SELECT COUNT(*) FROM courses WHERE status='active'").fetchone()[0]
        stats["total_enrollments"] = db.execute("SELECT COUNT(*) FROM enrollments").fetchone()[0]
        stats["total_trainees"] = db.execute("SELECT COUNT(*) FROM users WHERE role='trainee' AND status='active'").fetchone()[0]
        stats["total_instructors"] = db.execute("SELECT COUNT(*) FROM users WHERE role='instructor' AND status='active'").fetchone()[0]

        # Course completion rate
        completed = db.execute("SELECT COUNT(*) FROM enrollments WHERE status='completed'").fetchone()[0]
        total_enrolled = db.execute("SELECT COUNT(*) FROM enrollments WHERE status IN ('enrolled','in_progress','completed','failed')").fetchone()[0]
        stats["completion_rate"] = round((completed / total_enrolled * 100) if total_enrolled > 0 else 0, 1)

        # Average evaluation score
        avg = db.execute("SELECT AVG(score/max_score*100) FROM evaluations WHERE status='graded' AND max_score > 0").fetchone()[0]
        stats["avg_eval_score"] = round(avg, 1) if avg else 0

        # Users by role
        stats["users_by_role"] = dicts_from_rows(db.execute(
            "SELECT role, COUNT(*) as count FROM users WHERE status='active' GROUP BY role ORDER BY count DESC"
        ).fetchall())

        # Courses by type
        stats["courses_by_type"] = dicts_from_rows(db.execute(
            "SELECT type, COUNT(*) as count FROM courses GROUP BY type"
        ).fetchall())

        # Courses by status
        stats["courses_by_status"] = dicts_from_rows(db.execute(
            "SELECT status, COUNT(*) as count FROM courses GROUP BY status ORDER BY count DESC"
        ).fetchall())

        # Recent enrollments (last 10)
        stats["recent_enrollments"] = dicts_from_rows(db.execute("""
            SELECT e.*, u.name as trainee_name, c.name as course_name
            FROM enrollments e
            JOIN users u ON e.trainee_id = u.id
            JOIN courses c ON e.course_id = c.id
            ORDER BY e.enrolled_at DESC LIMIT 10
        """).fetchall())

        # Upcoming schedules (next 7 days)
        stats["upcoming_schedules"] = dicts_from_rows(db.execute("""
            SELECT s.*, c.name as course_name, u.name as instructor_name
            FROM schedules s
            LEFT JOIN courses c ON s.course_id = c.id
            LEFT JOIN users u ON s.instructor_id = u.id
            WHERE s.schedule_date >= CAST(DATE('now') AS TEXT) AND s.schedule_date <= CAST(DATE('now', '+7 days') AS TEXT)
            ORDER BY s.schedule_date, s.start_time LIMIT 10
        """).fetchall())

        # OJT stats
        stats["ojt_programs"] = db.execute("SELECT COUNT(*) FROM ojt_programs").fetchone()[0]
        stats["ojt_enrollments"] = db.execute("SELECT COUNT(*) FROM ojt_enrollments").fetchone()[0]

        db.close()
        self.success(stats)


class CourseReportHandler(BaseHandler):
    @require_auth(roles=["admin", "instructor", "ojt_admin", "manager"])
    def get(self):
        db = get_db()
        courses = dicts_from_rows(db.execute("""
            SELECT c.*,
                   COUNT(DISTINCT e.trainee_id) as enrolled_count,
                   COUNT(DISTINCT CASE WHEN e.status='completed' THEN e.trainee_id END) as completed_count,
                   ROUND(AVG(CASE WHEN e.status='completed' THEN e.final_score END), 1) as avg_score,
                   ROUND(AVG(s.overall_rating), 1) as avg_satisfaction
            FROM courses c
            LEFT JOIN enrollments e ON c.id = e.course_id
            LEFT JOIN surveys s ON c.id = s.course_id
            GROUP BY c.id
            ORDER BY c.start_date DESC
        """).fetchall())
        db.close()
        self.success(courses)


class TraineeReportHandler(BaseHandler):
    @require_auth(roles=["admin", "instructor", "ojt_admin", "manager"])
    def get(self):
        db = get_db()
        trainees = dicts_from_rows(db.execute("""
            SELECT u.id, u.employee_id, u.name, u.department, u.status,
                   COUNT(DISTINCT e.course_id) as courses_enrolled,
                   COUNT(DISTINCT CASE WHEN e.status='completed' THEN e.course_id END) as courses_completed,
                   ROUND(AVG(CASE WHEN ev.status='graded' THEN ev.score/ev.max_score*100 END), 1) as avg_score
            FROM users u
            LEFT JOIN enrollments e ON u.id = e.trainee_id
            LEFT JOIN evaluations ev ON u.id = ev.trainee_id AND ev.max_score > 0
            WHERE u.role = 'trainee'
            GROUP BY u.id
            ORDER BY u.name
        """).fetchall())
        db.close()
        self.success(trainees)


class AttendanceReportHandler(BaseHandler):
    @require_auth(roles=["admin", "instructor", "ojt_admin", "manager"])
    def get(self):
        course_id = self.get_argument("course_id", None)
        db = get_db()
        query = """
            SELECT u.id as trainee_id, u.name as trainee_name, u.employee_id,
                   COUNT(a.id) as total_sessions,
                   SUM(CASE WHEN a.status='present' THEN 1 ELSE 0 END) as present,
                   SUM(CASE WHEN a.status='absent' THEN 1 ELSE 0 END) as absent,
                   SUM(CASE WHEN a.status='late' THEN 1 ELSE 0 END) as late,
                   SUM(CASE WHEN a.status='excused' THEN 1 ELSE 0 END) as excused
            FROM attendance a
            JOIN users u ON a.trainee_id = u.id
            JOIN schedules s ON a.schedule_id = s.id
        """
        params = []
        if course_id:
            query += " WHERE s.course_id = ?"
            params.append(course_id)
        query += " GROUP BY u.id ORDER BY u.name"

        records = dicts_from_rows(db.execute(query, params).fetchall())
        db.close()
        self.success(records)


class MonthlyStatsHandler(BaseHandler):
    @require_auth(roles=["admin", "ojt_admin", "manager"])
    def get(self):
        db = get_db()
        # Monthly enrollment trends (last 12 months)
        monthly = dicts_from_rows(db.execute("""
            SELECT strftime('%Y-%m', enrolled_at) as month,
                   COUNT(*) as enrollments,
                   SUM(CASE WHEN status='completed' THEN 1 ELSE 0 END) as completions
            FROM enrollments
            WHERE enrolled_at >= DATE('now', '-12 months')
            GROUP BY month ORDER BY month
        """).fetchall())

        # Monthly evaluation averages
        eval_monthly = dicts_from_rows(db.execute("""
            SELECT strftime('%Y-%m', graded_at) as month,
                   ROUND(AVG(score/max_score*100), 1) as avg_score,
                   COUNT(*) as eval_count
            FROM evaluations
            WHERE status='graded' AND max_score > 0 AND graded_at >= DATE('now', '-12 months')
            GROUP BY month ORDER BY month
        """).fetchall())

        db.close()
        self.success({"enrollment_trends": monthly, "evaluation_trends": eval_monthly})
