"""User Management Routes"""
import json
from routes.auth_routes import BaseHandler
from database import get_db, dict_from_row, dicts_from_rows
from auth import require_auth, hash_password
from routes.audit_routes import log_audit


class UsersHandler(BaseHandler):
    @require_auth()
    def get(self):
        role_filter = self.get_argument("role", None)
        status_filter = self.get_argument("status", "active")
        search = self.get_argument("search", None)
        page = int(self.get_argument("page", 1))
        per_page = int(self.get_argument("per_page", 50))
        offset = (page - 1) * per_page

        db = get_db()
        query = "SELECT id, employee_id, name, email, phone, photo_url, role, title, department, specialty, status, created_at FROM users WHERE 1=1"
        params = []

        if role_filter:
            query += " AND role = ?"
            params.append(role_filter)
        if status_filter:
            query += " AND status = ?"
            params.append(status_filter)
        if search:
            query += " AND (name LIKE ? OR employee_id LIKE ? OR email LIKE ?)"
            s = f"%{search}%"
            params.extend([s, s, s])

        count_q = query.replace("SELECT id, employee_id, name, email, phone, photo_url, role, title, department, specialty, status, created_at", "SELECT COUNT(*)")
        total = db.execute(count_q, params).fetchone()[0]

        query += " ORDER BY created_at DESC LIMIT ? OFFSET ?"
        params.extend([per_page, offset])
        users = dicts_from_rows(db.execute(query, params).fetchall())
        db.close()

        self.success({"users": users, "total": total, "page": page, "per_page": per_page})


class UserDetailHandler(BaseHandler):
    @require_auth()
    def get(self, user_id):
        db = get_db()
        user = dict_from_row(db.execute(
            "SELECT id, employee_id, name, email, phone, birthday, role, title, department, specialty, bio, status, created_at FROM users WHERE id = ?",
            (user_id,)
        ).fetchone())
        if not user:
            db.close()
            return self.error("User not found", 404)

        # Get enrollments
        enrollments = dicts_from_rows(db.execute("""
            SELECT e.*, c.name as course_name, c.type as course_type
            FROM enrollments e JOIN courses c ON e.course_id = c.id
            WHERE e.trainee_id = ? ORDER BY e.enrolled_at DESC
        """, (user_id,)).fetchall())

        # Get evaluation scores
        evals = dicts_from_rows(db.execute("""
            SELECT ev.*, c.name as course_name
            FROM evaluations ev JOIN courses c ON ev.course_id = c.id
            WHERE ev.trainee_id = ? AND ev.status = 'graded'
            ORDER BY ev.graded_at DESC LIMIT 20
        """, (user_id,)).fetchall())

        db.close()
        user["enrollments"] = enrollments
        user["evaluations"] = evals
        self.success(user)

    @require_auth(roles=["admin", "ojt_admin"])
    def put(self, user_id):
        body = self.get_json_body()
        allowed = ["name", "email", "phone", "birthday", "role", "title", "department", "specialty", "bio", "status"]
        updates = {k: body[k] for k in allowed if k in body}
        if not updates:
            return self.error("No valid fields to update")

        set_clause = ", ".join(f"{k} = ?" for k in updates)
        values = list(updates.values()) + [user_id]

        db = get_db()
        db.execute(f"UPDATE users SET {set_clause}, updated_at = CURRENT_TIMESTAMP WHERE id = ?", values)
        db.commit()
        db.close()
        log_audit(self, 'update', 'user', int(user_id), updates)
        self.success(updates, "User updated")

    @require_auth(roles=["admin"])
    def delete(self, user_id):
        db = get_db()
        db.execute("UPDATE users SET status = 'inactive', updated_at = CURRENT_TIMESTAMP WHERE id = ?", (user_id,))
        db.commit()
        db.close()
        log_audit(self, 'delete', 'user', int(user_id))
        self.success(None, "User deactivated")


class ResetPasswordHandler(BaseHandler):
    @require_auth(roles=["admin"])
    def post(self, user_id):
        body = self.get_json_body()
        new_pw = body.get("new_password", "")
        if len(new_pw) < 8:
            return self.error("Password must be at least 8 characters")

        db = get_db()
        db.execute("UPDATE users SET password_hash = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                   (hash_password(new_pw), user_id))
        db.commit()
        db.close()
        log_audit(self, 'reset_password', 'user', int(user_id))
        self.success(None, "Password reset successfully")


class InstructorsHandler(BaseHandler):
    @require_auth()
    def get(self):
        db = get_db()
        instructors = dicts_from_rows(db.execute("""
            SELECT u.id, u.employee_id, u.name, u.email, u.specialty, u.title, u.status,
                   COUNT(DISTINCT ci.course_id) as course_count,
                   ROUND(AVG(s.instructor_rating), 1) as avg_rating
            FROM users u
            LEFT JOIN course_instructors ci ON u.id = ci.instructor_id
            LEFT JOIN surveys s ON s.course_id = ci.course_id
            WHERE u.role = 'instructor' AND u.status = 'active'
            GROUP BY u.id
            ORDER BY u.name
        """).fetchall())
        db.close()
        self.success(instructors)
