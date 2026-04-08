"""Reporting & Analytics Routes"""
import traceback
import csv
import io
from routes.auth_routes import BaseHandler
from database import get_db, dicts_from_rows
from auth import require_auth


class DashboardHandler(BaseHandler):
    @require_auth()
    def get(self):
        db = get_db()
        try:
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
            avg = db.execute("SELECT AVG(CAST(score AS FLOAT)/CAST(max_score AS FLOAT)*100) FROM evaluations WHERE status='graded' AND max_score > 0").fetchone()[0]
            stats["avg_eval_score"] = round(float(avg), 1) if avg else 0

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
        except Exception as ex:
            db.close()
            print(f"[DashboardHandler ERROR] {ex}\n{traceback.format_exc()}")
            self.error(f"Dashboard error: {str(ex)}", 500)


class CourseReportHandler(BaseHandler):
    @require_auth(roles=["admin", "instructor", "ojt_admin", "manager"])
    def get(self):
        db = get_db()
        try:
            courses = dicts_from_rows(db.execute("""
                SELECT c.id, c.name, c.code, c.type, c.status, c.start_date, c.end_date,
                       c.max_trainees, c.description, c.created_at,
                       COUNT(DISTINCT e.trainee_id) as enrolled_count,
                       COUNT(DISTINCT CASE WHEN e.status='completed' THEN e.trainee_id END) as completed_count,
                       ROUND(CAST(AVG(CASE WHEN e.status='completed' THEN CAST(e.final_score AS FLOAT) END) AS NUMERIC), 1) as avg_score,
                       ROUND(CAST(AVG(s.overall_rating) AS NUMERIC), 1) as avg_satisfaction
                FROM courses c
                LEFT JOIN enrollments e ON c.id = e.course_id
                LEFT JOIN surveys s ON c.id = s.course_id
                GROUP BY c.id, c.name, c.code, c.type, c.status, c.start_date, c.end_date,
                         c.max_trainees, c.description, c.created_at
                ORDER BY c.start_date DESC
            """).fetchall())
            db.close()
            self.success(courses)
        except Exception as ex:
            db.close()
            print(f"[CourseReportHandler ERROR] {ex}\n{traceback.format_exc()}")
            self.error(f"Course report error: {str(ex)}", 500)


class TraineeReportHandler(BaseHandler):
    @require_auth(roles=["admin", "instructor", "ojt_admin", "manager"])
    def get(self):
        db = get_db()
        try:
            trainees = dicts_from_rows(db.execute("""
                SELECT u.id, u.employee_id, u.name, u.department, u.status,
                       COUNT(DISTINCT e.course_id) as courses_enrolled,
                       COUNT(DISTINCT CASE WHEN e.status='completed' THEN e.course_id END) as courses_completed,
                       ROUND(CAST(AVG(CASE WHEN ev.status='graded' THEN CAST(ev.score AS FLOAT)/CAST(ev.max_score AS FLOAT)*100 END) AS NUMERIC), 1) as avg_score
                FROM users u
                LEFT JOIN enrollments e ON u.id = e.trainee_id
                LEFT JOIN evaluations ev ON u.id = ev.trainee_id AND ev.max_score > 0
                WHERE u.role = 'trainee'
                GROUP BY u.id, u.employee_id, u.name, u.department, u.status
                ORDER BY u.name
            """).fetchall())
            db.close()
            self.success(trainees)
        except Exception as ex:
            db.close()
            print(f"[TraineeReportHandler ERROR] {ex}\n{traceback.format_exc()}")
            self.error(f"Trainee report error: {str(ex)}", 500)


class AttendanceReportHandler(BaseHandler):
    @require_auth(roles=["admin", "instructor", "ojt_admin", "manager"])
    def get(self):
        course_id = self.get_argument("course_id", None)
        db = get_db()
        try:
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
            query += " GROUP BY u.id, u.name, u.employee_id ORDER BY u.name"

            records = dicts_from_rows(db.execute(query, params).fetchall())
            db.close()
            self.success(records)
        except Exception as ex:
            db.close()
            print(f"[AttendanceReportHandler ERROR] {ex}\n{traceback.format_exc()}")
            self.error(f"Attendance report error: {str(ex)}", 500)


