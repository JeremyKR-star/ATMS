"""
ATMS Database Module
Dual-backend support: SQLite (local dev) and PostgreSQL (production via Neon).
Auto-converts SQL syntax between backends.
"""
import sqlite3
import os
import re
import datetime
import decimal

DATABASE_URL = os.environ.get("DATABASE_URL")
DB_PATH = os.path.join(os.path.dirname(__file__), "data", "atms.db")
IS_POSTGRES = DATABASE_URL is not None

if IS_POSTGRES:
    import psycopg2
    import psycopg2.extras
    print("[DB] Using PostgreSQL backend (Neon)")
else:
    print("[DB] Using SQLite backend (local dev fallback)")


def _sanitize_value(val):
    """Convert non-JSON-serializable types to strings."""
    if isinstance(val, (datetime.datetime, datetime.date, datetime.time)):
        return val.isoformat()
    if isinstance(val, datetime.timedelta):
        total = int(val.total_seconds())
        hours, remainder = divmod(total, 3600)
        minutes, seconds = divmod(remainder, 60)
        return f"{hours}:{minutes:02d}:{seconds:02d}"
    if isinstance(val, decimal.Decimal):
        return float(val)
    if isinstance(val, memoryview):
        return bytes(val).decode("utf-8", errors="replace")
    return val


def _sanitize_dict(d):
    """Sanitize all values in a dict for JSON serialization."""
    return {k: _sanitize_value(v) for k, v in d.items()}


class DictRow:
    """A row that supports both dict-style (row['col']) and index-style (row[0]) access."""

    def __init__(self, data):
        if isinstance(data, dict):
            self._dict = _sanitize_dict(data)
        else:
            # sqlite3.Row or similar
            self._dict = _sanitize_dict(dict(data))
        self._keys = list(self._dict.keys())
        self._values = list(self._dict.values())

    def __getitem__(self, key):
        if isinstance(key, int):
            return self._values[key]
        return self._dict[key]

    def get(self, key, default=None):
        return self._dict.get(key, default)

    def keys(self):
        return self._keys

    def values(self):
        return self._values

    def items(self):
        return self._dict.items()

    def __contains__(self, key):
        return key in self._dict

    def __repr__(self):
        return repr(self._dict)

    def __iter__(self):
        return iter(self._keys)

    def __len__(self):
        return len(self._keys)


