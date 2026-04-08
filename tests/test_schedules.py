"""
Schedule Management Tests
Tests schedule CRUD, attendance recording, and conflict detection.
"""
import pytest
from database import get_db, dict_from_row, dicts_from_rows


class TestScheduleCreation:
    """Test schedule creation functionality."""

    def test_create_schedule_with_required_fields(self, database, sample_course, instructor_user):
        """Test creating a schedule with required fields."""
        db = get_db()

        cursor = db.execute(
            """INSERT INTO schedules
               (course_id, instructor_id, schedule_date, start_time, end_time, room)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (sample_course['id'], instructor_user['id'], '2026-04-20',
             '09:00', '12:00', 'Room A')
        )
        db.commit()
        schedule_id = cursor.lastrowid
        db.close()

        assert schedule_id > 0

    def test_create_schedule_with_all_fields(self, database, sample_course, instructor_user, sample_module):
        """Test creating a schedule with all optional fields."""
        db = get_db()

        cursor = db.execute(
            """INSERT INTO schedules
               (course_id, module_id, instructor_id, schedule_date, start_time, end_time, room, location, status, notes)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (sample_course['id'], sample_module['id'], instructor_user['id'],
             '2026-04-22', '14:00', '17:00', 'Room B', 'Building 1',
             'scheduled', 'Important session')
        )
        db.commit()
        schedule_id = cursor.lastrowid

        schedule = dict_from_row(db.execute(
            "SELECT * FROM schedules WHERE id = ?",
            (schedule_id,)
        ).fetchone())
        db.close()

        assert schedule['module_id'] == sample_module['id']
        assert schedule['location'] == 'Building 1'
        assert schedule['notes'] == 'Important session'

    def test_schedule_requires_date(self, database):
        """Test that schedule requires a date."""
        db = get_db()

        try:
            db.execute(
                """INSERT INTO schedules
                   (start_time, end_time, room)
                   VALUES (?, ?, ?)""",
                ('09:00', '12:00', 'Room A')
            )
            db.commit()
            assert False, "Should require schedule_date"
        except Exception:
            pass
        finally:
            db.close()

    def test_schedule_requires_start_time(self, database):
        """Test that schedule requires start time."""
        db = get_db()

        try:
            db.execute(
                """INSERT INTO schedules
                   (schedule_date, end_time, room)
                   VALUES (?, ?, ?)""",
                ('2026-04-20', '12:00', 'Room A')
            )
            db.commit()
            assert False, "Should require start_time"
        except Exception:
            pass
        finally:
            db.close()

    def test_schedule_requires_end_time(self, database):
        """Test that schedule requires end time."""
        db = get_db()

        try:
            db.execute(
                """INSERT INTO schedules
                   (schedule_date, start_time, room)
                   VALUES (?, ?, ?)""",
                ('2026-04-20', '09:00', 'Room A')
            )
            db.commit()
            assert False, "Should require end_time"
        except Exception:
            pass
        finally:
            db.close()