class MonthlyStatsHandler(BaseHandler):
    @require_auth(roles=["admin", "ojt_admin", "manager"])
    def get(self):
        db = get_db()
        try:
            # Monthly enrollment trends (last 12 months)
            monthly = dicts_from_rows(db.execute("""
                SELECT strftime('%Y-%m', enrolled_at) as month,
                       COUNT(*) as enrollments,
                       SUM(CASE WHEN status='completed' THEN 1 ELSE 0 END) as completions
                FROM enrollments
                WHERE enrolled_at >= DATE('now', '-12 months')
                GROUP BY strftime('%Y-%m', enrolled_at) ORDER BY month
            """).fetchall())

            # Monthly evaluation averages
            eval_monthly = dicts_from_rows(db.execute("""
                SELECT strftime('%Y-%m', graded_at) as month,
                       ROUND(CAST(AVG(CAST(score AS FLOAT)/CAST(max_score AS FLOAT)*100) AS NUMERIC), 1) as avg_score,
                       COUNT(*) as eval_count
                FROM evaluations
                WHERE status='graded' AND max_score > 0 AND graded_at >= DATE('now', '-12 months')
                GROUP BY strftime('%Y-%m', graded_at) ORDER BY month
            """).fetchall())

            db.close()
            self.success({"enrollment_trends": monthly, "evaluation_trends": eval_monthly})
        except Exception as ex:
            db.close()
            print(f"[MonthlyStatsHandler ERROR] {ex}\n{traceback.format_exc()}")
            self.error(f"Monthly stats error: {str(ex)}", 500)


class ModuleAttendanceReportHandler(BaseHandler):
    """Attendance breakdown by Course/Module/Class per the PDF spec (p.6)"""
    @require_auth(roles=["admin", "instructor", "ojt_admin", "manager"])
    def get(self):
        course_id = self.get_argument("course_id", None)
        db = get_db()
        try:
            query = """
                SELECT c.name as course_name, c.id as course_id,
                       cm.name as module_name, cm.id as module_id,
                       s.title as session_title, s.schedule_date, s.start_time, s.end_time,
                       u.name as trainee_name, u.employee_id,
                       a.status as attendance_status, a.check_in_time
                FROM attendance a
                JOIN users u ON a.trainee_id = u.id
                JOIN schedules s ON a.schedule_id = s.id
                LEFT JOIN courses c ON s.course_id = c.id
                LEFT JOIN course_modules cm ON s.module_id = cm.id
            """
            params = []
            if course_id:
                query += " WHERE s.course_id = ?"
                params.append(course_id)
            query += " ORDER BY c.name, cm.order_num, s.schedule_date, u.name"

            records = dicts_from_rows(db.execute(query, params).fetchall())

            # Aggregate by course/module
            summary = {}
            for r in records:
                ckey = str(r.get("course_id", "none"))
                if ckey not in summary:
                    summary[ckey] = {"course_name": r.get("course_name", "-"), "modules": {}, "total": 0, "present": 0, "absent": 0, "late": 0, "excused": 0}
                summary[ckey]["total"] += 1
                status = r.get("attendance_status", "")
                if status in ("present", "absent", "late", "excused"):
                    summary[ckey][status] += 1

                mkey = str(r.get("module_id", "none"))
                if mkey not in summary[ckey]["modules"]:
                    summary[ckey]["modules"][mkey] = {"module_name": r.get("module_name", "-"), "total": 0, "present": 0, "absent": 0, "late": 0, "excused": 0}
                summary[ckey]["modules"][mkey]["total"] += 1
                if status in ("present", "absent", "late", "excused"):
                    summary[ckey]["modules"][mkey][status] += 1

            # Convert to list
            result = []
            for ckey, cdata in summary.items():
                modules_list = []
                for mkey, mdata in cdata["modules"].items():
                    rate = round(mdata["present"] / mdata["total"] * 100, 1) if mdata["total"] > 0 else 0
                    mdata["attendance_rate"] = rate
                    modules_list.append(mdata)
                rate = round(cdata["present"] / cdata["total"] * 100, 1) if cdata["total"] > 0 else 0
                result.append({
                    "course_name": cdata["course_name"],
                    "total": cdata["total"], "present": cdata["present"],
                    "absent": cdata["absent"], "late": cdata["late"], "excused": cdata["excused"],
                    "attendance_rate": rate,
                    "modules": modules_list
                })

            db.close()
            self.success({"summary": result, "details": records[:500]})
        except Exception as ex:
            db.close()
            print(f"[ModuleAttendanceReportHandler ERROR] {ex}\n{traceback.format_exc()}")
            self.error(f"Module attendance report error: {str(ex)}", 500)


