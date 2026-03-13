"""
ATMS - Advanced Training Management System
Main Server Entry Point (Tornado)
"""
import os
import socket
import time
import webbrowser
import threading
import logging
from logging.handlers import RotatingFileHandler
import tornado.ioloop
import tornado.web
from database import init_db, get_db, DB_PATH, IS_POSTGRES, dicts_from_rows
from auth import get_current_user, require_auth

# Route imports
from routes.auth_routes import LoginHandler, RegisterHandler, VerifyIdHandler, ProfileHandler, ChangePasswordHandler, BaseHandler
from routes.user_routes import UsersHandler, UserDetailHandler, ResetPasswordHandler, InstructorsHandler
from routes.course_routes import CoursesHandler, CourseDetailHandler, ModulesHandler, EnrollmentHandler
from routes.schedule_routes import SchedulesHandler, ScheduleDetailHandler, AttendanceHandler, ScheduleConflictCheckHandler
from routes.evaluation_routes import EvaluationsHandler, EvaluationDetailHandler, SubmitEvaluationHandler, BulkCreateEvaluationsHandler
from routes.ojt_routes import OJTProgramsHandler, OJTProgramDetailHandler, OJTTasksHandler, OJTEnrollHandler, OJTEvaluationsHandler
from routes.content_routes import ContentHandler, ContentDetailHandler
from routes.report_routes import DashboardHandler, CourseReportHandler, TraineeReportHandler, AttendanceReportHandler, MonthlyStatsHandler
from routes.notification_routes import NotificationsHandler, NotificationReadHandler, NotificationReadAllHandler, SurveyHandler
from routes.photo_routes import PhotoUploadHandler
from routes.pilot_routes import (PilotsHandler, PilotDetailHandler, PilotPhotoHandler,
                                  PilotCoursesHandler, PilotTrainingHandler, PilotWeeklyHandler,
                                  PilotNationalitiesHandler, WeeklyUploadHandler,
                                  WeeklyUploadDetailHandler, WeeklyUploadDownloadHandler,
                                  WeeklyUploadLatestHandler)
from routes.mechanic_routes import (MechanicsHandler, MechanicDetailHandler, MechanicPhotoHandler,
                                    MechanicOJTItemsHandler, MechanicOJTRecordsHandler,
                                    MechanicCertificationsHandler, MechanicCertDetailHandler,
                                    MechanicSummaryHandler)
from routes.audit_routes import AuditLogHandler
from routes.backup_routes import BackupHandler, BackupListHandler, BackupCreateHandler

PORT = int(os.environ.get('PORT', 8080))
STATIC_PATH = os.path.join(os.path.dirname(__file__), "public")
UPLOAD_PATH = os.path.join(STATIC_PATH, "uploads")
LOG_DIR = os.path.join(os.path.dirname(__file__), "logs")

# ─── Active users tracking (simple time-window model) ───
_active_users = {}  # {ip_or_user: last_seen_timestamp}
ACTIVE_WINDOW = 300  # 5 minutes


def _get_client_ip(request):
    forwarded = request.headers.get("X-Forwarded-For", "")
    return forwarded.split(",")[0].strip() if forwarded else request.remote_ip


SKIP_IPS = {'127.0.0.1', '::1', '10.0.0.0'}  # Render internal / loopback

def _is_bot(request):
    """Check if request is from a bot or health check."""
    ua = request.headers.get("User-Agent", "").lower()
    ip = _get_client_ip(request)
    # Skip loopback, Render health checks, and known bots
    if ip in SKIP_IPS or ip.startswith("10."):
        return True
    if any(b in ua for b in ("bot", "spider", "crawl", "monitor", "health", "uptimerobot", "render")):
        return True
    # HEAD requests are typically health checks
    if request.method == "HEAD":
        return True
    return False


def _track_active(request):
    if _is_bot(request):
        return
    ip = _get_client_ip(request)
    user = get_current_user(type('H', (), {'request': request})())
    # Track by IP only (deduplicate same person before/after login)
    key = ip
    _active_users[key] = time.time()


def _count_active():
    now = time.time()
    return sum(1 for t in _active_users.values() if now - t < ACTIVE_WINDOW)


# ─── Access Logger ───
def setup_access_logger():
    os.makedirs(LOG_DIR, exist_ok=True)
    logger = logging.getLogger("atms.access")
    logger.setLevel(logging.INFO)
    handler = RotatingFileHandler(
        os.path.join(LOG_DIR, "access.log"),
        maxBytes=10 * 1024 * 1024,  # 10 MB
        backupCount=5,
        encoding="utf-8"
    )
    handler.setFormatter(logging.Formatter("%(message)s"))
    logger.addHandler(handler)
    return logger


access_logger = None


