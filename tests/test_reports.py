"""
Report and Analytics Tests
Tests dashboard stats, course reports, and attendance reports.
"""
import pytest
from database import get_db, dict_from_row, dicts_from_rows


class TestDashboardStats:
    """Test dashboard statistics."""

    def test_count_total_courses(self, database, sample_course):
        """Test counting total courses."""
        db = get_db()

        # Create additional course
        db.execute(
            "INSERT INTO courses (code, name, type) VALUES (?, ?, ?)",
            ('DASH_COURSE', 'Dashboard Test Course', 'theory')
        )
        db.commit()

        result = dict_from_row(db.execute(
            "SELECT COUNT(*) as count FROM courses"
        ).fetchone())
        db.close()

        assert result['count'] >= 2

    def test_count_active_courses(self, database):
        """Test counting active courses."""
        db = get_db()

        # Create courses with different statuses
        db.execute(
            "INSERT INTO courses (code, name, type, status) VALUES (?, ?, ?, ?)",
            ('ACTIVE1', 'Active Course 1', 'theory', 'active')
        )
        db.execute(
            "INSERT INTO courses (code, name, type, status) VALUES (?, ?, ?, ?)",
            ('ACTIVE2', 'Active Course 2', 'practical', 'active')
        )
        db.execute(
            "INSERT INTO courses (code, name, type, status) VALUES (?, ?, ?, ?)",
            ('PLANNED1', 'Planned Course', 'theory', 'planned')
        )
        db.commit()

        result = dict_from_row(db.execute(
            "SELECT COUNT(*) as count FROM courses WHERE status = ?",
            ('active',)
        ).fetchone())
        db.close()

        assert result['count'] >= 2

    def test_count_total_users_by_role(self, database, admin_user, instructor_user, trainee_user):
        """Test counting users by role."""
        db = get_db()

        # Create additional users
        db.execute(
            """INSERT INTO users
               (employee_id, password_hash, name, role, status)
               VALUES (?, ?, ?, ?, ?)""",
            ('extra_trainee', 'hash', 'Extra Trainee', 'trainee', 'active')
        )
        db.commit()

        stats = dicts_from_rows(db.execute(
            """SELECT role, COUNT(*) as count
               FROM users
               GROUP BY role
               ORDER BY count DESC"""
        ).fetchall())
        db.close()

        assert len(stats) > 0

    def test_count_total_enrollments(self, database, sample_course, trainee_user):
        """Test counting total enrollments."""
        db = get_db()

        # Create enrollments
        db.execute(
            "INSERT INTO enrollments (course_id, trainee_id, status) VALUES (?, ?, ?)",
            (sample_course['id'], trainee_user['id'], 'enrolled')
        )

        # Create another trainee
        cursor = db.execute(
            """INSERT INTO users
               (employee_id, password_hash, name, role, status)
               VALUES (?, ?, ?, ?, ?)""",
            ('enroll_test', 'hash', 'Enrollment Test', 'trainee', 'active')
        )
        trainee_id2 = cursor.lastrowid

        db.execute(
            "INSERT INTO enrollments (course_id, trainee_id, status) VALUES (?, ?, ?)",
            (sample_course['id'], trainee_id2, 'enrolled')
        )
        db.commit()

        result = dict_from_row(db.execute(
            "SELECT COUNT(*) as count FROM enrollments"
        ).fetchone())
        db.close()

        assert result['count'] >= 2

    def test_count_enrollments_by_status(self, database, sample_course, trainee_user):
        """Test counting enrollments by status."""
        db = get_db()

        # Create enrollments with different statuses
        db.execute(
            "INSERT INTO enrollments (course_id, trainee_id, status) VALUES (?, ?, ?)",
            (sample_course['id'], trainee_user['id'], 'enrolled')
        )

        cursor = db.execute(
            """INSERT INTO users
               (employee_id, password_hash, name, role, status)
               VALUES (?, ?, ?, ?, ?)""",
            ('status_test', 'hash', 'Status Test', 'trainee', 'active')
        )
        trainee_id2 = cursor.lastrowid

        db.execute(
            "INSERT INTO enrollments (course_id, trainee_id, status) VALUES (?, ?, ?)",
            (sample_course['id'], trainee_id2, 'completed')
        )
        db.commit()

        stats = dicts_from_rows(db.execute(
            """SELECT status, COUNT(*) as count
               FROM enrollments
               GROUP BY status"""
        ).fetchall())
        db.close()

        assert len(stats) >= 2