class OJTTaskCompletionReportHandler(BaseHandler):
    """OJT task completion report by program (PDF spec p.12)"""
    @require_auth(roles=["admin", "ojt_admin", "manager", "instructor"])
    def get(self):
        program_id = self.get_argument("program_id", None)
        db = get_db()
        try:
            query = """
                SELECT p.id as program_id, p.name as program_name, p.status as program_status,
                       t.id as task_id, t.name as task_name, t.order_num,
                       COUNT(DISTINCT tr.id) as total_results,
                       SUM(CASE WHEN tr.completion_status='completed' THEN 1 ELSE 0 END) as completed_count,
                       SUM(CASE WHEN tr.completion_status='in_progress' THEN 1 ELSE 0 END) as in_progress_count,
                       SUM(CASE WHEN tr.completion_status='pending' THEN 1 ELSE 0 END) as pending_count,
                       SUM(CASE WHEN tr.completion_status='failed' THEN 1 ELSE 0 END) as failed_count,
                       ROUND(CAST(AVG(CASE WHEN tr.score IS NOT NULL THEN CAST(tr.score AS FLOAT) END) AS NUMERIC), 1) as avg_score
                FROM ojt_programs p
                LEFT JOIN ojt_tasks t ON t.program_id = p.id
                LEFT JOIN ojt_training_results tr ON tr.task_id = t.id
            """
            params = []
            if program_id:
                query += " WHERE p.id = ?"
                params.append(program_id)
            query += " GROUP BY p.id, p.name, p.status, t.id, t.name, t.order_num ORDER BY p.name, t.order_num"
            data = dicts_from_rows(db.execute(query, params).fetchall())
            db.close()
            self.success(data)
        except Exception as ex:
            db.close()
            self.error(f"OJT task completion report error: {str(ex)}", 500)


class OJTTraineeProgressReportHandler(BaseHandler):
    """OJT trainee progress by level (PDF spec p.14)"""
    @require_auth(roles=["admin", "ojt_admin", "manager", "instructor"])
    def get(self):
        program_id = self.get_argument("program_id", None)
        db = get_db()
        try:
            query = """
                SELECT u.id as trainee_id, u.name as trainee_name, u.employee_id,
                       p.name as program_name, p.id as program_id,
                       oe.status as enrollment_status, oe.progress,
                       COUNT(DISTINCT tr.id) as total_tasks,
                       SUM(CASE WHEN tr.completion_status='completed' THEN 1 ELSE 0 END) as completed_tasks,
                       ROUND(CAST(AVG(CASE WHEN tr.score IS NOT NULL THEN CAST(tr.score AS FLOAT) END) AS NUMERIC), 1) as avg_score,
                       COUNT(DISTINCT oev.id) as total_evaluations,
                       SUM(CASE WHEN oev.status='pass' THEN 1 ELSE 0 END) as passed_evaluations
                FROM ojt_enrollments oe
                JOIN users u ON oe.trainee_id = u.id
                JOIN ojt_programs p ON oe.program_id = p.id
                LEFT JOIN ojt_training_results tr ON tr.enrollment_id = oe.id
                LEFT JOIN ojt_evaluations oev ON oev.enrollment_id = oe.id
            """
            params = []
            if program_id:
                query += " WHERE oe.program_id = ?"
                params.append(program_id)
            query += " GROUP BY u.id, u.name, u.employee_id, p.name, p.id, oe.status, oe.progress ORDER BY p.name, u.name"
            data = dicts_from_rows(db.execute(query, params).fetchall())
            db.close()
            self.success(data)
        except Exception as ex:
            db.close()
            self.error(f"OJT trainee progress report error: {str(ex)}", 500)