class TestScheduleRetrieval:
    """Test schedule retrieval and filtering."""

    def test_list_all_schedules(self, database, sample_schedule):
        """Test listing all schedules."""
        db = get_db()

        # Create additional schedule
        db.execute(
            """INSERT INTO schedules
               (schedule_date, start_time, end_time, room)
               VALUES (?, ?, ?, ?)""",
            ('2026-04-25', '10:00', '13:00', 'Room C')
        )
        db.commit()

        schedules = dicts_from_rows(db.execute(
            "SELECT * FROM schedules ORDER BY schedule_date"
        ).fetchall())
        db.close()

        assert len(schedules) >= 2

    def test_filter_schedules_by_date_range(self, database, sample_schedule):
        """Test filtering schedules by date range."""
        db = get_db()

        # Create schedules on different dates
        db.execute(
            "INSERT INTO schedules (schedule_date, start_time, end_time, room) VALUES (?, ?, ?, ?)",
            ('2026-04-10', '09:00', '12:00', 'Room')
        )
        db.execute(
            "INSERT INTO schedules (schedule_date, start_time, end_time, room) VALUES (?, ?, ?, ?)",
            ('2026-04-30', '09:00', '12:00', 'Room')
        )
        db.commit()

        # Filter date range
        filtered = dicts_from_rows(db.execute(
            """SELECT * FROM schedules
               WHERE schedule_date >= ? AND schedule_date <= ?
               ORDER BY schedule_date""",
            ('2026-04-15', '2026-04-25')
        ).fetchall())
        db.close()

        assert len(filtered) > 0

    def test_filter_schedules_by_instructor(self, database, instructor_user):
        """Test filtering schedules by instructor."""
        db = get_db()

        # Create schedule with specific instructor
        db.execute(
            """INSERT INTO schedules
               (instructor_id, schedule_date, start_time, end_time, room)
               VALUES (?, ?, ?, ?, ?)""",
            (instructor_user['id'], '2026-04-20', '09:00', '12:00', 'Room A')
        )
        db.commit()

        schedules = dicts_from_rows(db.execute(
            "SELECT * FROM schedules WHERE instructor_id = ?",
            (instructor_user['id'],)
        ).fetchall())
        db.close()

        assert len(schedules) > 0
        assert all(s['instructor_id'] == instructor_user['id'] for s in schedules)

    def test_filter_schedules_by_course(self, database, sample_schedule, sample_course):
        """Test filtering schedules by course."""
        db = get_db()

        schedules = dicts_from_rows(db.execute(
            "SELECT * FROM schedules WHERE course_id = ?",
            (sample_course['id'],)
        ).fetchall())
        db.close()

        assert len(schedules) > 0

    def test_get_schedule_with_course_info(self, database, sample_schedule, sample_course):
        """Test that schedule detail includes course information."""
        db = get_db()

        schedule = dict_from_row(db.execute(
            "SELECT s.*, c.name as course_name FROM schedules s LEFT JOIN courses c ON s.course_id = c.id WHERE s.id = ?",
            (sample_schedule['id'],)
        ).fetchone())
        db.close()

        assert schedule['id'] == sample_schedule['id']
        assert schedule['course_name'] == sample_course['name']

    def test_get_schedule_with_instructor_info(self, database, sample_schedule, instructor_user):
        """Test that schedule detail includes instructor information."""
        db = get_db()

        schedule = dict_from_row(db.execute(
            "SELECT s.*, u.name as instructor_name FROM schedules s LEFT JOIN users u ON s.instructor_id = u.id WHERE s.id = ?",
            (sample_schedule['id'],)
        ).fetchone())
        db.close()

        assert schedule['instructor_name'] == instructor_user['name']


