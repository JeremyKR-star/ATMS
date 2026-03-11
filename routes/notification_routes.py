"""Notification Routes"""
from routes.auth_routes import BaseHandler
from database import get_db, dicts_from_rows
from auth import require_auth


class NotificationsHandler(BaseHandler):
    @require_auth()
    def get(self):
        unread_only = self.get_argument("unread_only", "false") == "true"
        limit = int(self.get_argument("limit", 50))

        db = get_db()
        query = "SELECT * FROM notifications WHERE user_id = ?"
        params = [self.current_user_data["user_id"]]
        if unread_only:
            query += " AND is_read = 0"
        query += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)

        items = dicts_from_rows(db.execute(query, params).fetchall())
        unread_count = db.execute(
            "SELECT COUNT(*) FROM notifications WHERE user_id = ? AND is_read = 0",
            (self.current_user_data["user_id"],)
        ).fetchone()[0]
        db.close()
        self.success({"notifications": items, "unread_count": unread_count})

    @require_auth(roles=["admin", "ojt_admin", "instructor"])
    def post(self):
        body = self.get_json_body()
        if not body.get("user_id") or not body.get("title"):
            return self.error("user_id and title are required")

        db = get_db()
        db.execute("""
            INSERT INTO notifications (user_id, title, message, notification_type, link)
            VALUES (?, ?, ?, ?, ?)
        """, (body["user_id"], body["title"], body.get("message", ""),
              body.get("notification_type", "info"), body.get("link", "")))
        db.commit()
        db.close()
        self.success(None, "Notification sent")


class NotificationReadHandler(BaseHandler):
    @require_auth()
    def put(self, notif_id):
        db = get_db()
        db.execute("UPDATE notifications SET is_read = 1 WHERE id = ? AND user_id = ?",
                   (notif_id, self.current_user_data["user_id"]))
        db.commit()
        db.close()
        self.success(None, "Marked as read")


class NotificationReadAllHandler(BaseHandler):
    @require_auth()
    def put(self):
        db = get_db()
        db.execute("UPDATE notifications SET is_read = 1 WHERE user_id = ? AND is_read = 0",
                   (self.current_user_data["user_id"],))
        db.commit()
        db.close()
        self.success(None, "All marked as read")


class SurveyHandler(BaseHandler):
    @require_auth()
    def get(self):
        course_id = self.get_argument("course_id", None)
        db = get_db()
        query = """
            SELECT s.*, u.name as trainee_name, c.name as course_name
            FROM surveys s
            JOIN users u ON s.trainee_id = u.id
            LEFT JOIN courses c ON s.course_id = c.id
        """
        params = []
        if course_id:
            query += " WHERE s.course_id = ?"
            params.append(course_id)
        query += " ORDER BY s.created_at DESC"
        items = dicts_from_rows(db.execute(query, params).fetchall())
        db.close()
        self.success(items)

    @require_auth()
    def post(self):
        body = self.get_json_body()
        if not body.get("course_id"):
            return self.error("course_id is required")

        db = get_db()
        # Check duplicate
        existing = db.execute(
            "SELECT id FROM surveys WHERE course_id = ? AND trainee_id = ?",
            (body["course_id"], self.current_user_data["user_id"])
        ).fetchone()
        if existing:
            db.close()
            return self.error("Survey already submitted for this course")

        db.execute("""
            INSERT INTO surveys (course_id, trainee_id, overall_rating, instructor_rating, content_rating, facility_rating, comments)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (body["course_id"], self.current_user_data["user_id"],
              body.get("overall_rating"), body.get("instructor_rating"),
              body.get("content_rating"), body.get("facility_rating"),
              body.get("comments", "")))
        db.commit()
        db.close()
        self.success(None, "Survey submitted")