class OJTLeaderEvalSummaryHandler(BaseHandler):
    """OJT leader evaluation summaries (PDF spec p.12)"""
    @require_auth(roles=["admin", "ojt_admin", "manager"])
    def get(self):
        program_id = self.get_argument("program_id", None)
        db = get_db()
        try:
            query = """
                SELECT ev.name as evaluator_name, ev.id as evaluator_id,
                       p.name as program_name, p.id as program_id,
                       COUNT(DISTINCT oev.id) as total_evaluations,
                       SUM(CASE WHEN oev.status='pass' THEN 1 ELSE 0 END) as pass_count,
                       SUM(CASE WHEN oev.status='fail' THEN 1 ELSE 0 END) as fail_count,
                       SUM(CASE WHEN oev.status='needs_improvement' THEN 1 ELSE 0 END) as needs_improvement_count,
                       ROUND(CAST(AVG(CASE WHEN oev.score IS NOT NULL THEN CAST(oev.score AS FLOAT) / CAST(oev.max_score AS FLOAT) * 100 END) AS NUMERIC), 1) as avg_score_pct,
                       COUNT(DISTINCT oe.trainee_id) as trainees_evaluated
                FROM ojt_evaluations oev
                JOIN ojt_enrollments oe ON oev.enrollment_id = oe.id
                JOIN ojt_programs p ON oe.program_id = p.id
                LEFT JOIN users ev ON oev.evaluator_id = ev.id
            """
            params = []
            if program_id:
                query += " WHERE oe.program_id = ?"
                params.append(program_id)
            query += " GROUP BY ev.name, ev.id, p.name, p.id ORDER BY p.name, ev.name"
            data = dicts_from_rows(db.execute(query, params).fetchall())
            db.close()
            self.success(data)
        except Exception as ex:
            db.close()
            self.error(f"OJT leader eval summary error: {str(ex)}", 500)