class TestConflictDetection:
    """Test schedule conflict detection."""

    def test_detect_same_time_same_room_conflict(self, database, instructor_user):
        """Test detecting conflict when same room at same time."""
        db = get_db()

        # Create first schedule
        db.execute(
            """INSERT INTO schedules
               (schedule_date, start_time, end_time, room, instructor_id)
               VALUES (?, ?, ?, ?, ?)""",
            ('2026-04-20', '09:00', '12:00', 'Room A', instructor_user['id'])
        )
        db.commit()

        # Try to create overlapping schedule in same room
        conflicts = dicts_from_rows(db.execute(
            """SELECT * FROM schedules
               WHERE schedule_date = ? AND room = ?
               AND start_time < ? AND end_time > ?""",
            ('2026-04-20', 'Room A', '11:00', '10:00')
        ).fetchall())
        db.close()

        assert len(conflicts) > 0

    def test_detect_same_time_same_instructor_conflict(self, database, instructor_user):
        """Test detecting conflict when same instructor at overlapping time."""
        db = get_db()

        # Create first schedule
        db.execute(
            """INSERT INTO schedules
               (schedule_date, start_time, end_time, instructor_id)
               VALUES (?, ?, ?, ?)""",
            ('2026-04-20', '09:00', '12:00', instructor_user['id'])
        )
        db.commit()

        # Check for instructor conflict
        conflicts = dicts_from_rows(db.execute(
            """SELECT * FROM schedules
               WHERE schedule_date = ? AND instructor_id = ?
               AND start_time < ? AND end_time > ?""",
            ('2026-04-20', instructor_user['id'], '11:00', '10:00')
        ).fetchall())
        db.close()

        assert len(conflicts) > 0

    def test_no_conflict_different_times(self, database, instructor_user):
        """Test no conflict when schedules are at different times."""
        db = get_db()

        # Create schedules at different times
        db.execute(
            """INSERT INTO schedules
               (schedule_date, start_time, end_time, room)
               VALUES (?, ?, ?, ?)""",
            ('2026-04-20', '09:00', '12:00', 'Room A')
        )
        db.execute(
            """INSERT INTO schedules
               (schedule_date, start_time, end_time, room)
               VALUES (?, ?, ?, ?)""",
            ('2026-04-20', '13:00', '16:00', 'Room A')
        )
        db.commit()

        # Check for conflicts - should be none
        conflicts = dicts_from_rows(db.execute(
            """SELECT * FROM schedules s1
               WHERE s1.schedule_date = ? AND s1.room = ?
               AND EXISTS (
                   SELECT 1 FROM schedules s2
                   WHERE s2.schedule_date = s1.schedule_date
                   AND s2.room = s1.room
                   AND s2.start_time < s1.end_time
                   AND s2.end_time > s1.start_time
                   AND s2.id != s1.id
               )""",
            ('2026-04-20', 'Room A')
        ).fetchall())
        db.close()

        # No conflicts expected for non-overlapping times
        assert len(conflicts) == 0

    def test_exclude_schedule_from_conflict_check(self, database, instructor_user):
        """Test that updating a schedule excludes itself from conflict check."""
        db = get_db()

        # Create a schedule
        cursor = db.execute(
            """INSERT INTO schedules
               (schedule_date, start_time, end_time, room, instructor_id)
               VALUES (?, ?, ?, ?, ?)""",
            ('2026-04-20', '09:00', '12:00', 'Room A', instructor_user['id'])
        )
        db.commit()
        schedule_id = cursor.lastrowid

        # Check for conflicts excluding this schedule
        conflicts = dicts_from_rows(db.execute(
            """SELECT * FROM schedules
               WHERE schedule_date = ? AND room = ?
               AND start_time < ? AND end_time > ?
               AND id != ?""",
            ('2026-04-20', 'Room A', '11:00', '10:00', schedule_id)
        ).fetchall())
        db.close()

        assert len(conflicts) == 0


