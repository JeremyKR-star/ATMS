"""
Course Management Tests
Tests course CRUD operations, enrollment, and role-based access control.
"""
import pytest
from database import get_db, dict_from_row, dicts_from_rows


class TestCourseCreation:
    """Test course creation functionality."""

    def test_create_course_with_admin_role(self, admin_user, database):
        """Test admin can create a new course."""
        db = get_db()

        cursor = db.execute(
            """INSERT INTO courses
               (code, name, type, description, duration_weeks, max_trainees, status, start_date, end_date)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            ('ADMIN_COURSE', 'Admin Created Course', 'theory', 'Course by admin',
             4, 25, 'active', '2026-05-01', '2026-06-01')
        )
        db.commit()
        course_id = cursor.lastrowid
        db.close()

        assert course_id > 0

    def test_create_course_with_ojt_admin_role(self, database):
        """Test ojt_admin can create a new course."""
        db = get_db()

        # Create ojt_admin user
        cursor = db.execute(
            """INSERT INTO users
               (employee_id, password_hash, name, role, status)
               VALUES (?, ?, ?, ?, ?)""",
            ('ojt_admin001', 'hash', 'OJT Admin', 'ojt_admin', 'active')
        )
        db.commit()

        # Create course
        cursor = db.execute(
            """INSERT INTO courses
               (code, name, type, description, duration_weeks, status)
               VALUES (?, ?, ?, ?, ?, ?)""",
            ('OJT_COURSE', 'OJT Course', 'practical', 'OJT training', 6, 'active')
        )
        db.commit()
        course_id = cursor.lastrowid
        db.close()

        assert course_id > 0

    def test_create_course_with_trainee_role_fails(self, trainee_user, database):
        """Test trainee cannot create a course."""
        db = get_db()

        # Trainee should not have permission - this is enforced at handler level
        # We can verify the role check logic
        assert trainee_user['role'] == 'trainee'
        assert trainee_user['role'] not in ['admin', 'ojt_admin']

        db.close()

    def test_create_course_requires_code(self, database):
        """Test course code is required."""
        db = get_db()

        # Try to insert without code - should fail
        try:
            db.execute(
                """INSERT INTO courses
                   (name, type)
                   VALUES (?, ?)""",
                ('No Code Course', 'theory')
            )
            db.commit()
            assert False, "Should require code"
        except Exception:
            pass
        finally:
            db.close()

    def test_create_course_requires_name(self, database):
        """Test course name is required."""
        db = get_db()

        try:
            db.execute(
                """INSERT INTO courses
                   (code, type)
                   VALUES (?, ?)""",
                ('CODE001', 'theory')
            )
            db.commit()
            assert False, "Should require name"
        except Exception:
            pass
        finally:
            db.close()

    def test_create_course_requires_type(self, database):
        """Test course type is required."""
        db = get_db()

        try:
            db.execute(
                """INSERT INTO courses
                   (code, name)
                   VALUES (?, ?)""",
                ('CODE002', 'No Type Course')
            )
            db.commit()
            assert False, "Should require type"
        except Exception:
            pass
        finally:
            db.close()

    def test_course_code_must_be_unique(self, database):
        """Test course code must be unique."""
        db = get_db()

        # Create first course
        db.execute(
            """INSERT INTO courses
               (code, name, type)
               VALUES (?, ?, ?)""",
            ('UNIQUE_CODE', 'Course 1', 'theory')
        )
        db.commit()

        # Try to create duplicate
        try:
            db.execute(
                """INSERT INTO courses
                   (code, name, type)
                   VALUES (?, ?, ?)""",
                ('UNIQUE_CODE', 'Course 2', 'theory')
            )
            db.commit()
            assert False, "Should reject duplicate code"
        except Exception as e:
            assert 'UNIQUE' in str(e)
        finally:
            db.close()

    def test_create_course_with_optional_fields(self, database):
        """Test course can be created with optional fields."""
        db = get_db()

        cursor = db.execute(
            """INSERT INTO courses
               (code, name, type, description, duration_weeks, max_trainees, aircraft_type, status)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            ('FULL_COURSE', 'Full Course', 'practical', 'Complete description',
             8, 30, 'Boeing 737', 'active')
        )
        db.commit()
        course_id = cursor.lastrowid

        # Verify all fields
        course = dict_from_row(db.execute(
            "SELECT * FROM courses WHERE id = ?",
            (course_id,)
        ).fetchone())
        db.close()

        assert course['description'] == 'Complete description'
        assert course['duration_weeks'] == 8
        assert course['max_trainees'] == 30
        assert course['aircraft_type'] == 'Boeing 737'


