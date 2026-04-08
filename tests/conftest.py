"""
ATMS Test Fixtures and Configuration
Sets up in-memory SQLite database, test client, and seed data for testing.
"""
import os
import sys
import sqlite3
import json
import tempfile
import pytest
import tornado.web
import tornado.testing
from unittest.mock import patch

# Add parent directory to path so we can import ATMS modules
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from database import init_db, get_db, IS_POSTGRES
from auth import generate_token, hash_password
from server import make_app


@pytest.fixture(scope="session")
def database():
    """
    Session-scoped fixture: Creates an in-memory SQLite database
    and initializes the schema once for all tests.
    """
    # Force SQLite backend for testing
    with patch('database.IS_POSTGRES', False):
        with patch('database.DATABASE_URL', None):
            # Create in-memory database
            db_conn = sqlite3.connect(':memory:')
            db_conn.row_factory = sqlite3.Row

            # Initialize schema (from init_db)
            _init_test_db(db_conn)

            yield db_conn

            db_conn.close()


def _init_test_db(db_conn):
    """Initialize database schema for testing."""
    schema_sql = """
    -- Users table
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        employee_id TEXT UNIQUE NOT NULL,
        password_hash TEXT NOT NULL,
        name TEXT NOT NULL,
        role TEXT DEFAULT 'trainee',
        title TEXT,
        department TEXT,
        email TEXT,
        phone TEXT,
        birthday TEXT,
        specialty TEXT,
        bio TEXT,
        photo_url TEXT,
        status TEXT DEFAULT 'active',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );

    -- Courses table
    CREATE TABLE IF NOT EXISTS courses (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        code TEXT UNIQUE NOT NULL,
        name TEXT NOT NULL,
        type TEXT,
        description TEXT,
        duration_weeks INTEGER,
        max_trainees INTEGER DEFAULT 20,
        aircraft_type TEXT,
        status TEXT DEFAULT 'planned',
        start_date TEXT,
        end_date TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );

    -- Course modules
    CREATE TABLE IF NOT EXISTS course_modules (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        course_id INTEGER NOT NULL,
        name TEXT NOT NULL,
        description TEXT,
        order_num INTEGER,
        duration_hours REAL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (course_id) REFERENCES courses(id)
    );

    -- Course instructors
    CREATE TABLE IF NOT EXISTS course_instructors (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        course_id INTEGER NOT NULL,
        instructor_id INTEGER NOT NULL,
        role TEXT DEFAULT 'instructor',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(course_id, instructor_id),
        FOREIGN KEY (course_id) REFERENCES courses(id),
        FOREIGN KEY (instructor_id) REFERENCES users(id)
    );

    -- Enrollments
    CREATE TABLE IF NOT EXISTS enrollments (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        course_id INTEGER NOT NULL,
        trainee_id INTEGER NOT NULL,
        status TEXT DEFAULT 'enrolled',
        enrollment_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        completion_date TEXT,
        final_score REAL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(course_id, trainee_id),
        FOREIGN KEY (course_id) REFERENCES courses(id),
        FOREIGN KEY (trainee_id) REFERENCES users(id)
    );

    -- Schedules
    CREATE TABLE IF NOT EXISTS schedules (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        course_id INTEGER,
        module_id INTEGER,
        instructor_id INTEGER,
        schedule_date TEXT NOT NULL,
        start_time TEXT NOT NULL,
        end_time TEXT NOT NULL,
        room TEXT,
        location TEXT,
        status TEXT DEFAULT 'scheduled',
        notes TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (course_id) REFERENCES courses(id),
        FOREIGN KEY (module_id) REFERENCES course_modules(id),
        FOREIGN KEY (instructor_id) REFERENCES users(id)
    );

    -- Attendance
    CREATE TABLE IF NOT EXISTS attendance (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        schedule_id INTEGER NOT NULL,
        trainee_id INTEGER NOT NULL,
        status TEXT DEFAULT 'absent',
        recorded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        recorded_by INTEGER,
        UNIQUE(schedule_id, trainee_id),
        FOREIGN KEY (schedule_id) REFERENCES schedules(id),
        FOREIGN KEY (trainee_id) REFERENCES users(id),
        FOREIGN KEY (recorded_by) REFERENCES users(id)
    );

    -- Evaluations
    CREATE TABLE IF NOT EXISTS evaluations (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        course_id INTEGER NOT NULL,
        module_id INTEGER,
        trainee_id INTEGER NOT NULL,
        evaluator_id INTEGER,
        eval_type TEXT,
        title TEXT NOT NULL,
        description TEXT,
        max_score REAL DEFAULT 100,
        score REAL,
        due_date TEXT,
        status TEXT DEFAULT 'pending',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (course_id) REFERENCES courses(id),
        FOREIGN KEY (module_id) REFERENCES course_modules(id),
        FOREIGN KEY (trainee_id) REFERENCES users(id),
        FOREIGN KEY (evaluator_id) REFERENCES users(id)
    );

    -- Evaluation submissions
    CREATE TABLE IF NOT EXISTS evaluation_submissions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        evaluation_id INTEGER NOT NULL,
        trainee_id INTEGER NOT NULL,
        submission_text TEXT,
        submitted_at TIMESTAMP,
        graded_by INTEGER,
        grade REAL,
        graded_at TIMESTAMP,
        feedback TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (evaluation_id) REFERENCES evaluations(id),
        FOREIGN KEY (trainee_id) REFERENCES users(id),
        FOREIGN KEY (graded_by) REFERENCES users(id)
    );

    -- OJT Programs
    CREATE TABLE IF NOT EXISTS ojt_programs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        code TEXT UNIQUE NOT NULL,
        name TEXT NOT NULL,
        description TEXT,
        duration_days INTEGER,
        status TEXT DEFAULT 'draft',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );

    -- OJT Tasks
    CREATE TABLE IF NOT EXISTS ojt_tasks (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        program_id INTEGER NOT NULL,
        title TEXT NOT NULL,
        description TEXT,
        sequence_num INTEGER,
        estimated_hours REAL,
        status TEXT DEFAULT 'pending',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (program_id) REFERENCES ojt_programs(id)
    );

    -- OJT Enrollments
    CREATE TABLE IF NOT EXISTS ojt_enrollments (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        program_id INTEGER NOT NULL,
        trainee_id INTEGER NOT NULL,
        status TEXT DEFAULT 'enrolled',
        enrollment_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        completion_date TEXT,
        UNIQUE(program_id, trainee_id),
        FOREIGN KEY (program_id) REFERENCES ojt_programs(id),
        FOREIGN KEY (trainee_id) REFERENCES users(id)
    );

    -- OJT Evaluations
    CREATE TABLE IF NOT EXISTS ojt_evaluations (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        program_id INTEGER NOT NULL,
        trainee_id INTEGER NOT NULL,
        evaluator_id INTEGER,
        eval_type TEXT,
        title TEXT NOT NULL,
        max_score REAL DEFAULT 100,
        score REAL,
        status TEXT DEFAULT 'pending',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (program_id) REFERENCES ojt_programs(id),
        FOREIGN KEY (trainee_id) REFERENCES users(id),
        FOREIGN KEY (evaluator_id) REFERENCES users(id)
    );

    -- Content
    CREATE TABLE IF NOT EXISTS content (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        title TEXT NOT NULL,
        description TEXT,
        content_type TEXT,
        url TEXT,
        course_id INTEGER,
        module_id INTEGER,
        created_by INTEGER,
        status TEXT DEFAULT 'draft',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (course_id) REFERENCES courses(id),
        FOREIGN KEY (module_id) REFERENCES course_modules(id),
        FOREIGN KEY (created_by) REFERENCES users(id)
    );

    -- Notifications
    CREATE TABLE IF NOT EXISTS notifications (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        title TEXT NOT NULL,
        message TEXT,
        type TEXT DEFAULT 'info',
        is_read INTEGER DEFAULT 0,
        related_id INTEGER,
        related_type TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (user_id) REFERENCES users(id)
    );

    -- Access logs
    CREATE TABLE IF NOT EXISTS access_logs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        ip_address TEXT,
        method TEXT,
        path TEXT,
        status_code INTEGER,
        user_agent TEXT,
        user_id INTEGER,
        user_name TEXT,
        response_time_ms REAL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (user_id) REFERENCES users(id)
    );
    """

    db_conn.executescript(schema_sql)
    db_conn.commit()


