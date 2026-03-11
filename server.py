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
from database import init_db, DB_PATH
from auth import get_current_user

# Route imports
from routes.auth_routes import LoginHandler, RegisterHandler, VerifyIdHandler, ProfileHandler, ChangePasswordHandler, BaseHandler
from routes.user_routes import UsersHandler, UserDetailHandler, ResetPasswordHandler, InstructorsHandler
from routes.course_routes import CoursesHandler, CourseDetailHandler, ModulesHandler, EnrollmentHandler
from routes.schedule_routes import SchedulesHandler, ScheduleDetailHandler, AttendanceHandler
from routes.evaluation_routes import EvaluationsHandler, EvaluationDetailHandler, SubmitEvaluationHandler, BulkCreateEvaluationsHandler
from routes.ojt_routes import OJTProgramsHandler, OJTProgramDetailHandler, OJTTasksHandler, OJTEnrollHandler, OJTEvaluationsHandler
from routes.content_routes import ContentHandler, ContentDetailHandler
from routes.report_routes import DashboardHandler, CourseReportHandler, TraineeReportHandler, AttendanceReportHandler, MonthlyStatsHandler
from routes.notification_routes import NotificationsHandler, NotificationReadHandler, NotificationReadAllHandler, SurveyHandler
from routes.photo_routes import PhotoUploadHandler
from routes.pilot_routes import (PilotsHandler, PilotDetailHandler, PilotPhotoHandler,
                                  PilotCoursesHandler, PilotTrainingHandler, PilotWeeklyHandler)

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


def _track_active(request):
    ip = _get_client_ip(request)
    user = get_current_user(type('H', (), {'request': request})())
    key = f"{user['name']}({ip})" if user else ip
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
    try:
        u = get_current_user(handler)
        if u:
            user_info = u.get('name', '-')
    except Exception:
        pass

    ts = time.strftime("%Y-%m-%d %H:%M:%S")
    log_line = f"[{ts}] {status} {method} {uri} | IP={ip} | User={user_info} | {latency:.1f}ms | UA={ua}"

    # Print to console
    print(f"{status} {method} {uri} ({ip}) {latency:.1f}ms", flush=True)

    # Write to log file
    access_logger.info(log_line)


# ─── Active Users API ───
class ActiveUsersHandler(BaseHandler):
    def get(self):
        self.success({"count": _count_active()})


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

        # ── Active Users ──
        (r"/api/active-users", ActiveUsersHandler),

        # ── Uploaded files ──
        (r"/uploads/(.*)", tornado.web.StaticFileHandler, {"path": UPLOAD_PATH}),

        # ── Static files (frontend) ──
        (r"/(.*)", tornado.web.StaticFileHandler, {
            "path": STATIC_PATH,
            "default_filename": "index.html"
        }),
    ], debug=True, log_function=log_request)


if __name__ == "__main__":
    # Ensure directories exist
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
    print(f"  Database: {DB_PATH}")
    print(f"  Log file: {os.path.join(LOG_DIR, 'access.log')}")
    print(f"=" * 50)
    print(f"")
    print(f"  Other PCs can access via: http://{local_ip}:{PORT}")
    print(f"")

    # Open browser after server is ready (skip in cloud environments)
    if not os.environ.get('RENDER') and not os.environ.get('RAILWAY_ENVIRONMENT'):
        threading.Timer(1.0, lambda: webbrowser.open(f"http://localhost:{PORT}")).start()

    tornado.ioloop.IOLoop.current().start()