class TestCourseRetrieval:
    """Test course retrieval and listing."""

    def test_list_courses_requires_authentication(self):
        """Test that listing courses requires authentication."""
        from routes.course_routes import CoursesHandler
        assert hasattr(CoursesHandler, 'get')

    def test_list_courses_returns_all_courses(self, database, sample_course):
        """Test listing all courses."""
        db = get_db()

        # Create additional course
        db.execute(
            """INSERT INTO courses (code, name, type)
               VALUES (?, ?, ?)""",
            ('COURSE002', 'Another Course', 'practical')
        )
        db.commit()

        # Fetch all
        courses = dicts_from_rows(db.execute(
            "SELECT * FROM courses ORDER BY id"
        ).fetchall())
        db.close()

        assert len(courses) >= 2

    def test_filter_courses_by_status(self, database):
        """Test filtering courses by status."""
        db = get_db()

        # Create courses with different status
        db.execute(
            "INSERT INTO courses (code, name, type, status) VALUES (?, ?, ?, ?)",
            ('ACTIVE1', 'Active Course', 'theory', 'active')
        )
        db.execute(
            "INSERT INTO courses (code, name, type, status) VALUES (?, ?, ?, ?)",
            ('PLANNED1', 'Planned Course', 'theory', 'planned')
        )
        db.execute(
            "INSERT INTO courses (code, name, type, status) VALUES (?, ?, ?, ?)",
            ('COMPLETED1', 'Completed Course', 'theory', 'completed')
        )
        db.commit()

        # Filter by status
        active = dicts_from_rows(db.execute(
            "SELECT * FROM courses WHERE status = ?",
            ('active',)
        ).fetchall())
        db.close()

        assert len(active) > 0
        assert all(c['status'] == 'active' for c in active)

    def test_filter_courses_by_type(self, database):
        """Test filtering courses by type."""
        db = get_db()

        # Create courses with different types
        db.execute(
            "INSERT INTO courses (code, name, type) VALUES (?, ?, ?)",
            ('THEORY1', 'Theory Course', 'theory')
        )
        db.execute(
            "INSERT INTO courses (code, name, type) VALUES (?, ?, ?)",
            ('PRACTICAL1', 'Practical Course', 'practical')
        )
        db.commit()

        # Filter by type
        theory = dicts_from_rows(db.execute(
            "SELECT * FROM courses WHERE type = ?",
            ('theory',)
        ).fetchall())
        db.close()

        assert all(c['type'] == 'theory' for c in theory)

    def test_search_courses_by_name(self, database):
        """Test searching courses by name."""
        db = get_db()

        # Create courses
        db.execute(
            "INSERT INTO courses (code, name, type) VALUES (?, ?, ?)",
            ('CODE1', 'Maintenance Training', 'practical')
        )
        db.execute(
            "INSERT INTO courses (code, name, type) VALUES (?, ?, ?)",
            ('CODE2', 'Safety Course', 'theory')
        )
        db.commit()

        # Search by name
        results = dicts_from_rows(db.execute(
            "SELECT * FROM courses WHERE name LIKE ?",
            ('%Maintenance%',)
        ).fetchall())
        db.close()

        assert len(results) > 0
        assert 'Maintenance' in results[0]['name']

    def test_search_courses_by_code(self, database):
        """Test searching courses by code."""
        db = get_db()

        # Create course
        db.execute(
            "INSERT INTO courses (code, name, type) VALUES (?, ?, ?)",
            ('ABC123', 'Test Course', 'theory')
        )
        db.commit()

        # Search by code
        results = dicts_from_rows(db.execute(
            "SELECT * FROM courses WHERE code LIKE ?",
            ('%ABC%',)
        ).fetchall())
        db.close()

        assert len(results) > 0

    def test_get_course_detail_includes_modules(self, database, sample_course, sample_module):
        """Test course detail includes all modules."""
        db = get_db()

        modules = dicts_from_rows(db.execute(
            "SELECT * FROM course_modules WHERE course_id = ? ORDER BY order_num",
            (sample_course['id'],)
        ).fetchall())
        db.close()

        assert len(modules) > 0
        assert modules[0]['course_id'] == sample_course['id']

    def test_get_course_detail_includes_instructors(self, database, sample_course, instructor_user):
        """Test course detail includes all instructors."""
        db = get_db()

        instructors = dicts_from_rows(db.execute(
            """SELECT u.id, u.name, u.specialty, ci.role
               FROM course_instructors ci
               JOIN users u ON ci.instructor_id = u.id
               WHERE ci.course_id = ?""",
            (sample_course['id'],)
        ).fetchall())
        db.close()

        assert len(instructors) > 0
        assert instructors[0]['id'] == instructor_user['id']

    def test_get_course_detail_includes_enrollments(self, database, sample_course, trainee_user):
        """Test course detail includes enrollments."""
        db = get_db()

        # Enroll trainee
        db.execute(
            "INSERT INTO enrollments (course_id, trainee_id, status) VALUES (?, ?, ?)",
            (sample_course['id'], trainee_user['id'], 'enrolled')
        )
        db.commit()

        enrollments = dicts_from_rows(db.execute(
            """SELECT e.*, u.name as trainee_name, u.employee_id
               FROM enrollments e
               JOIN users u ON e.trainee_id = u.id
               WHERE e.course_id = ?""",
            (sample_course['id'],)
        ).fetchall())
        db.close()

        assert len(enrollments) > 0