def log_request(handler):
    """Log every request with status, latency, client IP, and user."""
    global access_logger
    if access_logger is None:
        access_logger = setup_access_logger()

    request = handler.request
    ip = _get_client_ip(request)
    status = handler.get_status()
    method = request.method
    uri = request.uri
    latency = 1000.0 * request.request_time()
    ua = request.headers.get("User-Agent", "-")[:100]

    # Track active user
    _track_active(request)

    # Get authenticated user name if available
    user_info = "-"
    user_id = None
    try:
        u = get_current_user(handler)
        if u:
            user_info = u.get('name', '-')
            user_id = u.get('id')
    except Exception:
        pass

    ts = time.strftime("%Y-%m-%d %H:%M:%S")
    log_line = f"[{ts}] {status} {method} {uri} | IP={ip} | User={user_info} | {latency:.1f}ms | UA={ua}"

    # Print to console
    print(f"{status} {method} {uri} ({ip}) {latency:.1f}ms", flush=True)

    # Write to log file
    access_logger.info(log_line)

    # Save to DB (only real user requests, skip static files and bots)
    try:
        path = uri.split("?")[0]
        skip_exts = ('.js', '.css', '.png', '.jpg', '.jpeg', '.gif', '.svg', '.ico', '.woff', '.woff2', '.ttf', '.map')
        is_bot = ip in SKIP_IPS or ip.startswith("10.") or method == "HEAD"
        if not is_bot and not path.endswith(skip_exts) and method in ('GET', 'POST', 'PUT', 'DELETE', 'PATCH'):
            db = get_db()
            db.execute(
                "INSERT INTO access_logs (ip_address, method, path, status_code, user_agent, user_id, user_name, response_time_ms) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (ip, method, path, status, ua[:200], user_id, user_info if user_info != "-" else None, round(latency, 1))
            )
            db.commit()
            db.close()
    except Exception:
        pass  # Don't let logging errors break the app


# ─── Active Users API ───
class ActiveUsersHandler(BaseHandler):
    def get(self):
        self.success({"count": _count_active()})


# ─── Access Logs API ───
class AccessLogsHandler(BaseHandler):
    @require_auth(roles=["admin"])
    def get(self):
        db = get_db()
        page = int(self.get_argument("page", "1"))
        limit = int(self.get_argument("limit", "50"))
        ip_filter = self.get_argument("ip", "")
        offset = (page - 1) * limit

        query = "SELECT * FROM access_logs WHERE 1=1"
        count_query = "SELECT COUNT(*) as cnt FROM access_logs WHERE 1=1"
        params = []

        if ip_filter:
            query += " AND ip_address LIKE ?"
            count_query += " AND ip_address LIKE ?"
            params.append(f"%{ip_filter}%")

        total = db.execute(count_query, params).fetchone()["cnt"]
        query += " ORDER BY created_at DESC LIMIT ? OFFSET ?"
        params.extend([limit, offset])
        logs = dicts_from_rows(db.execute(query, params).fetchall())

        # Unique visitor stats
        stats = {}
        stats["total_requests"] = total
        stats["unique_ips"] = db.execute("SELECT COUNT(DISTINCT ip_address) as cnt FROM access_logs").fetchone()["cnt"]
        stats["today_requests"] = db.execute(
            "SELECT COUNT(*) as cnt FROM access_logs WHERE CAST(created_at AS TEXT) LIKE ?",
            (time.strftime("%Y-%m-%d") + "%",)
        ).fetchone()["cnt"]
        stats["today_unique_ips"] = db.execute(
            "SELECT COUNT(DISTINCT ip_address) as cnt FROM access_logs WHERE CAST(created_at AS TEXT) LIKE ?",
            (time.strftime("%Y-%m-%d") + "%",)
        ).fetchone()["cnt"]

        db.close()
        self.success({
            "logs": logs,
            "total": total,
            "page": page,
            "limit": limit,
            "stats": stats
        })


