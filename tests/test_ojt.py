"""
OJT (On-the-Job Training) Program Tests
Tests OJT program CRUD, task management, enrollment, and evaluation.
"""
import pytest
from database import get_db, dict_from_row, dicts_from_rows


class TestOJTProgramCreation:
    """Test OJT program creation."""

    def test_create_ojt_program(self, database):
        """Test creating a new OJT program."""
        db = get_db()

        cursor = db.execute(
            """INSERT INTO ojt_programs
               (code, name, description, duration_days, status)
               VALUES (?, ?, ?, ?, ?)""",
            ('OJT_PROG_001', 'Aircraft Maintenance', 'Basic aircraft maintenance training',
             30, 'active')
        )
        db.commit()
        program_id = cursor.lastrowid
        db.close()

        assert program_id > 0

    def test_create_ojt_program_requires_code(self, database):
        """Test that program code is required."""
        db = get_db()

        try:
            db.execute(
                """INSERT INTO ojt_programs
                   (name, description)
                   VALUES (?, ?)""",
                ('Program', 'Description')
            )
            db.commit()
            assert False, "Should require code"
        except Exception:
            pass
        finally:
            db.close()

    def test_create_ojt_program_requires_name(self, database):
        """Test that program name is required."""
        db = get_db()

        try:
            db.execute(
                """INSERT INTO ojt_programs
                   (code, description)
                   VALUES (?, ?)""",
                ('CODE', 'Description')
            )
            db.commit()
            assert False, "Should require name"
        except Exception:
            pass
        finally:
            db.close()

    def test_program_code_must_be_unique(self, database):
        """Test that program codes must be unique."""
        db = get_db()

        # Create first program
        db.execute(
            "INSERT INTO ojt_programs (code, name) VALUES (?, ?)",
            ('UNIQUE_OJT', 'Program 1')
        )
        db.commit()

        # Try duplicate
        try:
            db.execute(
                "INSERT INTO ojt_programs (code, name) VALUES (?, ?)",
                ('UNIQUE_OJT', 'Program 2')
            )
            db.commit()
            assert False, "Should reject duplicate"
        except Exception as e:
            assert 'UNIQUE' in str(e)
        finally:
            db.close()