@pytest.fixture
def app(database):
    """Create a test Tornado application with in-memory database."""
    with patch('database.get_db') as mock_get_db:
        def patched_get_db():
            # Return a wrapper around the test database
            return DatabaseWrapper(database)

        mock_get_db.side_effect = patched_get_db

        # Create app
        test_app = make_app()
        yield test_app


class DatabaseWrapper:
    """Wraps SQLite connection to match the database module interface."""

    def __init__(self, conn):
        self.conn = conn

    def execute(self, query, params=None):
        """Execute query and return cursor."""
        try:
            cursor = self.conn.cursor()
            if params:
                cursor.execute(query, params)
            else:
                cursor.execute(query)
            return RowWrapper(cursor)
        except Exception as e:
            raise e

    def commit(self):
        self.conn.commit()

    def close(self):
        pass  # Don't close the session-scoped connection


class RowWrapper:
    """Wraps SQLite cursor to match database module interface."""

    def __init__(self, cursor):
        self.cursor = cursor
        self.lastrowid = cursor.lastrowid

    def fetchone(self):
        row = self.cursor.fetchone()
        if row is None:
            return None
        return dict(row) if row else None

    def fetchall(self):
        rows = self.cursor.fetchall()
        return [dict(row) for row in rows]


@pytest.fixture
def client(app, database):
    """Create a test HTTP client for the Tornado app."""
    class TestClient:
        def __init__(self, app, db):
            self.app = app
            self.db = db
            self.tokens = {}

        def post(self, path, data=None, token=None):
            """Make a POST request."""
            import json
            body = json.dumps(data or {})

            request = tornado.httputil.HTTPServerRequest(
                method='POST',
                uri=path,
                body=body
            )
            request.headers['Content-Type'] = 'application/json'
            if token:
                request.headers['Authorization'] = f'Bearer {token}'

            handler = self._get_handler(request)
            handler.post(*self._extract_args(path))
            return self._get_response(handler)

        def get(self, path, params=None, token=None):
            """Make a GET request."""
            query = '&'.join(f'{k}={v}' for k, v in (params or {}).items())
            full_path = f'{path}?{query}' if query else path

            request = tornado.httputil.HTTPServerRequest(
                method='GET',
                uri=full_path
            )
            if token:
                request.headers['Authorization'] = f'Bearer {token}'

            handler = self._get_handler(request)
            handler.get(*self._extract_args(path))
            return self._get_response(handler)

        def _get_handler(self, request):
            """Create a handler for the request."""
            handler = tornado.web.RequestHandler(self.app, request)
            handler.request = request
            return handler

        def _extract_args(self, path):
            """Extract path arguments from URL."""
            import re
            # Simple extraction - would need to match against routes
            match = re.findall(r'/(\d+)', path)
            return tuple(match) if match else ()

        def _get_response(self, handler):
            """Extract response from handler."""
            return {
                'status': handler.get_status(),
                'body': getattr(handler, '_write_buffer', [])
            }

    return TestClient(app, database)