class TestCourseReports:
    """Test course-specific reports."""

    def test_course_enrollment_summary(self, database, sample_course):
        """Test getting course enrollment summary."""
        db = get_db()

        # Create enrollments
        for i in range(3):
            cursor = db.execute(
                """INSERT INTO users
                   (employee_id, password_hash, name, role, status)
                   VALUES (?, ?, ?, ?, ?)""",
                (f'report_trainee_{i}', 'hash', f'Report Trainee {i}', 'trainee', 'active')
            )
            trainee_id = cursor.lastrowid

            db.execute(
                "INSERT INTO enrollments (course_id, trainee_id, status) VALUES (?, ?, ?)",
                (sample_course['id'], trainee_id, 'enrolled')
            )
        db.commit()

        enrollments = dicts_from_rows(db.execute(
            """SELECT e.*, u.name as trainee_name
               FROM enrollments e
               JOIN users u ON e.trainee_id = u.id
               WHERE e.course_id = ?""",
            (sample_course['id'],)
        ).fetchall())
        db.close()

        assert len(enrollments) >= 3

    def test_course_module_stats(self, database, sample_course):
        """Test getting course module statistics."""
        db = get_db()

        # Create modules
        for i in range(3):
            db.execute(
                """INSERT INTO course_modules
                   (course_id, name, order_num, duration_hours)
                   VALUES (?, ?, ?, ?)""",
                (sample_course['id'], f'Module {i}', i, 8.0 + i)
            )
        db.commit()

        modules = dicts_from_rows(db.execute(
            "SELECT * FROM course_modules WHERE course_id = ? ORDER BY order_num",
            (sample_course['id'],)
        ).fetchall())
        db.close()

        assert len(modules) >= 3

    def test_course_average_score(self, database, sample_course, trainee_user):
        """Test calculating average course score."""
        db = get_db()

        # Create enrollments with final scores
        db.execute(
            """INSERT INTO enrollments
               (course_id, trainee_id, status, final_score)
               VALUES (?, ?, ?, ?)""",
            (sample_course['id'], trainee_user['id'], 'completed', 85.0)
        )

        cursor = db.execute(
            """INSERT INTO users
               (employee_id, password_hash, name, role, status)
               VALUES (?, ?, ?, ?, ?)""",
            ('score_test', 'hash', 'Score Test', 'trainee', 'active')
        )
        trainee_id2 = cursor.lastrowid

        db.execute(
            """INSERT INTO enrollments
               (course_id, trainee_id, status, final_score)
               VALUES (?, ?, ?, ?)""",
            (sample_course['id'], trainee_id2, 'completed', 92.0)
        )
        db.commit()

        result = dict_from_row(db.execute(
            """SELECT AVG(final_score) as avg_score
               FROM enrollments
               WHERE course_id = ? AND final_score IS NOT NULL""",
            (sample_course['id'],)
        ).fetchone())
        db.close()

        assert result['avg_score'] is not None
        assert result['avg_score'] > 0


class TestAttendanceReports:
    """Test attendance reporting."""

    def test_attendance_by_schedule(self, database, sample_schedule):
        """Test getting attendance for a schedule."""
        db = get_db()

        # Create trainees and record attendance
        statuses = ['present', 'absent', 'late']
        for status in statuses:
            cursor = db.execute(
                """INSERT INTO users
                   (employee_id, password_hash, name, role, status)
                   VALUES (?, ?, ?, ?, ?)""",
                (f'att_{status}', 'hash', f'Att {status}', 'trainee', 'active')
            )
            trainee_id = cursor.lastrowid

            db.execute(
                "INSERT INTO attendance (schedule_id, trainee_id, status) VALUES (?, ?, ?)",
                (sample_schedule['id'], trainee_id, status)
            )
        db.commit()

        attendance = dicts_from_rows(db.execute(
            """SELECT status, COUNT(*) as count
               FROM attendance
               WHERE schedule_id = ?
               GROUP BY status""",
            (sample_schedule['id'],)
        ).fetchall())
        db.close()

        assert len(attendance) >= 2

    def test_attendance_rate_by_trainee(self, database, sample_schedule, trainee_user):
        """Test calculating attendance rate for a trainee."""
        db = get_db()

        # Create multiple schedules
        for i in range(4):
            cursor = db.execute(
                """INSERT INTO schedules
                   (schedule_date, start_time, end_time, room)
                   VALUES (?, ?, ?, ?)""",
                (f'2026-04-{15+i}', '09:00', '12:00', f'Room {i}')
            )
            schedule_id = cursor.lastrowid

            # Record attendance - 3 present, 1 absent
            status = 'present' if i < 3 else 'absent'
            db.execute(
                "INSERT INTO attendance (schedule_id, trainee_id, status) VALUES (?, ?, ?)",
                (schedule_id, trainee_user['id'], status)
            )
        db.commit()

        result = dict_from_row(db.execute(
            """SELECT
                COUNT(*) as total,
                SUM(CASE WHEN status = 'present' THEN 1 ELSE 0 END) as present
               FROM attendance
               WHERE trainee_id = ?""",
            (trainee_user['id'],)
        ).fetchone())
        db.close()

        assert result['total'] >= 4
        assert result['present'] >= 3

    def test_attendance_summary_by_date(self, database, trainee_user):
        """Test attendance summary grouped by date."""
        db = get_db()

        # Create schedules on different dates
        dates = ['2026-04-15', '2026-04-15', '2026-04-20']
        for date in dates:
            cursor = db.execute(
                """INSERT INTO schedules
                   (schedule_date, start_time, end_time, room)
                   VALUES (?, ?, ?, ?)""",
                (date, '09:00', '12:00', 'Room')
            )
            schedule_id = cursor.lastrowid

            db.execute(
                "INSERT INTO attendance (schedule_id, trainee_id, status) VALUES (?, ?, ?)",
                (schedule_id, trainee_user['id'], 'present')
            )
        db.commit()

        summary = dicts_from_rows(db.execute(
            """SELECT s.schedule_date, COUNT(*) as count
               FROM attendance a
               JOIN schedules s ON a.schedule_id = s.id
               WHERE a.trainee_id = ?
               GROUP BY s.schedule_date
               ORDER BY s.schedule_date""",
            (trainee_user['id'],)
        ).fetchall())
        db.close()

        assert len(summary) >= 2


