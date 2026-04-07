"""Notification Routes"""
import time
import threading
import json
import tornado.ioloop
import tornado.web
from routes.auth_routes import BaseHandler
from database import get_db, dicts_from_rows
from auth import require_auth, decode_token

try:
    from email_utils import send_notification_email
except ImportError:
    send_notification_email = None

try:
    from websocket_handler import broadcast_to_user
except ImportError:
    broadcast_to_user = None

# Notification batch buffer
_notification_batch = {}  # user_id -> list of notifications
_batch_timer = None
_BATCH_INTERVAL = 2.0  # seconds

def _flush_notification_batch():
    """Flush all batched notifications to their respective users."""
    global _notification_batch, _batch_timer
    batch = _notification_batch
    _notification_batch = {}
    _batch_timer = None

    for user_id, notifications in batch.items():
        if len(notifications) == 1:
            if broadcast_to_user:
                try:
                    broadcast_to_user(user_id, {"type": "notification", "data": notifications[0]})
                except Exception:
                    pass
            try:
                SSEHandler.broadcast_to_user(user_id, {"type": "notification", "data": notifications[0]})
            except Exception:
                pass
        else:
            if broadcast_to_user:
                try:
                    broadcast_to_user(user_id, {"type": "notification_batch", "data": notifications, "count": len(notifications)})
                except Exception:
                    pass
            try:
                SSEHandler.broadcast_to_user(user_id, {"type": "notification_batch", "data": notifications, "count": len(notifications)})
            except Exception:
                pass

def queue_notification(user_id, notification_data):
    """Queue a notification for batched delivery."""
    global _notification_batch, _batch_timer
    if user_id not in _notification_batch:
        _notification_batch[user_id] = []
    _notification_batch[user_id].append(notification_data)

    if _batch_timer is None:
        loop = tornado.ioloop.IOLoop.current()
        _batch_timer = loop.call_later(_BATCH_INTERVAL, _flush_notification_batch)


class SSEHandler(tornado.web.RequestHandler):
    """Server-Sent Events fallback for environments where WebSocket is blocked."""

    def initialize(self, get_db=None):
        self.get_db = get_db

    async def get(self):
        self.set_header('Content-Type', 'text/event-stream')
        self.set_header('Cache-Control', 'no-cache')
        self.set_header('Connection', 'keep-alive')
        self.set_header('Access-Control-Allow-Origin', '*')
        self.set_header('X-Accel-Buffering', 'no')

        # Get user from token query param
        token = self.get_argument('token', None)
        if not token:
            self.write('event: error\ndata: {"message":"Token required"}\n\n')
            self.finish()
            return

        user = decode_token(token)
        if not user:
            self.write('event: error\ndata: {"message":"Invalid token"}\n\n')
            self.finish()
            return

        user_id = user.get('user_id')
        if not user_id:
            self.write('event: error\ndata: {"message":"Invalid token"}\n\n')
            self.finish()
            return

        # Register in SSE clients registry
        if not hasattr(SSEHandler, '_sse_clients'):
            SSEHandler._sse_clients = {}
        if user_id not in SSEHandler._sse_clients:
            SSEHandler._sse_clients[user_id] = set()
        SSEHandler._sse_clients[user_id].add(self)

        # Send initial connected event
        self.write('event: connected\ndata: {"user_id": %d}\n\n' % user_id)
        self.flush()

        # Keep alive with periodic comments
        self._sse_active = True
        while self._sse_active:
            try:
                self.write(': keepalive\n\n')
                self.flush()
                await tornado.gen.sleep(15)
            except Exception:
                break

        # Cleanup
        if user_id in SSEHandler._sse_clients:
            SSEHandler._sse_clients[user_id].discard(self)

    def on_connection_close(self):
        self._sse_active = False

    @staticmethod
    def broadcast_to_user(user_id, message_data):
        """Send SSE event to a user's connections."""
        if not hasattr(SSEHandler, '_sse_clients'):
            return
        user_id = int(user_id)
        connections = SSEHandler._sse_clients.get(user_id, set())
        dead = set()
        msg = json.dumps(message_data)
        for handler in connections:
            try:
                handler.write('event: notification\ndata: %s\n\n' % msg)
                handler.flush()
            except Exception:
                dead.add(handler)
        for handler in dead:
            connections.discard(handler)


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

        # Send email notification if configured
        if send_notification_email:
            user_email = db.execute("SELECT email FROM users WHERE id = ?", (body["user_id"],)).fetchone()
            if user_email and user_email[0]:
                try:
                    send_notification_email(user_email[0], body.get("title", "ATMS Notification"), body.get("message", ""))
                except Exception:
                    pass  # Email failure should not block notification creation

        # Queue notification for batched delivery via WebSocket and SSE
        notification_data = {
            "title": body.get("title", ""),
            "message": body.get("message", ""),
            "notification_type": body.get("notification_type", "info"),
            "link": body.get("link", "")
        }
        queue_notification(body["user_id"], notification_data)

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