class DictCursor:
    """Wrapper for SQLite cursor to provide dict-like access and lastrowid conversion."""

    def __init__(self, cursor, backend="sqlite"):
        self._cursor = cursor
        self._backend = backend
        self.lastrowid = None
        self._last_query = None
        self._is_insert = False

    def _convert_placeholders(self, query):
        """Convert SQLite '?' placeholders to PostgreSQL '%s'."""
        if self._backend == "postgres":
            return query.replace("?", "%s")
        return query

    def _convert_sql_functions(self, query):
        """Convert SQLite-specific SQL to PostgreSQL equivalents."""
        if self._backend == "postgres":
            # GROUP_CONCAT -> STRING_AGG
            query = re.sub(
                r"GROUP_CONCAT\(DISTINCT\s+([^)]+)\)",
                r"STRING_AGG(DISTINCT \1, ',')",
                query,
                flags=re.IGNORECASE
            )
            query = re.sub(
                r"GROUP_CONCAT\(([^)]+)\)",
                r"STRING_AGG(\1, ',')",
                query,
                flags=re.IGNORECASE
            )

            # DATE('now') -> CURRENT_DATE
            query = re.sub(r"DATE\('now'\)", "CURRENT_DATE", query, flags=re.IGNORECASE)

            # DATE('now', '+N days/months/years') -> CURRENT_DATE + INTERVAL 'N days/months/years'
            query = re.sub(
                r"DATE\('now',\s*'([+-])(\d+)\s+(days?|months?|years?)'\)",
                lambda m: f"CURRENT_DATE {m.group(1)} INTERVAL '{m.group(2)} {m.group(3)}'",
                query,
                flags=re.IGNORECASE
            )

            # DATE('now', '-N months') -> CURRENT_DATE - INTERVAL 'N months'
            # (already handled above)

            # strftime('%Y-%m', col) -> TO_CHAR(col, 'YYYY-MM')
            query = re.sub(
                r"strftime\('%Y-%m',\s*(\w+)\)",
                r"TO_CHAR(\1, 'YYYY-MM')",
                query,
                flags=re.IGNORECASE
            )

            # DATE(col) -> col::date (for audit_routes DATE(created_at))
            query = re.sub(
                r"DATE\((\w+)\)",
                r"\1::date",
                query,
                flags=re.IGNORECASE
            )

            # INSERT OR IGNORE -> INSERT ... ON CONFLICT DO NOTHING
            if re.search(r"INSERT\s+OR\s+IGNORE\s+INTO", query, re.IGNORECASE):
                query = re.sub(
                    r"INSERT\s+OR\s+IGNORE\s+INTO",
                    "INSERT INTO",
                    query,
                    flags=re.IGNORECASE
                )
                # Append ON CONFLICT DO NOTHING at the end
                if not query.rstrip().endswith(";"):
                    query = query.rstrip() + " ON CONFLICT DO NOTHING"
                else:
                    query = query.rstrip()[:-1] + " ON CONFLICT DO NOTHING;"

            # INSERT OR REPLACE -> INSERT ... ON CONFLICT ... DO UPDATE
            # In SQLite, OR REPLACE replaces on primary key or unique constraint violation.
            # In PostgreSQL, we need to specify which columns to update.
            # Extract the column names from the INSERT clause to update all of them.
            if re.search(r"INSERT\s+OR\s+REPLACE\s+INTO", query, re.IGNORECASE):
                # Extract column list from INSERT statement
                columns_match = re.search(r"INSERT\s+OR\s+REPLACE\s+INTO\s+\w+\s*\(([^)]+)\)", query, re.IGNORECASE)
                columns = []
                if columns_match:
                    columns = [col.strip() for col in columns_match.group(1).split(",")]

                # Replace INSERT OR REPLACE with INSERT
                query = re.sub(
                    r"INSERT\s+OR\s+REPLACE\s+INTO",
                    "INSERT INTO",
                    query,
                    flags=re.IGNORECASE
                )

                # Build UPDATE clause for all non-id columns
                if columns:
                    update_parts = [f"{col} = EXCLUDED.{col}" for col in columns if col.strip().lower() != "id"]
                    update_clause = ", ".join(update_parts)
                    if update_clause:
                        if not query.rstrip().endswith(";"):
                            query = query.rstrip() + f" ON CONFLICT DO UPDATE SET {update_clause}"
                        else:
                            query = query.rstrip()[:-1] + f" ON CONFLICT DO UPDATE SET {update_clause};"

        return query

    def execute(self, query, params=None):
        """Execute a query with automatic placeholder and SQL conversion."""
        query = self._convert_sql_functions(query)
        query = self._convert_placeholders(query)

        # Track if this is an INSERT to handle lastrowid
        self._is_insert = bool(re.search(r"^\s*INSERT", query, re.IGNORECASE))
        self._last_query = query

        # For PostgreSQL INSERT, append RETURNING id if not already present
        if self._is_insert and self._backend == "postgres" and "RETURNING" not in query.upper():
            query = query.rstrip()
            if query.endswith(";"):
                query = query[:-1] + " RETURNING id;"
            else:
                query = query + " RETURNING id"

        if params:
            self._cursor.execute(query, params)
        else:
            self._cursor.execute(query)

        # Store lastrowid for PostgreSQL
        if self._is_insert and self._backend == "postgres":
            try:
                result = self._cursor.fetchone()
                if result:
                    self.lastrowid = result[0] if isinstance(result, tuple) else result.get("id")
            except Exception:
                self.lastrowid = None
        else:
            self.lastrowid = self._cursor.lastrowid

        return self

    def executemany(self, query, params_list):
        """Execute multiple queries with automatic conversion."""
        query = self._convert_sql_functions(query)
        query = self._convert_placeholders(query)

        self._cursor.executemany(query, params_list)
        return self

    def fetchone(self):
        """Fetch one row as DictRow (supports both row['col'] and row[0])."""
        row = self._cursor.fetchone()
        if row is None:
            return None
        return DictRow(row)

    def fetchall(self):
        """Fetch all rows as list of DictRow."""
        rows = self._cursor.fetchall()
        return [DictRow(r) for r in rows]

    def fetchone_raw(self):
        """Fetch one row without conversion (for internal use)."""
        return self._cursor.fetchone()

    def fetchall_raw(self):
        """Fetch all rows without conversion (for internal use)."""
        return self._cursor.fetchall()

    def __getattr__(self, name):
        """Delegate unknown attributes to the underlying cursor."""
        return getattr(self._cursor, name)


class PostgreSQLConnection:
    """Wrapper for psycopg2 connection to provide sqlite3-like interface."""

    def __init__(self, conn):
        self._conn = conn

    def cursor(self):
        """Get a cursor that behaves like sqlite3."""
        pg_cursor = self._conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        return DictCursor(pg_cursor, backend="postgres")

    def execute(self, query, params=None):
        """Execute directly on connection (like sqlite3)."""
        cursor = self.cursor()
        if params:
            cursor.execute(query, params)
        else:
            cursor.execute(query)
        return cursor

    def commit(self):
        """Commit the transaction."""
        self._conn.commit()

    def close(self):
        """Close the connection."""
        self._conn.close()

    def __getattr__(self, name):
        """Delegate unknown attributes to the underlying connection."""
        return getattr(self._conn, name)


