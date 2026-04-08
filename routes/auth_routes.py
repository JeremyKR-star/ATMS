"""Authentication Routes: Login, Register, Profile"""
import os
import json
import tornado.web
from database import get_db, dict_from_row
from auth import (hash_password, check_password, generate_token, require_auth, get_current_user,
                  check_rate_limit, record_login_attempt, clear_login_attempts)


def _log_audit(handler, action, target_type, target_id=None, details=''):
    """Lazy import wrapper to avoid circular imports."""
    try:
        from routes.audit_routes import log_audit
        log_audit(handler, action, target_type, target_id, details)
    except Exception:
        pass

# CORS origin: restrict in production, allow all in dev
ALLOWED_ORIGIN = os.environ.get("ATMS_CORS_ORIGIN", "*")


class BaseHandler(tornado.web.RequestHandler):
    """Base handler with JSON helpers and security headers."""

    def set_default_headers(self):
        self.set_header("Content-Type", "application/json")
        # CORS
        origin = self.request.headers.get("Origin", "")
        if ALLOWED_ORIGIN == "*":
            self.set_header("Access-Control-Allow-Origin", "*")
        elif origin and origin in ALLOWED_ORIGIN.split(","):
            self.set_header("Access-Control-Allow-Origin", origin)
        self.set_header("Access-Control-Allow-Methods", "GET,POST,PUT,DELETE,OPTIONS")
        self.set_header("Access-Control-Allow-Headers", "Content-Type,Authorization")
        # Security headers
        self.set_header("X-Content-Type-Options", "nosniff")
        self.set_header("X-Frame-Options", "DENY")
        self.set_header("X-XSS-Protection", "1; mode=block")
        self.set_header("Referrer-Policy", "strict-origin-when-cross-origin")
        self.set_header("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
        # Cache control for GET requests on list endpoints
        if self.request.method == "GET":
            self.set_header("Cache-Control", "public, max-age=60")

    def options(self, *args):
        self.set_status(204)
        self.finish()

    def get_json_body(self):
        try:
            return json.loads(self.request.body)
        except (json.JSONDecodeError, TypeError):
            return {}

    def success(self, data=None, message="Success"):
        self.write({"success": True, "message": message, "data": data})

    def error(self, message, status=400):
        self.set_status(status)
        self.write({"success": False, "error": message})


class LoginHandler(BaseHandler):
    def post(self):
        body = self.get_json_body()
        employee_id = body.get("employee_id", "").strip()
        password = body.get("password", "")

        if not employee_id or not password:
            return self.error("Employee ID and password are required")

        # Rate limiting check (by IP and employee_id)
        client_ip = self.request.headers.get("X-Forwarded-For", "").split(",")[0].strip() or self.request.remote_ip
        rate_key = f"login:{client_ip}:{employee_id}"
        allowed, remaining = check_rate_limit(rate_key)
        if not allowed:
            return self.error(f"Too many login attempts. Please try again in {remaining} seconds.", 429)

        db = get_db()
        user = dict_from_row(db.execute(
            "SELECT * FROM users WHERE employee_id = ? AND status = 'active'",
            (employee_id,)
        ).fetchone())
        db.close()

        if not user or not check_password(password, user["password_hash"]):
            record_login_attempt(rate_key)
            return self.error("Invalid employee ID or password", 401)

        # Successful login - clear rate limit
        clear_login_attempts(rate_key)
        _log_audit(self, 'login', 'user', user["id"])

        token = generate_token(user["id"], user["role"], user["name"])
        self.success({
            "token": token,
            "user": {
                "id": user["id"],
                "employee_id": user["employee_id"],
                "name": user["name"],
                "role": user["role"],
                "title": user["title"],
                "department": user["department"],
                "email": user["email"],
                "photo_url": user["photo_url"],
                "language": user.get("language", "ko"),
            }
        }, "Login successful")


class RegisterHandler(BaseHandler):
    @require_auth(roles=["admin", "ojt_admin"])
    def post(self):
        body = self.get_json_body()
        employee_id = body.get("employee_id", "").strip()
        password = body.get("password", "")
        name = body.get("name", "").strip()
        role = body.get("role", "trainee")
        title = body.get("title", "")
        department = body.get("department", "")
        email = body.get("email", "")
        phone = body.get("phone", "")
        birthday = body.get("birthday", "")
        specialty = body.get("specialty", "")

        if not employee_id or not password or not name:
            return self.error("Employee ID, password, and name are required")

        if len(password) < 8:
            return self.error("Password must be at least 8 characters")
        if not any(c.isdigit() for c in password):
            return self.error("Password must contain at least one number")
        if not any(c.isalpha() for c in password):
            return self.error("Password must contain at least one letter")

        valid_roles = ["admin", "instructor", "trainee", "ojt_admin", "manager", "staff", "customer"]
        if role not in valid_roles:
            return self.error(f"Invalid role. Must be one of: {', '.join(valid_roles)}")

        db = get_db()
        existing = db.execute("SELECT id FROM users WHERE employee_id = ?", (employee_id,)).fetchone()
        if existing:
            db.close()
            return self.error("Employee ID already exists")

        # Input length validation
        if len(employee_id) > 50 or len(name) > 100 or len(email) > 150:
            db.close()
            return self.error("Input exceeds maximum allowed length")

        try:
            cur = db.execute(
                """INSERT INTO users (employee_id, password_hash, name, role, title, department, email, phone, birthday, specialty)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (employee_id, hash_password(password), name, role, title, department, email, phone, birthday, specialty)
            )
            db.commit()
            user_id = cur.lastrowid
            db.close()
            _log_audit(self, 'register', 'user', user_id, {"employee_id": employee_id, "name": name, "role": role})
            self.success({"id": user_id, "employee_id": employee_id, "name": name, "role": role}, "User registered successfully")
        except Exception:
            db.close()
            self.error("Registration failed. Please try again.", 500)


class VerifyIdHandler(BaseHandler):
    """Check if an employee ID is valid and available."""
    def post(self):
        body = self.get_json_body()
        employee_id = body.get("employee_id", "").strip()
        if not employee_id or len(employee_id) < 4:
            return self.error("Employee ID must be at least 4 characters")

        db = get_db()
        existing = db.execute("SELECT id FROM users WHERE employee_id = ?", (employee_id,)).fetchone()
        db.close()

        if existing:
            return self.error("Employee ID already in use")

        self.success({"employee_id": employee_id, "available": True}, "ID is available")


class ProfileHandler(BaseHandler):
    @require_auth()
    def get(self):
        db = get_db()
        user = dict_from_row(db.execute(
            "SELECT id, employee_id, name, email, phone, birthday, photo_url, role, title, department, specialty, bio, language, status, created_at FROM users WHERE id = ?",
            (self.current_user_data["user_id"],)
        ).fetchone())
        db.close()
        if user:
            self.success(user)
        else:
            self.error("User not found", 404)

    @require_auth()
    def put(self):
        body = self.get_json_body()
        allowed = ["name", "email", "phone", "birthday", "bio", "specialty", "language"]
        updates = {k: body[k] for k in allowed if k in body}
        if not updates:
            return self.error("No valid fields to update")

        # Validate language if provided
        if "language" in updates and updates["language"] not in ("ko", "en"):
            return self.error("Invalid language. Must be 'ko' or 'en'")

        set_clause = ", ".join(f"{k} = ?" for k in updates)
        values = list(updates.values()) + [self.current_user_data["user_id"]]

        db = get_db()
        db.execute(f"UPDATE users SET {set_clause}, updated_at = CURRENT_TIMESTAMP WHERE id = ?", values)
        db.commit()
        db.close()
        self.success(updates, "Profile updated")


class ChangePasswordHandler(BaseHandler):
    @require_auth()
    def post(self):
        body = self.get_json_body()
        old_pw = body.get("old_password", "") or body.get("current_password", "")
        new_pw = body.get("new_password", "")

        if len(new_pw) < 8:
            return self.error("New password must be at least 8 characters")
        if not any(c.isdigit() for c in new_pw):
            return self.error("New password must contain at least one number")
        if not any(c.isalpha() for c in new_pw):
            return self.error("New password must contain at least one letter")

        db = get_db()
        user = dict_from_row(db.execute("SELECT password_hash FROM users WHERE id = ?", (self.current_user_data["user_id"],)).fetchone())
        if not user or not check_password(old_pw, user["password_hash"]):
            db.close()
            return self.error("Current password is incorrect")

        db.execute("UPDATE users SET password_hash = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                   (hash_password(new_pw), self.current_user_data["user_id"]))
        db.commit()
        db.close()
        _log_audit(self, 'change_password', 'user', self.current_user_data["user_id"])
        self.success(None, "Password changed successfully")


class LanguagePreferenceHandler(BaseHandler):
    @require_auth()
    def put(self):
        body = self.get_json_body()
        lang = body.get("language", "ko")
        if lang not in ("ko", "en"):
            return self.error("Invalid language. Must be 'ko' or 'en'")
        db = get_db()
        db.execute("UPDATE users SET language = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?", (lang, self.current_user_data["user_id"]))
        db.commit()
        db.close()
        self.success({"language": lang}, "Language updated")
