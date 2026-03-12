"""
ATMS Database Module
SQLite database setup, schema creation, and helper functions.
"""
import sqlite3
import os

DB_PATH = os.path.join(os.path.dirname(__file__), "data", "atms.db")


def get_db():
    """Get a database connection with row_factory for dict-like access."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def dict_from_row(row):
    """Convert sqlite3.Row to dict."""
    if row is None:
        return None
    return dict(row)


def dicts_from_rows(rows):
    """Convert list of sqlite3.Row to list of dicts."""
    return [dict(r) for r in rows]


def init_db():
    """Create all tables if they don't exist."""
    conn = get_db()
    c = conn.cursor()

    # ── Users ──
    c.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            employee_id TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            name TEXT NOT NULL,
            email TEXT,
            phone TEXT,
            birthday TEXT,
            photo_url TEXT,
            role TEXT NOT NULL CHECK(role IN ('admin','instructor','trainee','ojt_admin','manager','staff','customer')),
            title TEXT,
            department TEXT,
            specialty TEXT,
            bio TEXT,
            status TEXT DEFAULT 'active' CHECK(status IN ('active','inactive','suspended')),
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # ── Courses ──
    c.execute("""
        CREATE TABLE IF NOT EXISTS courses (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            code TEXT UNIQUE NOT NULL,
            name TEXT NOT NULL,
            type TEXT NOT NULL CHECK(type IN ('TT','OJT')),
            description TEXT,
            duration_weeks INTEGER,
            max_trainees INTEGER DEFAULT 20,
            aircraft_type TEXT,
            status TEXT DEFAULT 'planned' CHECK(status IN ('planned','active','completed','cancelled')),
            start_date TEXT,
            end_date TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # ── Course Modules ──
    c.execute("""
        CREATE TABLE IF NOT EXISTS course_modules (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            course_id INTEGER NOT NULL REFERENCES courses(id) ON DELETE CASCADE,
            name TEXT NOT NULL,
            description TEXT,
            order_num INTEGER DEFAULT 0,
            duration_hours REAL,
            module_type TEXT DEFAULT 'theory' CHECK(module_type IN ('theory','practical','assessment','wrap_up')),
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # ── Course Assignments (instructor <-> course) ──
    c.execute("""
        CREATE TABLE IF NOT EXISTS course_instructors (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            course_id INTEGER NOT NULL REFERENCES courses(id) ON DELETE CASCADE,
            instructor_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            role TEXT DEFAULT 'lead' CHECK(role IN ('lead','assistant')),
            assigned_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(course_id, instructor_id)
        )
    """)

    # ── Enrollments (trainee <-> course) ──
    c.execute("""
        CREATE TABLE IF NOT EXISTS enrollments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            course_id INTEGER NOT NULL REFERENCES courses(id) ON DELETE CASCADE,
            trainee_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            status TEXT DEFAULT 'enrolled' CHECK(status IN ('enrolled','in_progress','completed','dropped','failed')),
            progress REAL DEFAULT 0,
            final_score REAL,
            enrolled_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            completed_at TIMESTAMP,
            UNIQUE(course_id, trainee_id)
        )
    """)

    # ── Schedule ──
    c.execute("""
        CREATE TABLE IF NOT EXISTS schedules (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            course_id INTEGER REFERENCES courses(id) ON DELETE CASCADE,
            instructor_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
            module_id INTEGER REFERENCES course_modules(id) ON DELETE SET NULL,
            title TEXT NOT NULL,
            schedule_date TEXT NOT NULL,
            start_time TEXT NOT NULL,
            end_time TEXT NOT NULL,
            room TEXT,
            schedule_type TEXT DEFAULT 'lecture' CHECK(schedule_type IN ('lecture','practical','assessment','ojt','meeting','other')),
            notes TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # ── Evaluations ──
    c.execute("""
        CREATE TABLE IF NOT EXISTS evaluations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            course_id INTEGER NOT NULL REFERENCES courses(id) ON DELETE CASCADE,
            module_id INTEGER REFERENCES course_modules(id) ON DELETE SET NULL,
            trainee_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            evaluator_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
            eval_type TEXT NOT NULL CHECK(eval_type IN ('quiz','exam','practical','assignment','wrap_up','ojt_task')),
            title TEXT NOT NULL,
            score REAL,
            max_score REAL DEFAULT 100,
            grade TEXT,
            feedback TEXT,
            status TEXT DEFAULT 'pending' CHECK(status IN ('pending','submitted','graded','returned')),
            due_date TEXT,
            submitted_at TIMESTAMP,
            graded_at TIMESTAMP,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # ── Content / Learning Materials ──
    c.execute("""
        CREATE TABLE IF NOT EXISTS content (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            course_id INTEGER REFERENCES courses(id) ON DELETE CASCADE,
            module_id INTEGER REFERENCES course_modules(id) ON DELETE SET NULL,
            title TEXT NOT NULL,
            content_type TEXT NOT NULL CHECK(content_type IN ('ebook','assessment','assignment','lesson_plan','supplementary','video','document')),
            description TEXT,
            file_path TEXT,
            uploaded_by INTEGER REFERENCES users(id) ON DELETE SET NULL,
            status TEXT DEFAULT 'active' CHECK(status IN ('active','draft','archived')),
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # ── OJT Programs ──
    c.execute("""
        CREATE TABLE IF NOT EXISTS ojt_programs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            description TEXT,
            duration_weeks INTEGER,
            aircraft_type TEXT,
            status TEXT DEFAULT 'planned' CHECK(status IN ('planned','active','completed')),
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # ── OJT Tasks ──
    c.execute("""
        CREATE TABLE IF NOT EXISTS ojt_tasks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            program_id INTEGER NOT NULL REFERENCES ojt_programs(id) ON DELETE CASCADE,
            name TEXT NOT NULL,
            description TEXT,
            order_num INTEGER DEFAULT 0,
            required_hours REAL,
            criteria TEXT
        )
    """)

    # ── OJT Enrollments ──
    c.execute("""
        CREATE TABLE IF NOT EXISTS ojt_enrollments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            program_id INTEGER NOT NULL REFERENCES ojt_programs(id) ON DELETE CASCADE,
            trainee_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            trainer_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
            status TEXT DEFAULT 'enrolled' CHECK(status IN ('enrolled','in_progress','completed','failed')),
            progress REAL DEFAULT 0,
            enrolled_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            completed_at TIMESTAMP,
            UNIQUE(program_id, trainee_id)
        )
    """)

    # ── OJT Evaluations ──
    c.execute("""
        CREATE TABLE IF NOT EXISTS ojt_evaluations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            enrollment_id INTEGER NOT NULL REFERENCES ojt_enrollments(id) ON DELETE CASCADE,
            task_id INTEGER NOT NULL REFERENCES ojt_tasks(id) ON DELETE CASCADE,
            evaluator_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
            score REAL,
            max_score REAL DEFAULT 100,
            status TEXT DEFAULT 'pending' CHECK(status IN ('pending','pass','fail','needs_improvement')),
            feedback TEXT,
            eval_date TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # ── Attendance ──
    c.execute("""
        CREATE TABLE IF NOT EXISTS attendance (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            schedule_id INTEGER NOT NULL REFERENCES schedules(id) ON DELETE CASCADE,
            trainee_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            status TEXT DEFAULT 'present' CHECK(status IN ('present','absent','late','excused')),
            check_in_time TEXT,
            notes TEXT,
            UNIQUE(schedule_id, trainee_id)
        )
    """)

    # ── Notifications ──
    c.execute("""
        CREATE TABLE IF NOT EXISTS notifications (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            title TEXT NOT NULL,
            message TEXT,
            notification_type TEXT DEFAULT 'info' CHECK(notification_type IN ('info','warning','success','danger')),
            is_read INTEGER DEFAULT 0,
            link TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # ── Pilot Nationalities ──
    c.execute("""
        CREATE TABLE IF NOT EXISTS pilot_nationalities (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            code TEXT UNIQUE NOT NULL,
            label_ko TEXT NOT NULL,
            sort_order INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # ── Mechanics personal records ──
    c.execute("""
        CREATE TABLE IF NOT EXISTS mechanics (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            short_name TEXT NOT NULL,
            rank TEXT DEFAULT 'Staff',
            employee_id TEXT,
            specialty TEXT DEFAULT 'Airframe',
            team TEXT,
            date_of_birth TEXT,
            certification_date TEXT,
            phone TEXT,
            email TEXT,
            photo_url TEXT,
            notes TEXT,
            sort_order INTEGER DEFAULT 0,
            status TEXT DEFAULT 'active' CHECK(status IN ('active','inactive','graduated','suspended')),
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # ── Mechanic OJT items (checklist) ──
    c.execute("""
        CREATE TABLE IF NOT EXISTS mechanic_ojt_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            category TEXT NOT NULL,
            item_no TEXT NOT NULL,
            subject TEXT NOT NULL,
            description TEXT,
            sort_order INTEGER DEFAULT 0
        )
    """)

    # ── Mechanic OJT completion records ──
    c.execute("""
        CREATE TABLE IF NOT EXISTS mechanic_ojt_records (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            mechanic_id INTEGER NOT NULL REFERENCES mechanics(id) ON DELETE CASCADE,
            ojt_item_id INTEGER NOT NULL REFERENCES mechanic_ojt_items(id) ON DELETE CASCADE,
            completed_date TEXT,
            evaluator TEXT,
            score TEXT DEFAULT 'P' CHECK(score IN ('P','F','N/A')),
            notes TEXT,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(mechanic_id, ojt_item_id)
        )
    """)

    # ── Mechanic certifications ──
    c.execute("""
        CREATE TABLE IF NOT EXISTS mechanic_certifications (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            mechanic_id INTEGER NOT NULL REFERENCES mechanics(id) ON DELETE CASCADE,
            cert_name TEXT NOT NULL,
            cert_type TEXT DEFAULT 'license',
            issued_date TEXT,
            expiry_date TEXT,
            issuer TEXT,
            status TEXT DEFAULT 'active' CHECK(status IN ('active','expired','revoked','pending')),
            notes TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # ── Migrate: Malaysian -> Malaysia ──
    try:
        c.execute("UPDATE pilots SET nationality='Malaysia' WHERE nationality='Malaysian'")
    except Exception:
        pass  # table may not exist yet on fresh DB

    # ── Pilots ──
    c.execute("""
        CREATE TABLE IF NOT EXISTS pilots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            short_name TEXT NOT NULL,
            rank TEXT DEFAULT 'Major',
            service_number TEXT,
            callsign TEXT,
            nationality TEXT DEFAULT 'Malaysian',
            squadron TEXT,
            date_of_birth TEXT,
            course_class TEXT,
            training_start_date TEXT,
            training_end_date TEXT,
            phone TEXT,
            email TEXT,
            photo_url TEXT,
            notes TEXT,
            sort_order INTEGER DEFAULT 0,
            status TEXT DEFAULT 'active' CHECK(status IN ('active','inactive','graduated','suspended')),
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # ── Pilot Training Courses (SIM + Flight syllabus) ──
    c.execute("""
        CREATE TABLE IF NOT EXISTS pilot_courses (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            course_no TEXT NOT NULL,
            category TEXT NOT NULL CHECK(category IN ('sim','flight')),
            seq_no INTEGER,
            subject TEXT NOT NULL,
            contents TEXT,
            duration TEXT DEFAULT '1:00',
            sort_order INTEGER DEFAULT 0
        )
    """)

    # ── Pilot Training Records (individual completion) ──
    c.execute("""
        CREATE TABLE IF NOT EXISTS pilot_training (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            pilot_id INTEGER NOT NULL REFERENCES pilots(id) ON DELETE CASCADE,
            course_id INTEGER NOT NULL REFERENCES pilot_courses(id) ON DELETE CASCADE,
            completed_date TEXT,
            completed_time TEXT,
            notes TEXT,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(pilot_id, course_id)
        )
    """)

    # ── Weekly Report Uploads ──
    c.execute("""
        CREATE TABLE IF NOT EXISTS weekly_uploads (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            filename TEXT NOT NULL,
            original_filename TEXT NOT NULL,
            uploaded_by TEXT,
            report_date TEXT,
            file_size INTEGER DEFAULT 0,
            row_count INTEGER DEFAULT 0,
            notes TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # ── Weekly Report Data (parsed from Excel) ──
    c.execute("""
        CREATE TABLE IF NOT EXISTS weekly_report_data (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            upload_id INTEGER NOT NULL REFERENCES weekly_uploads(id) ON DELETE CASCADE,
            pilot_id INTEGER REFERENCES pilots(id) ON DELETE SET NULL,
            pilot_name TEXT,
            flt_plan INTEGER DEFAULT 0,
            flt_done INTEGER DEFAULT 0,
            flt_remain INTEGER DEFAULT 0,
            sim_plan INTEGER DEFAULT 0,
            sim_done INTEGER DEFAULT 0,
            sim_remain INTEGER DEFAULT 0,
            remarks TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # ── Surveys ──
    c.execute("""
        CREATE TABLE IF NOT EXISTS surveys (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            course_id INTEGER REFERENCES courses(id) ON DELETE CASCADE,
            trainee_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            overall_rating REAL,
            instructor_rating REAL,
            content_rating REAL,
            facility_rating REAL,
            comments TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)


    # ── Audit Log ──
    c.execute("""
        CREATE TABLE IF NOT EXISTS audit_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_name TEXT,
            action TEXT NOT NULL,
            target_type TEXT NOT NULL,
            target_id INTEGER,
            details TEXT,
            ip_address TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.commit()
    conn.close()
    print("[DB] Database initialized successfully.")


if __name__ == "__main__":
    init_db()
    print("[DB] Schema created at:", DB_PATH)