class SQLiteConnection:
    """Wrapper for sqlite3 connection to provide uniform interface."""

    def __init__(self, conn):
        self._conn = conn
        self._conn.row_factory = sqlite3.Row

    def cursor(self):
        """Get a cursor that behaves like sqlite3 but with conversion support."""
        sqlite_cursor = self._conn.cursor()
        return DictCursor(sqlite_cursor, backend="sqlite")

    def execute(self, query, params=None):
        """Execute directly on connection (like sqlite3)."""
        cursor = self.cursor()
        if params:
            cursor.execute(query, params)
        else:
            cursor.execute(query)
        return cursor

    def commit(self):
        """Commit the transaction."""
        self._conn.commit()

    def close(self):
        """Close the connection."""
        self._conn.close()

    def __getattr__(self, name):
        """Delegate unknown attributes to the underlying connection."""
        return getattr(self._conn, name)


def get_db():
    """Get a database connection that works with both SQLite and PostgreSQL."""
    if IS_POSTGRES:
        try:
            pg_conn = psycopg2.connect(DATABASE_URL)
            return PostgreSQLConnection(pg_conn)
        except psycopg2.Error as e:
            raise Exception(f"PostgreSQL connection failed: {e}")
    else:
        # SQLite fallback
        sqlite_conn = sqlite3.connect(DB_PATH)
        sqlite_conn.execute("PRAGMA journal_mode=WAL")
        sqlite_conn.execute("PRAGMA foreign_keys=ON")
        return SQLiteConnection(sqlite_conn)


def dict_from_row(row):
    """Convert row to dict (works with DictRow, sqlite3.Row and psycopg2 dicts)."""
    if row is None:
        return None
    if isinstance(row, dict):
        return row
    if isinstance(row, DictRow):
        return row._dict
    return dict(row)


def dicts_from_rows(rows):
    """Convert list of rows to list of dicts (works with both backends)."""
    return [dict_from_row(r) for r in rows]