class ReportExportHandler(BaseHandler):
    @require_auth(roles=["admin", "instructor", "ojt_admin", "manager"])
    def get(self):
        report_type = self.get_argument("type", None)
        db = get_db()
        try:
            valid_types = ["courses", "trainees", "attendance", "ojt_results", "ojt_evaluations"]
            if not report_type or report_type not in valid_types:
                self.error(f"Invalid report type. Must be one of: {', '.join(valid_types)}", 400)
                return

            # Generate CSV data
            if report_type == "courses":
                data = dicts_from_rows(db.execute("""
                    SELECT c.id, c.name, c.code, c.type, c.status, c.start_date, c.end_date,
                           c.max_trainees, c.description, c.created_at,
                           COUNT(DISTINCT e.trainee_id) as enrolled_count,
                           COUNT(DISTINCT CASE WHEN e.status='completed' THEN e.trainee_id END) as completed_count,
                           ROUND(CAST(AVG(CASE WHEN e.status='completed' THEN CAST(e.final_score AS FLOAT) END) AS NUMERIC), 1) as avg_score,
                           ROUND(CAST(AVG(s.overall_rating) AS NUMERIC), 1) as avg_satisfaction
                    FROM courses c
                    LEFT JOIN enrollments e ON c.id = e.course_id
                    LEFT JOIN surveys s ON c.id = s.course_id
                    GROUP BY c.id, c.name, c.code, c.type, c.status, c.start_date, c.end_date,
                             c.max_trainees, c.description, c.created_at
                    ORDER BY c.start_date DESC
                """).fetchall())
                filename = "courses_report.csv"

            elif report_type == "trainees":
                data = dicts_from_rows(db.execute("""
                    SELECT u.id, u.employee_id, u.name, u.department, u.status,
                           COUNT(DISTINCT e.course_id) as courses_enrolled,
                           COUNT(DISTINCT CASE WHEN e.status='completed' THEN e.course_id END) as courses_completed,
                           ROUND(CAST(AVG(CASE WHEN ev.status='graded' THEN CAST(ev.score AS FLOAT)/CAST(ev.max_score AS FLOAT)*100 END) AS NUMERIC), 1) as avg_score
                    FROM users u
                    LEFT JOIN enrollments e ON u.id = e.trainee_id
                    LEFT JOIN evaluations ev ON u.id = ev.trainee_id AND ev.max_score > 0
                    WHERE u.role = 'trainee'
                    GROUP BY u.id, u.employee_id, u.name, u.department, u.status
                    ORDER BY u.name
                """).fetchall())
                filename = "trainees_report.csv"

            elif report_type == "attendance":
                data = dicts_from_rows(db.execute("""
                    SELECT u.id as trainee_id, u.name as trainee_name, u.employee_id,
                           COUNT(a.id) as total_sessions,
                           SUM(CASE WHEN a.status='present' THEN 1 ELSE 0 END) as present,
                           SUM(CASE WHEN a.status='absent' THEN 1 ELSE 0 END) as absent,
                           SUM(CASE WHEN a.status='late' THEN 1 ELSE 0 END) as late,
                           SUM(CASE WHEN a.status='excused' THEN 1 ELSE 0 END) as excused
                    FROM attendance a
                    JOIN users u ON a.trainee_id = u.id
                    JOIN schedules s ON a.schedule_id = s.id
                    GROUP BY u.id, u.name, u.employee_id ORDER BY u.name
                """).fetchall())
                filename = "attendance_report.csv"

            elif report_type == "ojt_results":
                program_id = self.get_argument("program_id", None)
                query = """
                    SELECT tr.id, u.name as trainee_name, u.employee_id,
                           p.name as program_name, t.name as task_name,
                           tr.attendance_status, tr.completion_status, tr.score,
                           tr.notes, tr.result_date
                    FROM ojt_training_results tr
                    JOIN ojt_enrollments oe ON tr.enrollment_id = oe.id
                    JOIN users u ON oe.trainee_id = u.id
                    JOIN ojt_programs p ON oe.program_id = p.id
                    LEFT JOIN ojt_tasks t ON tr.task_id = t.id
                """
                params_ojt = []
                if program_id:
                    query += " WHERE oe.program_id = ?"
                    params_ojt.append(program_id)
                query += " ORDER BY u.name, t.order_num"
                data = dicts_from_rows(db.execute(query, params_ojt).fetchall())
                filename = "ojt_results_report.csv"

            elif report_type == "ojt_evaluations":
                program_id = self.get_argument("program_id", None)
                query = """
                    SELECT oe_eval.id, u.name as trainee_name, u.employee_id,
                           p.name as program_name, t.name as task_name,
                           ev.name as evaluator_name,
                           oe_eval.score, oe_eval.max_score, oe_eval.status,
                           oe_eval.feedback, oe_eval.eval_date
                    FROM ojt_evaluations oe_eval
                    JOIN ojt_enrollments oe ON oe_eval.enrollment_id = oe.id
                    JOIN users u ON oe.trainee_id = u.id
                    JOIN ojt_programs p ON oe.program_id = p.id
                    LEFT JOIN ojt_tasks t ON oe_eval.task_id = t.id
                    LEFT JOIN users ev ON oe_eval.evaluator_id = ev.id
                """
                params_ojt = []
                if program_id:
                    query += " WHERE oe.program_id = ?"
                    params_ojt.append(program_id)
                query += " ORDER BY u.name, oe_eval.eval_date DESC"
                data = dicts_from_rows(db.execute(query, params_ojt).fetchall())
                filename = "ojt_evaluations_report.csv"

            # Convert to CSV
            if data:
                output = io.StringIO()
                writer = csv.DictWriter(output, fieldnames=data[0].keys())
                writer.writeheader()
                writer.writerows(data)
                csv_content = output.getvalue()
            else:
                csv_content = ""

            db.close()

            # Set response headers for file download
            self.set_header("Content-Type", "text/csv; charset=utf-8")
            self.set_header("Content-Disposition", f"attachment; filename={filename}")
            self.write(csv_content)
        except Exception as ex:
            db.close()
            print(f"[ReportExportHandler ERROR] {ex}\n{traceback.format_exc()}")
            self.error(f"Report export error: {str(ex)}", 500)