def make_app():
    return tornado.web.Application([
        # ── Auth ──
        (r"/api/auth/login", LoginHandler),
        (r"/api/auth/register", RegisterHandler),
        (r"/api/auth/verify-id", VerifyIdHandler),
        (r"/api/auth/profile", ProfileHandler),
        (r"/api/auth/change-password", ChangePasswordHandler),

        # ── Users ──
        (r"/api/users", UsersHandler),
        (r"/api/users/(\d+)", UserDetailHandler),
        (r"/api/users/(\d+)/reset-password", ResetPasswordHandler),
        (r"/api/instructors", InstructorsHandler),

        # ── Courses ──
        (r"/api/courses", CoursesHandler),
        (r"/api/courses/(\d+)", CourseDetailHandler),
        (r"/api/courses/(\d+)/modules", ModulesHandler),
        (r"/api/courses/(\d+)/enroll", EnrollmentHandler),

        # ── Schedule ──
        (r"/api/schedules", SchedulesHandler),
        (r"/api/schedules/check-conflicts", ScheduleConflictCheckHandler),
        (r"/api/schedules/(\d+)", ScheduleDetailHandler),
        (r"/api/schedules/(\d+)/attendance", AttendanceHandler),  # FIXED: was /api/attendance

        # ── Evaluations ──
        (r"/api/evaluations", EvaluationsHandler),
        (r"/api/evaluations/(\d+)", EvaluationDetailHandler),
        (r"/api/evaluations/(\d+)/submit", SubmitEvaluationHandler),
        (r"/api/evaluations/bulk-create", BulkCreateEvaluationsHandler),

        # ── OJT ──
        (r"/api/ojt/programs", OJTProgramsHandler),
        (r"/api/ojt/programs/(\d+)", OJTProgramDetailHandler),
        (r"/api/ojt/programs/(\d+)/tasks", OJTTasksHandler),
        (r"/api/ojt/programs/(\d+)/enroll", OJTEnrollHandler),  # FIXED: was /api/ojt/enroll

        # ── Content ──
        (r"/api/content", ContentHandler),
        (r"/api/content/(\d+)", ContentDetailHandler),

        # ── Reports ──
        (r"/api/dashboard", DashboardHandler),
        (r"/api/reports/courses", CourseReportHandler),
        (r"/api/reports/trainees", TraineeReportHandler),
        (r"/api/reports/attendance", AttendanceReportHandler),
        (r"/api/reports/monthly", MonthlyStatsHandler),

        # ── Notifications & Surveys ──
        (r"/api/notifications", NotificationsHandler),
        (r"/api/notifications/(\d+)/read", NotificationReadHandler),
        (r"/api/notifications/read-all", NotificationReadAllHandler),
        (r"/api/surveys", SurveyHandler),

        # ── Photo Upload (user photos) ──
        (r"/api/upload/photo", PhotoUploadHandler),

        # ── Pilots ──
        (r"/api/pilots", PilotsHandler),
        (r"/api/pilots/(\d+)", PilotDetailHandler),
        (r"/api/pilots/(\d+)/photo", PilotPhotoHandler),
        (r"/api/pilots/courses", PilotCoursesHandler),
        (r"/api/pilots/training", PilotTrainingHandler),
        (r"/api/pilots/weekly", PilotWeeklyHandler),
        (r"/api/pilots/nationalities", PilotNationalitiesHandler),
        (r"/api/pilots/weekly-uploads", WeeklyUploadHandler),
        (r"/api/pilots/weekly-uploads/latest", WeeklyUploadLatestHandler),
        (r"/api/pilots/weekly-uploads/(\d+)", WeeklyUploadDetailHandler),
        (r"/api/pilots/weekly-uploads/(\d+)/download", WeeklyUploadDownloadHandler),

        # ── Mechanics ──
        (r"/api/mechanics", MechanicsHandler),
        (r"/api/mechanics/(\d+)", MechanicDetailHandler),
        (r"/api/mechanics/(\d+)/photo", MechanicPhotoHandler),
        (r"/api/mechanics/ojt-items", MechanicOJTItemsHandler),
        (r"/api/mechanics/ojt-records", MechanicOJTRecordsHandler),
        (r"/api/mechanics/certifications", MechanicCertificationsHandler),
        (r"/api/mechanics/certifications/(\d+)", MechanicCertDetailHandler),
        (r"/api/mechanics/summary", MechanicSummaryHandler),

        # ── Active Users ──
        # ── Audit Log ──
        (r"/api/audit-log", AuditLogHandler),

        # ── Backup ──
        (r"/api/admin/backup", BackupHandler),
        (r"/api/admin/backup/list", BackupListHandler),
        (r"/api/admin/backup/create", BackupCreateHandler),

        (r"/api/active-users", ActiveUsersHandler),
        (r"/api/access-logs", AccessLogsHandler),

        # ── Uploaded files ──
        (r"/uploads/(.*)", tornado.web.StaticFileHandler, {"path": UPLOAD_PATH}),

        # ── Static files (frontend) ──
        (r"/(.*)", tornado.web.StaticFileHandler, {
            "path": STATIC_PATH,
            "default_filename": "index.html"
        }),
    ], debug=os.environ.get("ATMS_DEBUG", "").lower() in ("1", "true", "yes"),
       log_function=log_request)


if __name__ == "__main__":
    # Ensure directories exist
    if not IS_POSTGRES:
        os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    os.makedirs(STATIC_PATH, exist_ok=True)
    os.makedirs(UPLOAD_PATH, exist_ok=True)
    os.makedirs(LOG_DIR, exist_ok=True)

    # Initialize database
    init_db()

    app = make_app()
    app.listen(PORT, address="0.0.0.0")

    # Get local IP address
    local_ip = "unknown"
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        local_ip = s.getsockname()[0]
        s.close()
    except Exception:
        pass

    print(f"=" * 50)
    print(f"  ATMS Server Running")
    print(f"  Local:   http://localhost:{PORT}")
    print(f"  Network: http://{local_ip}:{PORT}")
    print(f"  Database: {'PostgreSQL (Neon)' if IS_POSTGRES else DB_PATH}")
    print(f"  Log file: {os.path.join(LOG_DIR, 'access.log')}")
    print(f"=" * 50)
    print(f"")
    print(f"  Other PCs can access via: http://{local_ip}:{PORT}")
    print(f"")

    # Open browser after server is ready (skip in cloud environments)
    if not os.environ.get('RENDER') and not os.environ.get('RAILWAY_ENVIRONMENT'):
        threading.Timer(1.0, lambda: webbrowser.open(f"http://localhost:{PORT}")).start()

    tornado.ioloop.IOLoop.current().start()