def init_db():
    """Create all tables if they don't exist. Auto-converts schema for PostgreSQL."""
    conn = get_db()
    c = conn.cursor()

    # Determine backend for schema conversion
    backend = "postgres" if IS_POSTGRES else "sqlite"

    def get_pk_syntax():
        """Return PRIMARY KEY syntax for current backend."""
        return "SERIAL PRIMARY KEY" if backend == "postgres" else "INTEGER PRIMARY KEY AUTOINCREMENT"

    # ── Users ──
    c.execute(f"""
        CREATE TABLE IF NOT EXISTS users (
            id {get_pk_syntax()},
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
            language TEXT NOT NULL DEFAULT 'ko',
            status TEXT DEFAULT 'active' CHECK(status IN ('active','inactive','suspended')),
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # ── Courses ──
    c.execute(f"""
        CREATE TABLE IF NOT EXISTS courses (
            id {get_pk_syntax()},
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
    c.execute(f"""
        CREATE TABLE IF NOT EXISTS course_modules (
            id {get_pk_syntax()},
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
    c.execute(f"""
        CREATE TABLE IF NOT EXISTS course_instructors (
            id {get_pk_syntax()},
            course_id INTEGER NOT NULL REFERENCES courses(id) ON DELETE CASCADE,
            instructor_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            role TEXT DEFAULT 'lead' CHECK(role IN ('lead','assistant')),
            assigned_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(course_id, instructor_id)
        )
    """)

    # ── Enrollments (trainee <-> course) ──
    c.execute(f"""
        CREATE TABLE IF NOT EXISTS enrollments (
            id {get_pk_syntax()},
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
    c.execute(f"""
        CREATE TABLE IF NOT EXISTS schedules (
            id {get_pk_syntax()},
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
    c.execute(f"""
        CREATE TABLE IF NOT EXISTS evaluations (
            id {get_pk_syntax()},
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
    c.execute(f"""
        CREATE TABLE IF NOT EXISTS content (
            id {get_pk_syntax()},
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
    c.execute(f"""
        CREATE TABLE IF NOT EXISTS ojt_programs (
            id {get_pk_syntax()},
            name TEXT NOT NULL,
            description TEXT,
            duration_weeks INTEGER,
            aircraft_type TEXT,
            status TEXT DEFAULT 'planned' CHECK(status IN ('planned','active','completed')),
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # ── OJT Tasks ──
    c.execute(f"""
        CREATE TABLE IF NOT EXISTS ojt_tasks (
            id {get_pk_syntax()},
            program_id INTEGER NOT NULL REFERENCES ojt_programs(id) ON DELETE CASCADE,
            name TEXT NOT NULL,
            description TEXT,
            order_num INTEGER DEFAULT 0,
            required_hours REAL,
            criteria TEXT
        )
    """)

    # ── OJT Enrollments ──
    c.execute(f"""
        CREATE TABLE IF NOT EXISTS ojt_enrollments (
            id {get_pk_syntax()},
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
    c.execute(f"""
        CREATE TABLE IF NOT EXISTS ojt_evaluations (
            id {get_pk_syntax()},
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
    c.execute(f"""
        CREATE TABLE IF NOT EXISTS attendance (
            id {get_pk_syntax()},
            schedule_id INTEGER NOT NULL REFERENCES schedules(id) ON DELETE CASCADE,
            trainee_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            status TEXT DEFAULT 'present' CHECK(status IN ('present','absent','late','excused')),
            check_in_time TEXT,
            notes TEXT,
            UNIQUE(schedule_id, trainee_id)
        )
    """)

    # ── Notifications ──
    c.execute(f"""
        CREATE TABLE IF NOT EXISTS notifications (
            id {get_pk_syntax()},
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
    c.execute(f"""
        CREATE TABLE IF NOT EXISTS pilot_nationalities (
            id {get_pk_syntax()},
            code TEXT UNIQUE NOT NULL,
            label_ko TEXT NOT NULL,
            sort_order INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # ── Mechanics personal records ──
    c.execute(f"""
        CREATE TABLE IF NOT EXISTS mechanics (
            id {get_pk_syntax()},
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
    c.execute(f"""
        CREATE TABLE IF NOT EXISTS mechanic_ojt_items (
            id {get_pk_syntax()},
            category TEXT NOT NULL,
            item_no TEXT NOT NULL,
            subject TEXT NOT NULL,
            description TEXT,
            sort_order INTEGER DEFAULT 0
        )
    """)

    # ── Mechanic OJT completion records ──
    c.execute(f"""
        CREATE TABLE IF NOT EXISTS mechanic_ojt_records (
            id {get_pk_syntax()},
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
    c.execute(f"""
        CREATE TABLE IF NOT EXISTS mechanic_certifications (
            id {get_pk_syntax()},
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

    # ── Pilots ──
    c.execute(f"""
        CREATE TABLE IF NOT EXISTS pilots (
            id {get_pk_syntax()},
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

    # ── Migrate: Malaysian -> Malaysia ──
    try:
        if backend == "postgres":
            c._cursor.execute("SAVEPOINT migrate_nat")
            c.execute("UPDATE pilots SET nationality=%s WHERE nationality=%s", ("Malaysia", "Malaysian"))
        else:
            c.execute("UPDATE pilots SET nationality=? WHERE nationality=?", ("Malaysia", "Malaysian"))
    except Exception:
        if backend == "postgres":
            c._cursor.execute("ROLLBACK TO SAVEPOINT migrate_nat")

    # ── Pilot Training Courses (SIM + Flight syllabus) ──
    c.execute(f"""
        CREATE TABLE IF NOT EXISTS pilot_courses (
            id {get_pk_syntax()},
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
    c.execute(f"""
        CREATE TABLE IF NOT EXISTS pilot_training (
            id {get_pk_syntax()},
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
    c.execute(f"""
        CREATE TABLE IF NOT EXISTS weekly_uploads (
            id {get_pk_syntax()},
            filename TEXT NOT NULL,
            original_filename TEXT NOT NULL,
            uploaded_by TEXT,
            report_date TEXT,
            file_size INTEGER DEFAULT 0,
            row_count INTEGER DEFAULT 0,
            notes TEXT,
            file_data BYTEA,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # Migration: add file_data column if missing
    try:
        c.execute("SELECT file_data FROM weekly_uploads LIMIT 0")
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass
        try:
            c.execute("ALTER TABLE weekly_uploads ADD COLUMN file_data BYTEA")
            conn.commit()
        except Exception:
            try:
                conn.rollback()
            except Exception:
                pass

    # ── Weekly Report Data (parsed from Excel) ──
    c.execute(f"""
        CREATE TABLE IF NOT EXISTS weekly_report_data (
            id {get_pk_syntax()},
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
    c.execute(f"""
        CREATE TABLE IF NOT EXISTS surveys (
            id {get_pk_syntax()},
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
    c.execute(f"""
        CREATE TABLE IF NOT EXISTS audit_log (
            id {get_pk_syntax()},
            user_name TEXT,
            action TEXT NOT NULL,
            target_type TEXT NOT NULL,
            target_id INTEGER,
            details TEXT,
            ip_address TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # ── Access Logs (visitor tracking) ──
    c.execute(f"""
        CREATE TABLE IF NOT EXISTS access_logs (
            id {get_pk_syntax()},
            ip_address TEXT NOT NULL,
            method TEXT NOT NULL,
            path TEXT NOT NULL,
            status_code INTEGER,
            user_agent TEXT,
            user_id INTEGER,
            user_name TEXT,
            response_time_ms REAL,
            country TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # ══════════════════════════════════════════════════════════
    # NEW TABLES FOR ATMS FULL SPEC (PDF Requirements)
    # ══════════════════════════════════════════════════════════

    # ── OJT Sub-tasks (hierarchical under ojt_tasks) ──
    c.execute(f"""
        CREATE TABLE IF NOT EXISTS ojt_sub_tasks (
            id {get_pk_syntax()},
            task_id INTEGER NOT NULL REFERENCES ojt_tasks(id) ON DELETE CASCADE,
            name TEXT NOT NULL,
            description TEXT,
            order_num INTEGER DEFAULT 0,
            required_hours REAL,
            criteria TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # ── OJT Leaders (assigned to programs) ──
    c.execute(f"""
        CREATE TABLE IF NOT EXISTS ojt_leaders (
            id {get_pk_syntax()},
            program_id INTEGER NOT NULL REFERENCES ojt_programs(id) ON DELETE CASCADE,
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            role TEXT DEFAULT 'leader' CHECK(role IN ('leader','dedicated_admin')),
            assigned_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(program_id, user_id)
        )
    """)

    # ── OJT Program Admins (per-program admin assignments) ──
    c.execute(f"""
        CREATE TABLE IF NOT EXISTS ojt_program_admins (
            id {get_pk_syntax()},
            program_id INTEGER NOT NULL REFERENCES ojt_programs(id) ON DELETE CASCADE,
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            admin_role TEXT DEFAULT 'dedicated_admin',
            permissions TEXT DEFAULT 'read,write',
            assigned_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(program_id, user_id)
        )
    """)

    # ── OJT Training Specification (TS) documents ──
    c.execute(f"""
        CREATE TABLE IF NOT EXISTS ojt_training_specs (
            id {get_pk_syntax()},
            program_id INTEGER NOT NULL REFERENCES ojt_programs(id) ON DELETE CASCADE,
            title TEXT NOT NULL,
            description TEXT,
            content TEXT,
            file_path TEXT,
            version TEXT DEFAULT '1.0',
            status TEXT DEFAULT 'draft' CHECK(status IN ('draft','active','archived')),
            created_by INTEGER REFERENCES users(id),
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # ── OJT Evaluation Specification (ES) documents ──
    c.execute(f"""
        CREATE TABLE IF NOT EXISTS ojt_eval_specs (
            id {get_pk_syntax()},
            program_id INTEGER NOT NULL REFERENCES ojt_programs(id) ON DELETE CASCADE,
            title TEXT NOT NULL,
            description TEXT,
            content TEXT,
            file_path TEXT,
            version TEXT DEFAULT '1.0',
            status TEXT DEFAULT 'draft' CHECK(status IN ('draft','active','archived')),
            created_by INTEGER REFERENCES users(id),
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # ── OJT Pre-assignments (사전과제) ──
    c.execute(f"""
        CREATE TABLE IF NOT EXISTS ojt_pre_assignments (
            id {get_pk_syntax()},
            program_id INTEGER NOT NULL REFERENCES ojt_programs(id) ON DELETE CASCADE,
            title TEXT NOT NULL,
            description TEXT,
            file_path TEXT,
            due_date TEXT,
            created_by INTEGER REFERENCES users(id),
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # ── OJT Venues (훈련장소) ──
    c.execute(f"""
        CREATE TABLE IF NOT EXISTS ojt_venues (
            id {get_pk_syntax()},
            name TEXT NOT NULL,
            location TEXT,
            capacity INTEGER,
            equipment TEXT,
            notes TEXT,
            status TEXT DEFAULT 'active' CHECK(status IN ('active','inactive')),
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # ── OJT Announcements (공지사항) ──
    c.execute(f"""
        CREATE TABLE IF NOT EXISTS ojt_announcements (
            id {get_pk_syntax()},
            program_id INTEGER REFERENCES ojt_programs(id) ON DELETE CASCADE,
            title TEXT NOT NULL,
            content TEXT,
            priority TEXT DEFAULT 'normal' CHECK(priority IN ('low','normal','high','urgent')),
            created_by INTEGER REFERENCES users(id),
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # ── OJT Survey Templates ──
    c.execute(f"""
        CREATE TABLE IF NOT EXISTS ojt_survey_templates (
            id {get_pk_syntax()},
            program_id INTEGER REFERENCES ojt_programs(id) ON DELETE CASCADE,
            title TEXT NOT NULL,
            description TEXT,
            start_date TEXT,
            end_date TEXT,
            status TEXT DEFAULT 'draft' CHECK(status IN ('draft','active','closed','forced_close')),
            created_by INTEGER REFERENCES users(id),
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # ── OJT Survey Items (questions) ──
    c.execute(f"""
        CREATE TABLE IF NOT EXISTS ojt_survey_items (
            id {get_pk_syntax()},
            template_id INTEGER NOT NULL REFERENCES ojt_survey_templates(id) ON DELETE CASCADE,
            question TEXT NOT NULL,
            question_type TEXT DEFAULT 'rating' CHECK(question_type IN ('rating','text','multiple_choice','yes_no')),
            options TEXT,
            order_num INTEGER DEFAULT 0,
            required INTEGER DEFAULT 1
        )
    """)

    # ── OJT Survey Responses ──
    c.execute(f"""
        CREATE TABLE IF NOT EXISTS ojt_survey_responses (
            id {get_pk_syntax()},
            template_id INTEGER NOT NULL REFERENCES ojt_survey_templates(id) ON DELETE CASCADE,
            item_id INTEGER NOT NULL REFERENCES ojt_survey_items(id) ON DELETE CASCADE,
            trainee_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            response TEXT,
            rating REAL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # ── Career Development Roadmap (경력개발 로드맵) ──
    c.execute(f"""
        CREATE TABLE IF NOT EXISTS career_roadmap (
            id {get_pk_syntax()},
            level INTEGER NOT NULL CHECK(level IN (3,5,7)),
            level_name TEXT NOT NULL,
            title TEXT NOT NULL,
            description TEXT,
            requirements TEXT,
            duration_months INTEGER,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # ── Career Roadmap Tasks ──
    c.execute(f"""
        CREATE TABLE IF NOT EXISTS career_roadmap_tasks (
            id {get_pk_syntax()},
            roadmap_id INTEGER NOT NULL REFERENCES career_roadmap(id) ON DELETE CASCADE,
            name TEXT NOT NULL,
            description TEXT,
            order_num INTEGER DEFAULT 0,
            required INTEGER DEFAULT 1
        )
    """)

    # ── Career Roadmap Sub-tasks ──
    c.execute(f"""
        CREATE TABLE IF NOT EXISTS career_roadmap_sub_tasks (
            id {get_pk_syntax()},
            task_id INTEGER NOT NULL REFERENCES career_roadmap_tasks(id) ON DELETE CASCADE,
            name TEXT NOT NULL,
            description TEXT,
            order_num INTEGER DEFAULT 0
        )
    """)

    # ── Career Roadmap Trainee Progress ──
    c.execute(f"""
        CREATE TABLE IF NOT EXISTS career_roadmap_progress (
            id {get_pk_syntax()},
            trainee_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            roadmap_id INTEGER NOT NULL REFERENCES career_roadmap(id) ON DELETE CASCADE,
            task_id INTEGER REFERENCES career_roadmap_tasks(id) ON DELETE CASCADE,
            sub_task_id INTEGER REFERENCES career_roadmap_sub_tasks(id) ON DELETE CASCADE,
            status TEXT DEFAULT 'pending' CHECK(status IN ('pending','in_progress','completed')),
            completed_at TIMESTAMP,
            notes TEXT,
            UNIQUE(trainee_id, roadmap_id, task_id, sub_task_id)
        )
    """)

    # ── Wrap-up Tests (강사가 생성하는 Daily 테스트) ──
    c.execute(f"""
        CREATE TABLE IF NOT EXISTS wrap_up_tests (
            id {get_pk_syntax()},
            course_id INTEGER NOT NULL REFERENCES courses(id) ON DELETE CASCADE,
            module_id INTEGER REFERENCES course_modules(id) ON DELETE SET NULL,
            instructor_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            title TEXT NOT NULL,
            description TEXT,
            test_date TEXT,
            time_limit_minutes INTEGER DEFAULT 30,
            status TEXT DEFAULT 'draft' CHECK(status IN ('draft','active','closed')),
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # ── Wrap-up Test Questions ──
    c.execute(f"""
        CREATE TABLE IF NOT EXISTS wrap_up_questions (
            id {get_pk_syntax()},
            test_id INTEGER NOT NULL REFERENCES wrap_up_tests(id) ON DELETE CASCADE,
            question TEXT NOT NULL,
            question_type TEXT DEFAULT 'multiple_choice' CHECK(question_type IN ('multiple_choice','true_false','short_answer','essay')),
            options TEXT,
            correct_answer TEXT,
            points REAL DEFAULT 10,
            order_num INTEGER DEFAULT 0
        )
    """)

    # ── Wrap-up Test Responses (trainee answers) ──
    c.execute(f"""
        CREATE TABLE IF NOT EXISTS wrap_up_responses (
            id {get_pk_syntax()},
            test_id INTEGER NOT NULL REFERENCES wrap_up_tests(id) ON DELETE CASCADE,
            trainee_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            question_id INTEGER NOT NULL REFERENCES wrap_up_questions(id) ON DELETE CASCADE,
            answer TEXT,
            is_correct INTEGER DEFAULT 0,
            score REAL DEFAULT 0,
            feedback TEXT,
            submitted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(test_id, trainee_id, question_id)
        )
    """)

    # ── Wrap-up Test Results (aggregate per trainee per test) ──
    c.execute(f"""
        CREATE TABLE IF NOT EXISTS wrap_up_results (
            id {get_pk_syntax()},
            test_id INTEGER NOT NULL REFERENCES wrap_up_tests(id) ON DELETE CASCADE,
            trainee_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            total_score REAL DEFAULT 0,
            max_score REAL DEFAULT 0,
            percentage REAL DEFAULT 0,
            status TEXT DEFAULT 'pending' CHECK(status IN ('pending','submitted','graded')),
            instructor_feedback TEXT,
            submitted_at TIMESTAMP,
            graded_at TIMESTAMP,
            UNIQUE(test_id, trainee_id)
        )
    """)

    # ── Assignment Submissions (과제 제출) ──
    c.execute(f"""
        CREATE TABLE IF NOT EXISTS assignment_submissions (
            id {get_pk_syntax()},
            content_id INTEGER NOT NULL REFERENCES content(id) ON DELETE CASCADE,
            trainee_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            file_path TEXT,
            submission_text TEXT,
            score REAL,
            max_score REAL DEFAULT 100,
            feedback TEXT,
            status TEXT DEFAULT 'pending' CHECK(status IN ('pending','submitted','graded','returned','resubmit')),
            submitted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            graded_at TIMESTAMP,
            graded_by INTEGER REFERENCES users(id),
            UNIQUE(content_id, trainee_id)
        )
    """)

    # ── Digital Signatures (JPG 서명) ──
    c.execute(f"""
        CREATE TABLE IF NOT EXISTS digital_signatures (
            id {get_pk_syntax()},
            trainee_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            course_id INTEGER NOT NULL REFERENCES courses(id) ON DELETE CASCADE,
            module_id INTEGER REFERENCES course_modules(id),
            signature_data TEXT,
            signature_path TEXT,
            purpose TEXT DEFAULT 'course_completion',
            status TEXT DEFAULT 'pending' CHECK(status IN ('pending','signed','verified','rejected')),
            signed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            verified_by INTEGER REFERENCES users(id),
            verified_at TIMESTAMP
        )
    """)

    # ── Counseling Records (상담기록) ──
    c.execute(f"""
        CREATE TABLE IF NOT EXISTS counseling_records (
            id {get_pk_syntax()},
            trainee_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            counselor_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            course_id INTEGER REFERENCES courses(id) ON DELETE SET NULL,
            topic TEXT NOT NULL,
            content TEXT,
            action_items TEXT,
            counseling_date TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # ── OJT Training Schedules (훈련일정) ──
    c.execute(f"""
        CREATE TABLE IF NOT EXISTS ojt_schedules (
            id {get_pk_syntax()},
            program_id INTEGER NOT NULL REFERENCES ojt_programs(id) ON DELETE CASCADE,
            title TEXT NOT NULL,
            schedule_date TEXT NOT NULL,
            start_time TEXT,
            end_time TEXT,
            venue_id INTEGER REFERENCES ojt_venues(id),
            instructor_id INTEGER REFERENCES users(id),
            notes TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # ── User Extended Profile (추가 필드 - 별도 테이블) ──
    c.execute(f"""
        CREATE TABLE IF NOT EXISTS user_profiles (
            id {get_pk_syntax()},
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            major TEXT,
            career_history TEXT,
            qualifications TEXT,
            pre_training TEXT,
            visa_info TEXT,
            visa_expiry TEXT,
            medical_check TEXT,
            medical_check_date TEXT,
            military_number TEXT,
            payroll TEXT,
            gender TEXT,
            date_of_birth TEXT,
            organization TEXT,
            job_experience TEXT,
            specialty_skill TEXT,
            equipment_issued TEXT,
            rnr TEXT,
            bio_data TEXT,
            training_system TEXT,
            UNIQUE(user_id)
        )
    """)

    # ── OJT Training Results (훈련결과) ──
    c.execute(f"""
        CREATE TABLE IF NOT EXISTS ojt_training_results (
            id {get_pk_syntax()},
            enrollment_id INTEGER NOT NULL REFERENCES ojt_enrollments(id) ON DELETE CASCADE,
            task_id INTEGER NOT NULL REFERENCES ojt_tasks(id) ON DELETE CASCADE,
            attendance_status TEXT DEFAULT 'present' CHECK(attendance_status IN ('present','absent','late','excused')),
            completion_status TEXT DEFAULT 'pending' CHECK(completion_status IN ('pending','in_progress','completed','failed')),
            approval_status TEXT DEFAULT 'draft' CHECK(approval_status IN ('draft','submitted','leader_approved','admin_approved','rejected')),
            submitted_at TIMESTAMP,
            leader_approved_by INTEGER REFERENCES users(id) ON DELETE SET NULL,
            leader_approved_at TIMESTAMP,
            admin_approved_by INTEGER REFERENCES users(id) ON DELETE SET NULL,
            admin_approved_at TIMESTAMP,
            score REAL,
            notes TEXT,
            result_date TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # ── OJT Evaluation Templates (평가 템플릿) ──
    c.execute(f"""
        CREATE TABLE IF NOT EXISTS ojt_eval_templates (
            id {get_pk_syntax()},
            program_id INTEGER REFERENCES ojt_programs(id) ON DELETE CASCADE,
            name TEXT NOT NULL,
            description TEXT,
            criteria TEXT,
            max_score REAL DEFAULT 100,
            template_data TEXT,
            created_by INTEGER REFERENCES users(id),
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # ── Notification Preferences ──
    c.execute(f"""
        CREATE TABLE IF NOT EXISTS notification_preferences (
            id {get_pk_syntax()},
            user_id INTEGER NOT NULL,
            notification_type TEXT NOT NULL DEFAULT 'all',
            muted INTEGER NOT NULL DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(user_id, notification_type)
        )
    """)

    # ── Attendance QR Tokens ──
    c.execute(f"""
        CREATE TABLE IF NOT EXISTS attendance_qr_tokens (
            id {get_pk_syntax()},
            schedule_id INTEGER NOT NULL,
            token TEXT NOT NULL UNIQUE,
            expires_at TIMESTAMP NOT NULL,
            created_by INTEGER NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # ── Work Schedules (근무 스케줄) ──
    c.execute(f"""
        CREATE TABLE IF NOT EXISTS work_schedules (
            id {get_pk_syntax()},
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            title TEXT DEFAULT '',
            schedule_date DATE NOT NULL,
            start_time TEXT NOT NULL DEFAULT '09:00',
            end_time TEXT NOT NULL DEFAULT '18:00',
            schedule_type TEXT NOT NULL DEFAULT 'work' CHECK(schedule_type IN ('work','leave','holiday','overtime','duty','half_day')),
            notes TEXT DEFAULT '',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # ══════════════════════════════════════════════════════════
    # PERFORMANCE INDEXES
    # ══════════════════════════════════════════════════════════

    # ── User Indexes ──
    c.execute("CREATE INDEX IF NOT EXISTS idx_users_email ON users(email)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_users_role ON users(role)")

    # ── Enrollment Indexes ──
    c.execute("CREATE INDEX IF NOT EXISTS idx_enrollments_user_id ON enrollments(trainee_id)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_enrollments_course_id ON enrollments(course_id)")

    # ── Schedule Indexes ──
    c.execute("CREATE INDEX IF NOT EXISTS idx_schedules_course_id ON schedules(course_id)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_schedules_date ON schedules(schedule_date)")

    # ── Attendance Indexes ──
    c.execute("CREATE INDEX IF NOT EXISTS idx_attendance_schedule_id ON attendance(schedule_id)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_attendance_user_id ON attendance(trainee_id)")

    # ── OJT Enrollment Indexes ──
    c.execute("CREATE INDEX IF NOT EXISTS idx_ojt_enrollments_user_id ON ojt_enrollments(trainee_id)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_ojt_enrollments_program_id ON ojt_enrollments(program_id)")

    # ── Notification Indexes ──
    c.execute("CREATE INDEX IF NOT EXISTS idx_notifications_user_id ON notifications(user_id)")

    # ── Audit Log Indexes ──
    c.execute("CREATE INDEX IF NOT EXISTS idx_audit_log_user_id ON audit_log(user_name)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_audit_log_created_at ON audit_log(created_at)")

    # ── Access Log Indexes ──
    c.execute("CREATE INDEX IF NOT EXISTS idx_access_logs_user_id ON access_logs(user_id)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_access_logs_accessed_at ON access_logs(created_at)")

    # ── Content Indexes ──
    c.execute("CREATE INDEX IF NOT EXISTS idx_content_course_id ON content(course_id)")

    # ── Evaluation Indexes ──
    c.execute("CREATE INDEX IF NOT EXISTS idx_evaluations_course_id ON evaluations(course_id)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_evaluations_trainee_id ON evaluations(trainee_id)")

    # ── OJT Task Indexes ──
    c.execute("CREATE INDEX IF NOT EXISTS idx_ojt_tasks_program_id ON ojt_tasks(program_id)")

    # ── OJT Evaluation Indexes ──
    c.execute("CREATE INDEX IF NOT EXISTS idx_ojt_evaluations_enrollment_id ON ojt_evaluations(enrollment_id)")

    # ── Work Schedule Indexes ──
    c.execute("CREATE INDEX IF NOT EXISTS idx_work_schedules_user_id ON work_schedules(user_id)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_work_schedules_date ON work_schedules(schedule_date)")

    # ══════════════════════════════════════════════════════════
    # SCHEMA MIGRATIONS (ADD MISSING COLUMNS)
    # ══════════════════════════════════════════════════════════

    # ── Add submission-related columns to ojt_pre_assignments ──
    try:
        c.execute("ALTER TABLE ojt_pre_assignments ADD COLUMN status TEXT DEFAULT 'pending' CHECK(status IN ('pending','submitted','reviewed'))")
    except Exception:
        pass  # Column already exists

    try:
        c.execute("ALTER TABLE ojt_pre_assignments ADD COLUMN submission_text TEXT")
    except Exception:
        pass  # Column already exists

    try:
        c.execute("ALTER TABLE ojt_pre_assignments ADD COLUMN file_url TEXT")
    except Exception:
        pass  # Column already exists

    try:
        c.execute("ALTER TABLE ojt_pre_assignments ADD COLUMN submitted_at TIMESTAMP")
    except Exception:
        pass  # Column already exists

    # ── Add transfer-related columns to evaluations ──
    try:
        c.execute("ALTER TABLE evaluations ADD COLUMN transferred_at TIMESTAMP")
    except Exception:
        pass  # Column already exists

    try:
        c.execute("ALTER TABLE evaluations ADD COLUMN transferred_by INTEGER REFERENCES users(id) ON DELETE SET NULL")
    except Exception:
        pass  # Column already exists

    conn.commit()
    conn.close()
    backend_name = "PostgreSQL" if IS_POSTGRES else "SQLite"
    print(f"[DB] Database initialized successfully on {backend_name}.")


if __name__ == "__main__":
    init_db()
    print("[DB] Schema created at:", DB_PATH)
