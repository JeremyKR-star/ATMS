"""Authentication Routes: Login, Register, Profile"""
import json
import tornado.web
from database import get_db, dict_from_row
from auth import hash_password, check_password, generate_token, require_auth, get_current_user


class BaseHandler(tornado.web.RequestHandler):
    """Base handler with JSON helpers."""

    def set_default_headers(self):
        self.set_header("Content-Type", "application/json")
        self.set_header("Access-Control-Allow-Origin", "*")
        self.set_header("Access-Control-Allow-Methods", "GET,POST,PUT,DELETE,OPTIONS")
        self.set_header("Access-Control-Allow-Headers", "Content-Type,Authorization")

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

        db = get_db()
        user = dict_from_row(db.execute(
            "SELECT * FROM users WHERE employee_id = ? AND status = 'active'",
            (employee_id,)
        ).fetchone())
        db.close()

        if not user or not check_password(password, user["password_hash"]):
            return self.error("Invalid employee ID or password", 401)

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

        valid_roles = ["admin", "instructor", "trainee", "ojt_admin", "manager", "staff", "customer"]
        if role not in valid_roles:
            return self.error(f"Invalid role. Must be one of: {', '.join(valid_roles)}")

        db = get_db()
        existing = db.execute("SELECT id FROM users WHERE employee_id = ?", (employee_id,)).fetchone()
        if existing:
            db.close()
            return self.error("Employee ID already exists")

        try:
            cur = db.execute(
                """INSERT INTO users (employee_id, password_hash, name, role, title, department, email, phone, birthday, specialty)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (employee_id, hash_password(password), name, role, title, department, email, phone, birthday, specialty)
            )
            db.commit()
            user_id = cur.lastrowid
            db.close()
            self.success({"id": user_id, "employee_id": employee_id, "name": name, "role": role}, "User registered successfully")
        except Exception as e:
            db.close()
            self.error(str(e), 500)


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
            "SELECT id, employee_id, name, email, phone, birthday, photo_url, role, title, department, specialty, bio, status, created_at FROM users WHERE id = ?",
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
        allowed = ["name", "email", "phone", "birthday", "bio", "specialty"]
        updates = {k: body[k] for k in allowed if k in body}
        if not updates:
            return self.error("No valid fields to update")

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

        db = get_db()
        user = dict_from_row(db.execute("SELECT password_hash FROM users WHERE id = ?", (self.current_user_data["user_id"],)).fetchone())
        if not user or not check_password(old_pw, user["password_hash"]):
            db.close()
            return self.error("Current password is incorrect")

        db.execute("UPDATE users SET password_hash = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                   (hash_password(new_pw), self.current_user_data["user_id"]))
        db.commit()
        db.close()
        self.success(None, "Password changed successfully")