@pytest.fixture
def admin_user(database):
    """Create an admin user for testing."""
    db = DatabaseWrapper(database)
    user_data = {
        'employee_id': 'admin001',
        'password_hash': hash_password('Admin@123'),
        'name': 'Admin User',
        'role': 'admin',
        'email': 'admin@test.com',
        'status': 'active'
    }

    cursor = database.execute(
        """INSERT INTO users
           (employee_id, password_hash, name, role, email, status)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (user_data['employee_id'], user_data['password_hash'],
         user_data['name'], user_data['role'],
         user_data['email'], user_data['status'])
    )
    database.commit()
    user_id = cursor.lastrowid

    return {
        'id': user_id,
        'employee_id': user_data['employee_id'],
        'name': user_data['name'],
        'role': 'admin',
        'token': generate_token(user_id, 'admin', user_data['name'])
    }


@pytest.fixture
def instructor_user(database):
    """Create an instructor user for testing."""
    user_data = {
        'employee_id': 'instructor001',
        'password_hash': hash_password('Instructor@123'),
        'name': 'Instructor User',
        'role': 'instructor',
        'email': 'instructor@test.com',
        'status': 'active'
    }

    cursor = database.execute(
        """INSERT INTO users
           (employee_id, password_hash, name, role, email, status)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (user_data['employee_id'], user_data['password_hash'],
         user_data['name'], user_data['role'],
         user_data['email'], user_data['status'])
    )
    database.commit()
    user_id = cursor.lastrowid

    return {
        'id': user_id,
        'employee_id': user_data['employee_id'],
        'name': user_data['name'],
        'role': 'instructor',
        'token': generate_token(user_id, 'instructor', user_data['name'])
    }