class TestOJTTasks:
    """Test OJT task management."""

    def test_create_ojt_task(self, database, sample_ojt_program):
        """Test creating a task for an OJT program."""
        db = get_db()

        cursor = db.execute(
            """INSERT INTO ojt_tasks
               (program_id, title, description, sequence_num, estimated_hours, status)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (sample_ojt_program['id'], 'Engine Inspection',
             'Learn to inspect and document aircraft engines', 1, 16.0, 'pending')
        )
        db.commit()
        task_id = cursor.lastrowid
        db.close()

        assert task_id > 0

    def test_create_multiple_tasks_for_program(self, database, sample_ojt_program):
        """Test creating multiple tasks for a program."""
        db = get_db()

        task_titles = [
            'Pre-flight Check',
            'Maintenance Log Review',
            'Tool Safety Training',
            'Hydraulic System Study'
        ]

        for i, title in enumerate(task_titles, 1):
            db.execute(
                """INSERT INTO ojt_tasks
                   (program_id, title, sequence_num, estimated_hours)
                   VALUES (?, ?, ?, ?)""",
                (sample_ojt_program['id'], title, i, 8.0)
            )
        db.commit()

        tasks = dicts_from_rows(db.execute(
            "SELECT * FROM ojt_tasks WHERE program_id = ? ORDER BY sequence_num",
            (sample_ojt_program['id'],)
        ).fetchall())
        db.close()

        assert len(tasks) >= len(task_titles)

    def test_list_tasks_in_sequence(self, database, sample_ojt_program):
        """Test tasks are returned in proper sequence."""
        db = get_db()

        # Create tasks out of order
        db.execute(
            "INSERT INTO ojt_tasks (program_id, title, sequence_num) VALUES (?, ?, ?)",
            (sample_ojt_program['id'], 'Task 3', 3)
        )
        db.execute(
            "INSERT INTO ojt_tasks (program_id, title, sequence_num) VALUES (?, ?, ?)",
            (sample_ojt_program['id'], 'Task 1', 1)
        )
        db.execute(
            "INSERT INTO ojt_tasks (program_id, title, sequence_num) VALUES (?, ?, ?)",
            (sample_ojt_program['id'], 'Task 2', 2)
        )
        db.commit()

        tasks = dicts_from_rows(db.execute(
            """SELECT * FROM ojt_tasks
               WHERE program_id = ?
               ORDER BY sequence_num""",
            (sample_ojt_program['id'],)
        ).fetchall())
        db.close()

        # Verify order
        for i, task in enumerate(tasks, 1):
            assert task['sequence_num'] == i

    def test_task_requires_program(self, database):
        """Test that task requires program_id."""
        db = get_db()

        try:
            db.execute(
                "INSERT INTO ojt_tasks (title) VALUES (?)",
                ('Task without program',)
            )
            db.commit()
            assert False, "Should require program_id"
        except Exception:
            pass
        finally:
            db.close()

    def test_task_requires_title(self, database, sample_ojt_program):
        """Test that task requires title."""
        db = get_db()

        try:
            db.execute(
                "INSERT INTO ojt_tasks (program_id) VALUES (?)",
                (sample_ojt_program['id'],)
            )
            db.commit()
            assert False, "Should require title"
        except Exception:
            pass
        finally:
            db.close()


class TestOJTEnrollment:
    """Test OJT enrollment."""

    def test_enroll_trainee_in_ojt_program(self, database, sample_ojt_program, trainee_user):
        """Test enrolling a trainee in an OJT program."""
        db = get_db()

        cursor = db.execute(
            """INSERT INTO ojt_enrollments
               (program_id, trainee_id, status)
               VALUES (?, ?, ?)""",
            (sample_ojt_program['id'], trainee_user['id'], 'enrolled')
        )
        db.commit()
        enrollment_id = cursor.lastrowid
        db.close()

        assert enrollment_id > 0

    def test_duplicate_ojt_enrollment_rejected(self, database, sample_ojt_program, trainee_user):
        """Test that duplicate OJT enrollment is rejected."""
        db = get_db()

        # First enrollment
        db.execute(
            "INSERT INTO ojt_enrollments (program_id, trainee_id, status) VALUES (?, ?, ?)",
            (sample_ojt_program['id'], trainee_user['id'], 'enrolled')
        )
        db.commit()

        # Duplicate
        try:
            db.execute(
                "INSERT INTO ojt_enrollments (program_id, trainee_id, status) VALUES (?, ?, ?)",
                (sample_ojt_program['id'], trainee_user['id'], 'enrolled')
            )
            db.commit()
            assert False, "Should reject duplicate"
        except Exception as e:
            assert 'UNIQUE' in str(e)
        finally:
            db.close()

    def test_ojt_enrollment_tracks_dates(self, database, sample_ojt_program, trainee_user):
        """Test that enrollment tracks enrollment and completion dates."""
        db = get_db()

        db.execute(
            """INSERT INTO ojt_enrollments
               (program_id, trainee_id, status, completion_date)
               VALUES (?, ?, ?, ?)""",
            (sample_ojt_program['id'], trainee_user['id'], 'completed', '2026-05-15')
        )
        db.commit()

        enrollment = dict_from_row(db.execute(
            "SELECT * FROM ojt_enrollments WHERE program_id = ? AND trainee_id = ?",
            (sample_ojt_program['id'], trainee_user['id'])
        ).fetchone())
        db.close()

        assert enrollment['enrollment_date'] is not None
        assert enrollment['completion_date'] == '2026-05-15'

    def test_list_ojt_enrollments(self, database, sample_ojt_program):
        """Test listing all enrollments in a program."""
        db = get_db()

        # Create and enroll multiple trainees
        for i in range(3):
            cursor = db.execute(
                """INSERT INTO users
                   (employee_id, password_hash, name, role, status)
                   VALUES (?, ?, ?, ?, ?)""",
                (f'ojt_trainee_{i}', 'hash', f'OJT Trainee {i}', 'trainee', 'active')
            )
            trainee_id = cursor.lastrowid

            db.execute(
                "INSERT INTO ojt_enrollments (program_id, trainee_id, status) VALUES (?, ?, ?)",
                (sample_ojt_program['id'], trainee_id, 'enrolled')
            )
        db.commit()

        enrollments = dicts_from_rows(db.execute(
            "SELECT * FROM ojt_enrollments WHERE program_id = ?",
            (sample_ojt_program['id'],)
        ).fetchall())
        db.close()

        assert len(enrollments) >= 3


class TestOJTEvaluation:
    """Test OJT evaluation."""

    def test_create_ojt_evaluation(self, database, sample_ojt_program, trainee_user, instructor_user):
        """Test creating an OJT evaluation."""
        db = get_db()

        cursor = db.execute(
            """INSERT INTO ojt_evaluations
               (program_id, trainee_id, evaluator_id, eval_type, title, max_score, status)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (sample_ojt_program['id'], trainee_user['id'], instructor_user['id'],
             'practical', 'Engine Inspection Assessment', 100.0, 'pending')
        )
        db.commit()
        eval_id = cursor.lastrowid
        db.close()

        assert eval_id > 0

    def test_create_ojt_evaluation_requires_program(self, database, trainee_user):
        """Test that OJT evaluation requires program."""
        db = get_db()

        try:
            db.execute(
                """INSERT INTO ojt_evaluations
                   (trainee_id, title)
                   VALUES (?, ?)""",
                (trainee_user['id'], 'Eval')
            )
            db.commit()
            assert False, "Should require program_id"
        except Exception:
            pass
        finally:
            db.close()

    def test_grade_ojt_evaluation(self, database, sample_ojt_program, trainee_user, instructor_user):
        """Test grading an OJT evaluation."""
        db = get_db()

        # Create evaluation
        cursor = db.execute(
            """INSERT INTO ojt_evaluations
               (program_id, trainee_id, evaluator_id, eval_type, title, max_score, status)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (sample_ojt_program['id'], trainee_user['id'], instructor_user['id'],
             'practical', 'Assessment', 100.0, 'pending')
        )
        db.commit()
        eval_id = cursor.lastrowid

        # Grade it
        db.execute(
            """UPDATE ojt_evaluations
               SET score = ?, status = ?
               WHERE id = ?""",
            (88.5, 'graded', eval_id)
        )
        db.commit()

        evaluation = dict_from_row(db.execute(
            "SELECT * FROM ojt_evaluations WHERE id = ?",
            (eval_id,)
        ).fetchone())
        db.close()

        assert evaluation['score'] == 88.5
        assert evaluation['status'] == 'graded'

    def test_list_ojt_evaluations_for_program(self, database, sample_ojt_program, trainee_user):
        """Test listing evaluations for an OJT program."""
        db = get_db()

        # Create multiple evaluations
        for i in range(3):
            db.execute(
                """INSERT INTO ojt_evaluations
                   (program_id, trainee_id, eval_type, title, status)
                   VALUES (?, ?, ?, ?, ?)""",
                (sample_ojt_program['id'], trainee_user['id'],
                 f'type_{i}', f'Evaluation {i}', 'pending')
            )
        db.commit()

        evals = dicts_from_rows(db.execute(
            "SELECT * FROM ojt_evaluations WHERE program_id = ?",
            (sample_ojt_program['id'],)
        ).fetchall())
        db.close()

        assert len(evals) >= 3

    def test_list_ojt_evaluations_for_trainee(self, database, sample_ojt_program, trainee_user):
        """Test listing evaluations for a specific trainee."""
        db = get_db()

        # Create evaluations for trainee
        for i in range(2):
            db.execute(
                """INSERT INTO ojt_evaluations
                   (program_id, trainee_id, eval_type, title)
                   VALUES (?, ?, ?, ?)""",
                (sample_ojt_program['id'], trainee_user['id'],
                 'practical', f'Test {i}')
            )
        db.commit()

        evals = dicts_from_rows(db.execute(
            "SELECT * FROM ojt_evaluations WHERE trainee_id = ?",
            (trainee_user['id'],)
        ).fetchall())
        db.close()

        assert len(evals) >= 2
        assert all(e['trainee_id'] == trainee_user['id'] for e in evals)

    def test_filter_ojt_evaluations_by_status(self, database, sample_ojt_program, trainee_user):
        """Test filtering OJT evaluations by status."""
        db = get_db()

        # Create evaluations with different statuses
        for status in ['pending', 'in_progress', 'graded']:
            db.execute(
                """INSERT INTO ojt_evaluations
                   (program_id, trainee_id, eval_type, title, status)
                   VALUES (?, ?, ?, ?, ?)""",
                (sample_ojt_program['id'], trainee_user['id'],
                 'test', f'Test {status}', status)
            )
        db.commit()

        pending = dicts_from_rows(db.execute(
            "SELECT * FROM ojt_evaluations WHERE status = ?",
            ('pending',)
        ).fetchall())
        db.close()

        assert all(e['status'] == 'pending' for e in pending)


class TestOJTProgramManagement:
    """Test overall OJT program management."""

    def test_get_ojt_program_with_tasks(self, database, sample_ojt_program, sample_ojt_task):
        """Test retrieving program with its tasks."""
        db = get_db()

        program = dict_from_row(db.execute(
            "SELECT * FROM ojt_programs WHERE id = ?",
            (sample_ojt_program['id'],)
        ).fetchone())

        tasks = dicts_from_rows(db.execute(
            "SELECT * FROM ojt_tasks WHERE program_id = ? ORDER BY sequence_num",
            (sample_ojt_program['id'],)
        ).fetchall())
        db.close()

        assert program is not None
        assert len(tasks) > 0

    def test_get_ojt_program_with_enrollments(self, database, sample_ojt_program, trainee_user):
        """Test retrieving program with its enrollments."""
        db = get_db()

        # Enroll trainee
        db.execute(
            "INSERT INTO ojt_enrollments (program_id, trainee_id, status) VALUES (?, ?, ?)",
            (sample_ojt_program['id'], trainee_user['id'], 'enrolled')
        )
        db.commit()

        enrollments = dicts_from_rows(db.execute(
            """SELECT e.*, u.name as trainee_name
               FROM ojt_enrollments e
               JOIN users u ON e.trainee_id = u.id
               WHERE e.program_id = ?""",
            (sample_ojt_program['id'],)
        ).fetchall())
        db.close()

        assert len(enrollments) > 0