class TestTraineeReports:
    """Test trainee-specific reports."""

    def test_trainee_course_history(self, database, trainee_user):
        """Test getting trainee's course history."""
        db = get_db()

        # Create courses and enroll trainee
        for i in range(3):
            cursor = db.execute(
                "INSERT INTO courses (code, name, type) VALUES (?, ?, ?)",
                (f'TRAIN_COURSE_{i}', f'Training Course {i}', 'theory')
            )
            course_id = cursor.lastrowid

            db.execute(
                "INSERT INTO enrollments (course_id, trainee_id, status) VALUES (?, ?, ?)",
                (course_id, trainee_user['id'], 'completed')
            )
        db.commit()

        history = dicts_from_rows(db.execute(
            """SELECT c.*, e.enrollment_date, e.final_score
               FROM enrollments e
               JOIN courses c ON e.course_id = c.id
               WHERE e.trainee_id = ?
               ORDER BY e.enrollment_date DESC""",
            (trainee_user['id'],)
        ).fetchall())
        db.close()

        assert len(history) >= 3

    def test_trainee_evaluation_summary(self, database, trainee_user, sample_course):
        """Test getting trainee's evaluation summary."""
        db = get_db()

        # Create evaluations with different statuses
        for status, score in [('pending', None), ('submitted', None), ('graded', 92.5)]:
            db.execute(
                """INSERT INTO evaluations
                   (course_id, trainee_id, eval_type, title, status, score)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (sample_course['id'], trainee_user['id'], 'test',
                 f'Test {status}', status, score)
            )
        db.commit()

        summary = dicts_from_rows(db.execute(
            """SELECT status, COUNT(*) as count
               FROM evaluations
               WHERE trainee_id = ?
               GROUP BY status""",
            (trainee_user['id'],)
        ).fetchall())
        db.close()

        assert len(summary) >= 2

    def test_trainee_average_performance(self, database, trainee_user, sample_course):
        """Test calculating trainee's average performance."""
        db = get_db()

        # Create graded evaluations
        for i in range(3):
            db.execute(
                """INSERT INTO evaluations
                   (course_id, trainee_id, eval_type, title, max_score, score, status)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (sample_course['id'], trainee_user['id'], 'test',
                 f'Test {i}', 100, 85.0 + i, 'graded')
            )
        db.commit()

        result = dict_from_row(db.execute(
            """SELECT AVG(score) as avg_score, MAX(score) as max_score, MIN(score) as min_score
               FROM evaluations
               WHERE trainee_id = ? AND score IS NOT NULL""",
            (trainee_user['id'],)
        ).fetchone())
        db.close()

        assert result['avg_score'] is not None


class TestMonthlyStats:
    """Test monthly statistics."""

    def test_enrollments_by_month(self, database, sample_course):
        """Test getting enrollments grouped by month."""
        db = get_db()

        # Create enrollments
        for i in range(5):
            cursor = db.execute(
                """INSERT INTO users
                   (employee_id, password_hash, name, role, status)
                   VALUES (?, ?, ?, ?, ?)""",
                (f'monthly_{i}', 'hash', f'Monthly {i}', 'trainee', 'active')
            )
            trainee_id = cursor.lastrowid

            db.execute(
                "INSERT INTO enrollments (course_id, trainee_id, status) VALUES (?, ?, ?)",
                (sample_course['id'], trainee_id, 'enrolled')
            )
        db.commit()

        result = dict_from_row(db.execute(
            "SELECT COUNT(*) as count FROM enrollments"
        ).fetchone())
        db.close()

        assert result['count'] >= 5

    def test_active_users_by_month(self, database):
        """Test getting active user counts."""
        db = get_db()

        # Create access logs
        for i in range(10):
            db.execute(
                """INSERT INTO access_logs
                   (ip_address, method, path, status_code, response_time_ms)
                   VALUES (?, ?, ?, ?, ?)""",
                (f'192.168.1.{i}', 'GET', '/api/courses', 200, 45.5)
            )
        db.commit()

        result = dict_from_row(db.execute(
            "SELECT COUNT(DISTINCT ip_address) as unique_ips FROM access_logs"
        ).fetchone())
        db.close()

        assert result['unique_ips'] >= 5