@pytest.fixture
def trainee_user(database):
    """Create a trainee user for testing."""
    user_data = {
        'employee_id': 'trainee001',
        'password_hash': hash_password('Trainee@123'),
        'name': 'Trainee User',
        'role': 'trainee',
        'email': 'trainee@test.com',
        'status': 'active'
    }

    cursor = database.execute(
        """INSERT INTO users
           (employee_id, password_hash, name, role, email, status)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (user_data['employee_id'], user_data['password_hash'],
         user_data['name'], user_data['role'],
         user_data['email'], user_data['status'])
    )
    database.commit()
    user_id = cursor.lastrowid

    return {
        'id': user_id,
        'employee_id': user_data['employee_id'],
        'name': user_data['name'],
        'role': 'trainee',
        'token': generate_token(user_id, 'trainee', user_data['name'])
    }


@pytest.fixture
def sample_course(database, instructor_user):
    """Create a sample course for testing."""
    cursor = database.execute(
        """INSERT INTO courses
           (code, name, type, description, duration_weeks, max_trainees, status, start_date, end_date)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        ('COURSE001', 'Sample Course', 'theory', 'A sample training course',
         4, 20, 'active', '2026-04-15', '2026-05-15')
    )
    database.commit()
    course_id = cursor.lastrowid

    # Add instructor
    database.execute(
        """INSERT INTO course_instructors (course_id, instructor_id, role)
           VALUES (?, ?, ?)""",
        (course_id, instructor_user['id'], 'lead_instructor')
    )
    database.commit()

    return {
        'id': course_id,
        'code': 'COURSE001',
        'name': 'Sample Course',
        'instructor_id': instructor_user['id']
    }


@pytest.fixture
def sample_module(database, sample_course):
    """Create a sample course module for testing."""
    cursor = database.execute(
        """INSERT INTO course_modules
           (course_id, name, description, order_num, duration_hours)
           VALUES (?, ?, ?, ?, ?)""",
        (sample_course['id'], 'Module 1', 'First training module', 1, 8.0)
    )
    database.commit()

    return {
        'id': cursor.lastrowid,
        'course_id': sample_course['id'],
        'name': 'Module 1'
    }


@pytest.fixture
def sample_schedule(database, sample_course, instructor_user):
    """Create a sample schedule for testing."""
    cursor = database.execute(
        """INSERT INTO schedules
           (course_id, instructor_id, schedule_date, start_time, end_time, room, status)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (sample_course['id'], instructor_user['id'], '2026-04-15',
         '09:00', '12:00', 'Room A', 'scheduled')
    )
    database.commit()

    return {
        'id': cursor.lastrowid,
        'course_id': sample_course['id'],
        'instructor_id': instructor_user['id'],
        'schedule_date': '2026-04-15'
    }


@pytest.fixture
def sample_ojt_program(database):
    """Create a sample OJT program for testing."""
    cursor = database.execute(
        """INSERT INTO ojt_programs
           (code, name, description, duration_days, status)
           VALUES (?, ?, ?, ?, ?)""",
        ('OJT001', 'Maintenance OJT', 'Aircraft maintenance training', 30, 'active')
    )
    database.commit()

    return {
        'id': cursor.lastrowid,
        'code': 'OJT001',
        'name': 'Maintenance OJT'
    }


@pytest.fixture
def sample_ojt_task(database, sample_ojt_program):
    """Create a sample OJT task for testing."""
    cursor = database.execute(
        """INSERT INTO ojt_tasks
           (program_id, title, description, sequence_num, estimated_hours, status)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (sample_ojt_program['id'], 'Engine Inspection', 'Learn to inspect aircraft engines',
         1, 16.0, 'pending')
    )
    database.commit()

    return {
        'id': cursor.lastrowid,
        'program_id': sample_ojt_program['id'],
        'title': 'Engine Inspection'
    }
