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
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

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
    conn.commit()
    conn.close()
    backend_name = "PostgreSQL" if IS_POSTGRES else "SQLite"
    print(f"[DB] Database initialized successfully on {backend_name}.")


if __name__ == "__main__":
    init_db()
    print("[DB] Schema created at:", DB_PATH)