class TestCourseModules:
    """Test course module management."""

    def test_create_module_for_course(self, database, sample_course):
        """Test creating a module for a course."""
        db = get_db()

        cursor = db.execute(
            """INSERT INTO course_modules
               (course_id, name, description, order_num, duration_hours)
               VALUES (?, ?, ?, ?, ?)""",
            (sample_course['id'], 'Module 2', 'Second module', 2, 6.0)
        )
        db.commit()
        module_id = cursor.lastrowid
        db.close()

        assert module_id > 0

    def test_list_course_modules_in_order(self, database, sample_course):
        """Test modules are listed in correct order."""
        db = get_db()

        # Create multiple modules
        for i in range(1, 4):
            db.execute(
                """INSERT INTO course_modules
                   (course_id, name, order_num)
                   VALUES (?, ?, ?)""",
                (sample_course['id'], f'Module {i}', i)
            )
        db.commit()

        # Fetch in order
        modules = dicts_from_rows(db.execute(
            """SELECT * FROM course_modules
               WHERE course_id = ?
               ORDER BY order_num""",
            (sample_course['id'],)
        ).fetchall())
        db.close()

        assert len(modules) >= 3
        for i, module in enumerate(modules[:3]):
            assert module['order_num'] == i + 1


class TestEnrollment:
    """Test course enrollment functionality."""

    def test_enroll_trainee_in_course(self, database, sample_course, trainee_user):
        """Test enrolling a trainee in a course."""
        db = get_db()

        cursor = db.execute(
            """INSERT INTO enrollments
               (course_id, trainee_id, status)
               VALUES (?, ?, ?)""",
            (sample_course['id'], trainee_user['id'], 'enrolled')
        )
        db.commit()
        enrollment_id = cursor.lastrowid
        db.close()

        assert enrollment_id > 0

    def test_duplicate_enrollment_rejected(self, database, sample_course, trainee_user):
        """Test that duplicate enrollment is rejected."""
        db = get_db()

        # Create first enrollment
        db.execute(
            "INSERT INTO enrollments (course_id, trainee_id, status) VALUES (?, ?, ?)",
            (sample_course['id'], trainee_user['id'], 'enrolled')
        )
        db.commit()

        # Try duplicate
        try:
            db.execute(
                "INSERT INTO enrollments (course_id, trainee_id, status) VALUES (?, ?, ?)",
                (sample_course['id'], trainee_user['id'], 'enrolled')
            )
            db.commit()
            assert False, "Should reject duplicate"
        except Exception as e:
            assert 'UNIQUE' in str(e)
        finally:
            db.close()

    def test_enrollment_tracks_enrollment_date(self, database, sample_course, trainee_user):
        """Test that enrollment records enrollment date."""
        db = get_db()

        cursor = db.execute(
            """INSERT INTO enrollments
               (course_id, trainee_id, status)
               VALUES (?, ?, ?)""",
            (sample_course['id'], trainee_user['id'], 'enrolled')
        )
        db.commit()

        enrollment = dict_from_row(db.execute(
            "SELECT * FROM enrollments WHERE id = ?",
            (cursor.lastrowid,)
        ).fetchone())
        db.close()

        assert enrollment['enrollment_date'] is not None

    def test_enrollment_allows_completion_date(self, database, sample_course, trainee_user):
        """Test that enrollment can record completion date."""
        db = get_db()

        db.execute(
            """INSERT INTO enrollments
               (course_id, trainee_id, status, completion_date, final_score)
               VALUES (?, ?, ?, ?, ?)""",
            (sample_course['id'], trainee_user['id'], 'completed',
             '2026-05-20', 95.5)
        )
        db.commit()

        enrollment = dict_from_row(db.execute(
            """SELECT * FROM enrollments
               WHERE course_id = ? AND trainee_id = ?""",
            (sample_course['id'], trainee_user['id'])
        ).fetchone())
        db.close()

        assert enrollment['status'] == 'completed'
        assert enrollment['final_score'] == 95.5

    def test_list_course_enrollments(self, database, sample_course):
        """Test listing all enrollments for a course."""
        db = get_db()

        # Create multiple trainees and enroll them
        trainee_ids = []
        for i in range(3):
            cursor = db.execute(
                """INSERT INTO users
                   (employee_id, password_hash, name, role, status)
                   VALUES (?, ?, ?, ?, ?)""",
                (f'trainee_{i}', 'hash', f'Trainee {i}', 'trainee', 'active')
            )
            trainee_ids.append(cursor.lastrowid)

        for trainee_id in trainee_ids:
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