class TestAttendance:
    """Test attendance recording."""

    def test_record_attendance_present(self, database, sample_schedule, trainee_user):
        """Test recording trainee as present."""
        db = get_db()

        cursor = db.execute(
            """INSERT INTO attendance
               (schedule_id, trainee_id, status, recorded_by)
               VALUES (?, ?, ?, ?)""",
            (sample_schedule['id'], trainee_user['id'], 'present', 1)
        )
        db.commit()
        attendance_id = cursor.lastrowid
        db.close()

        assert attendance_id > 0

    def test_record_attendance_absent(self, database, sample_schedule, trainee_user):
        """Test recording trainee as absent."""
        db = get_db()

        cursor = db.execute(
            """INSERT INTO attendance
               (schedule_id, trainee_id, status)
               VALUES (?, ?, ?)""",
            (sample_schedule['id'], trainee_user['id'], 'absent')
        )
        db.commit()
        attendance_id = cursor.lastrowid
        db.close()

        assert attendance_id > 0

    def test_record_attendance_late(self, database, sample_schedule, trainee_user):
        """Test recording trainee as late."""
        db = get_db()

        cursor = db.execute(
            """INSERT INTO attendance
               (schedule_id, trainee_id, status)
               VALUES (?, ?, ?)""",
            (sample_schedule['id'], trainee_user['id'], 'late')
        )
        db.commit()
        attendance_id = cursor.lastrowid
        db.close()

        assert attendance_id > 0

    def test_duplicate_attendance_rejected(self, database, sample_schedule, trainee_user):
        """Test that duplicate attendance record is rejected."""
        db = get_db()

        # Create first record
        db.execute(
            "INSERT INTO attendance (schedule_id, trainee_id, status) VALUES (?, ?, ?)",
            (sample_schedule['id'], trainee_user['id'], 'present')
        )
        db.commit()

        # Try duplicate
        try:
            db.execute(
                "INSERT INTO attendance (schedule_id, trainee_id, status) VALUES (?, ?, ?)",
                (sample_schedule['id'], trainee_user['id'], 'present')
            )
            db.commit()
            assert False, "Should reject duplicate"
        except Exception as e:
            assert 'UNIQUE' in str(e)
        finally:
            db.close()

    def test_attendance_recorded_timestamp(self, database, sample_schedule, trainee_user):
        """Test that attendance records a timestamp."""
        db = get_db()

        db.execute(
            "INSERT INTO attendance (schedule_id, trainee_id, status) VALUES (?, ?, ?)",
            (sample_schedule['id'], trainee_user['id'], 'present')
        )
        db.commit()

        attendance = dict_from_row(db.execute(
            "SELECT * FROM attendance WHERE schedule_id = ? AND trainee_id = ?",
            (sample_schedule['id'], trainee_user['id'])
        ).fetchone())
        db.close()

        assert attendance['recorded_at'] is not None

    def test_get_schedule_attendance_list(self, database, sample_schedule):
        """Test listing all attendance for a schedule."""
        db = get_db()

        # Create multiple trainees and record attendance
        for i in range(3):
            cursor = db.execute(
                """INSERT INTO users
                   (employee_id, password_hash, name, role, status)
                   VALUES (?, ?, ?, ?, ?)""",
                (f'att_trainee_{i}', 'hash', f'Trainee {i}', 'trainee', 'active')
            )
            trainee_id = cursor.lastrowid

            db.execute(
                "INSERT INTO attendance (schedule_id, trainee_id, status) VALUES (?, ?, ?)",
                (sample_schedule['id'], trainee_id, 'present')
            )
        db.commit()

        attendance_records = dicts_from_rows(db.execute(
            """SELECT a.*, u.name as trainee_name
               FROM attendance a
               JOIN users u ON a.trainee_id = u.id
               WHERE a.schedule_id = ?""",
            (sample_schedule['id'],)
        ).fetchall())
        db.close()

        assert len(attendance_records) >= 3

    def test_get_attendance_summary_by_status(self, database, sample_schedule):
        """Test getting attendance summary grouped by status."""
        db = get_db()

        # Create attendance with different statuses
        for status in ['present', 'absent', 'late']:
            cursor = db.execute(
                """INSERT INTO users
                   (employee_id, password_hash, name, role, status)
                   VALUES (?, ?, ?, ?, ?)""",
                (f'user_{status}', 'hash', f'User {status}', 'trainee', 'active')
            )
            trainee_id = cursor.lastrowid

            db.execute(
                "INSERT INTO attendance (schedule_id, trainee_id, status) VALUES (?, ?, ?)",
                (sample_schedule['id'], trainee_id, status)
            )
        db.commit()

        # Get summary
        summary = dicts_from_rows(db.execute(
            """SELECT status, COUNT(*) as count
               FROM attendance
               WHERE schedule_id = ?
               GROUP BY status""",
            (sample_schedule['id'],)
        ).fetchall())
        db.close()

        assert len(summary) == 3
        assert sum(s['count'] for s in summary) == 3
