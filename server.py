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
from collections import defaultdict
import tornado.ioloop
import tornado.web
from database import init_db, get_db, DB_PATH, IS_POSTGRES, dicts_from_rows
from auth import get_current_user, require_auth

# ─── Rate Limiter ───
class RateLimiter:
    """In-memory rate limiter using sliding window algorithm."""

    def __init__(self):
        # {ip: [(timestamp, ...), (timestamp, ...), ...]}
        self.requests = defaultdict(list)
        self.last_cleanup = time.time()
        self.cleanup_interval = 300  # 5 minutes

        # Rate limits: requests per minute per IP
        self.limits = {
            'login': 10,          # /api/auth/login
            'upload': 20,         # file upload endpoints
            'general': 120        # general API endpoints
        }

    def _get_client_ip(self, request):
        """Extract client IP from request, considering proxies."""
        forwarded = request.headers.get("X-Forwarded-For", "")
        return forwarded.split(",")[0].strip() if forwarded else request.remote_ip

    def _cleanup_expired(self):
        """Remove request timestamps older than 1 minute."""
        now = time.time()
        if now - self.last_cleanup < self.cleanup_interval:
            return

        self.last_cleanup = now
        window = 60  # 1 minute
        cutoff_time = now - window

        # Clean up old entries
        expired_ips = []
        for ip in list(self.requests.keys()):
            self.requests[ip] = [ts for ts in self.requests[ip] if ts > cutoff_time]
            if not self.requests[ip]:
                expired_ips.append(ip)

        for ip in expired_ips:
            del self.requests[ip]

    def check_rate_limit(self, request, endpoint_type='general'):
        """
        Check if request exceeds rate limit.

        Args:
            request: Tornado request object
            endpoint_type: 'login', 'upload', or 'general'

        Returns:
            (is_allowed, retry_after_seconds)
        """
        self._cleanup_expired()

        ip = self._get_client_ip(request)
        now = time.time()
        window = 60  # 1 minute
        cutoff_time = now - window

        # Remove timestamps outside the window
        self.requests[ip] = [ts for ts in self.requests[ip] if ts > cutoff_time]

        limit = self.limits.get(endpoint_type, self.limits['general'])
        current_count = len(self.requests[ip])

        if current_count >= limit:
            # Rate limit exceeded - calculate retry_after
            if self.requests[ip]:
                oldest_request = min(self.requests[ip])
                retry_after = int(window - (now - oldest_request)) + 1
            else:
                retry_after = 60
            return False, retry_after

        # Add current request timestamp
        self.requests[ip].append(now)
        return True, 0


# Global rate limiter instance
_rate_limiter = RateLimiter()


# ─── Rate Limited Handler Mixin ───
class RateLimitMixin:
    """
    Mixin to add rate limiting to Tornado handlers.

    Handlers using this mixin will automatically check rate limits in prepare().
    If rate limited, a 429 response is sent automatically.

    Set self.rate_limit_type = 'login', 'upload', or 'general' (default) to control the limit.
    """

    rate_limit_type = 'general'  # Can be overridden by subclasses

    def prepare(self):
        """Check rate limit before processing request."""
        # Call parent prepare() if it exists
        if hasattr(super(), 'prepare'):
            super().prepare()

        # Check rate limit
        is_allowed, error_response = _check_rate_limit(self.request, self)
        if not is_allowed:
            self.write(error_response)
            self.finish()


# Route imports
from routes.auth_routes import LoginHandler, RegisterHandler, VerifyIdHandler, ProfileHandler, ChangePasswordHandler, LanguagePreferenceHandler, BaseHandler
from routes.user_routes import UsersHandler, UserDetailHandler, ResetPasswordHandler, InstructorsHandler, BulkUserImportHandler
from routes.course_routes import CoursesHandler, CourseDetailHandler, ModulesHandler, EnrollmentHandler
from routes.schedule_routes import SchedulesHandler, ScheduleDetailHandler, AttendanceHandler, ScheduleConflictCheckHandler, ScheduleEnrollmentsHandler, ScheduleOptimizeHandler
from routes.evaluation_routes import EvaluationsHandler, EvaluationDetailHandler, SubmitEvaluationHandler, BulkCreateEvaluationsHandler, TransferEvaluationHandler
from routes.ojt_routes import OJTProgramsHandler, OJTProgramDetailHandler, OJTTasksHandler, OJTEnrollHandler, OJTEvaluationsHandler
from routes.content_routes import ContentHandler, ContentDetailHandler
from routes.report_routes import DashboardHandler, CourseReportHandler, TraineeReportHandler, AttendanceReportHandler, MonthlyStatsHandler, ReportExportHandler, ModuleAttendanceReportHandler, OJTTaskCompletionReportHandler, OJTTraineeProgressReportHandler, OJTLeaderEvalSummaryHandler
from routes.notification_routes import NotificationsHandler, NotificationReadHandler, NotificationReadAllHandler, SurveyHandler, SSEHandler, NotificationPreferencesHandler, SurveyAnalyticsHandler, QRAttendanceHandler
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
from routes.wrapup_routes import (WrapUpTestsHandler, WrapUpTestDetailHandler,
                                   WrapUpQuestionsHandler, WrapUpQuestionDetailHandler,
                                   WrapUpSubmitHandler, WrapUpGradeHandler)
from routes.assignment_routes import (AssignmentSubmissionsHandler, AssignmentGradeHandler,
                                       DigitalSignaturesHandler, DigitalSignatureVerifyHandler,
                                       CounselingHandler, UserProfileExtHandler)
from websocket_handler import ATMSWebSocketHandler, broadcast_to_user, broadcast_to_all
from routes.work_schedule_routes import WorkSchedulesHandler, WorkScheduleDetailHandler, WorkScheduleSummaryHandler
from routes.ojt_extended_routes import (
    OJTSubTasksHandler, OJTSubTaskDetailHandler,
    OJTLeadersHandler, OJTLeaderDetailHandler,
    OJTTrainingSpecsHandler, OJTTrainingSpecDetailHandler,
    OJTEvalSpecsHandler, OJTEvalSpecDetailHandler,
    OJTPreAssignmentsHandler, OJTPreAssignmentSubmitHandler,
    OJTVenuesHandler, OJTVenueDetailHandler,
    OJTAnnouncementsHandler, OJTAnnouncementDetailHandler,
    OJTSurveyTemplatesHandler, OJTSurveyTemplateDetailHandler,
    OJTSurveyItemsHandler, OJTSurveyResponsesHandler, OJTSurveyResultsHandler,
    OJTSchedulesHandler, OJTScheduleDetailHandler,
    CareerRoadmapHandler, CareerRoadmapDetailHandler,
    CareerRoadmapTasksHandler, CareerRoadmapSubTasksHandler,
    CareerRoadmapProgressHandler,
    OJTTrainingResultsHandler, OJTTrainingResultDetailHandler, OJTApprovalHandler,
    OJTProgramAdminsHandler, OJTProgramAdminDetailHandler,
    OJTEvalTemplateHandler, OJTEvalTemplateDetailHandler, OJTEvalTemplateBulkApplyHandler
)

PORT = int(os.environ.get('PORT', 8080))
STATIC_PATH = os.path.join(os.path.dirname(__file__), "public")
UPLOAD_PATH = os.path.join(STATIC_PATH, "uploads")
LOG_DIR = os.path.join(os.path.dirname(__file__), "logs")

# ─── Active users tracking (simple time-window model) ───
_active_users = {}  # {ip_or_user: last_seen_timestamp}
ACTIVE_WINDOW = 60  # 1 minute


def _get_client_ip(request):
    forwarded = request.headers.get("X-Forwarded-For", "")
    return forwarded.split(",")[0].strip() if forwarded else request.remote_ip


SKIP_IPS = {'127.0.0.1', '::1', '10.0.0.0'}  # Render internal / loopback

def _is_bot(request):
    """Check if request is from a bot or health check."""
    ua = request.headers.get("User-Agent", "").lower()
    ip = _get_client_ip(request)
    # Skip loopback, Render health checks, and known bots
    if ip in SKIP_IPS or ip.startswith("10.") or ip.startswith("35.") or ip.startswith("34."):
        return True
    if any(b in ua for b in ("bot", "spider", "crawl", "monitor", "health", "uptimerobot", "render")):
        return True
    # HEAD requests are typically health checks
    if request.method == "HEAD":
        return True
    return False


def _should_rate_limit(request):
    """Determine if rate limiting should apply to this request."""
    # Don't rate limit bots or health checks
    if _is_bot(request):
        return False
    # Don't rate limit static files
    if request.path.startswith('/uploads/') or request.path.endswith(('.js', '.css', '.png', '.jpg', '.jpeg', '.gif', '.svg', '.ico', '.woff', '.woff2', '.ttf', '.map')):
        return False
    return True


def _check_rate_limit(request, handler):
    """
    Check rate limit and set response if exceeded.

    Returns: (is_allowed, error_response_dict_or_none)
    """
    if not _should_rate_limit(request):
        return True, None

    # Determine endpoint type
    path = request.path
    if '/api/auth/login' in path:
        endpoint_type = 'login'
    elif '/upload/' in path or path.endswith('/download'):
        endpoint_type = 'upload'
    else:
        endpoint_type = 'general'

    is_allowed, retry_after = _rate_limiter.check_rate_limit(request, endpoint_type)

    if not is_allowed:
        error_response = {
            "error": "Too many requests. Please try again later.",
            "retry_after": retry_after
        }
        handler.set_status(429)
        handler.set_header("Retry-After", str(retry_after))
        handler.set_header("Content-Type", "application/json")
        return False, error_response

    return True, None


def _track_active(request):
    if _is_bot(request):
        return
    ip = _get_client_ip(request)
    user = get_current_user(type('H', (), {'request': request})())
    # Track by IP only (deduplicate same person before/after login)
    key = ip
    _active_users[key] = time.time()


def _flush_expired():
    """Remove expired users and log DISCONNECT for each."""
    now = time.time()
    expired = [ip for ip, t in _active_users.items() if now - t >= ACTIVE_WINDOW]
    for ip in expired:
        del _active_users[ip]
        # Log disconnect to DB
        try:
            db = get_db()
            db.execute(
                "INSERT INTO access_logs (ip_address, method, path, status_code, user_agent, response_time_ms) VALUES (?, ?, ?, ?, ?, ?)",
                (ip, "DISCONNECT", "-", 0, "system:auto-timeout", 0)
            )
            db.commit()
            db.close()
        except Exception:
            pass


def _count_active():
    _flush_expired()
    return len(_active_users)


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

    # Check rate limit (note: rate limited responses are already sent by _check_rate_limit)
    # This is informational logging only
    if _should_rate_limit(request) and status == 429:
        # Rate limit already applied in handler
        pass

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
        is_bot = ip in SKIP_IPS or ip.startswith("10.") or ip.startswith("35.") or ip.startswith("34.") or method == "HEAD"
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
        method_filter = self.get_argument("method", "")
        status_filter = self.get_argument("status", "")
        date_from = self.get_argument("date_from", "")
        date_to = self.get_argument("date_to", "")
        path_filter = self.get_argument("path", "")
        offset = (page - 1) * limit

        query = "SELECT * FROM access_logs WHERE 1=1"
        count_query = "SELECT COUNT(*) as cnt FROM access_logs WHERE 1=1"
        params = []

        if ip_filter:
            query += " AND ip_address LIKE ?"
            count_query += " AND ip_address LIKE ?"
            params.append(f"%{ip_filter}%")

        if method_filter:
            query += " AND method=?"
            count_query += " AND method=?"
            params.append(method_filter)

        if status_filter:
            if status_filter == '2xx':
                query += " AND status_code >= 200 AND status_code < 300"
                count_query += " AND status_code >= 200 AND status_code < 300"
            elif status_filter == '3xx':
                query += " AND status_code >= 300 AND status_code < 400"
                count_query += " AND status_code >= 300 AND status_code < 400"
            elif status_filter == '4xx':
                query += " AND status_code >= 400 AND status_code < 500"
                count_query += " AND status_code >= 400 AND status_code < 500"
            elif status_filter == '5xx':
                query += " AND status_code >= 500"
                count_query += " AND status_code >= 500"
            elif status_filter == 'disconnect':
                query += " AND method='DISCONNECT'"
                count_query += " AND method='DISCONNECT'"
            else:
                try:
                    sc = int(status_filter)
                    query += " AND status_code=?"
                    count_query += " AND status_code=?"
                    params.append(sc)
                except ValueError:
                    pass

        if date_from:
            query += " AND CAST(created_at AS TEXT) >= ?"
            count_query += " AND CAST(created_at AS TEXT) >= ?"
            params.append(date_from)

        if date_to:
            query += " AND CAST(created_at AS TEXT) < ?"
            count_query += " AND CAST(created_at AS TEXT) < ?"
            # Add one day to include the full end date
            params.append(date_to + " 23:59:59")

        if path_filter:
            query += " AND path LIKE ?"
            count_query += " AND path LIKE ?"
            params.append(f"%{path_filter}%")

        total = db.execute(count_query, params).fetchone()["cnt"]
        query += " ORDER BY created_at DESC LIMIT ? OFFSET ?"
        params.extend([limit, offset])
        logs = dicts_from_rows(db.execute(query, params).fetchall())

        # Unique visitor stats (for filtered results too)
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


class AccessLogsUniqueIPsHandler(BaseHandler):
    """GET unique IP list — all time or today only"""
    @require_auth(roles=["admin"])
    def get(self):
        db = get_db()
        scope = self.get_argument("scope", "all")  # "all" or "today"

        if scope == "today":
            today = time.strftime("%Y-%m-%d")
            rows = dicts_from_rows(db.execute(
                """SELECT ip_address, COUNT(*) as request_count,
                   MIN(created_at) as first_seen, MAX(created_at) as last_seen
                   FROM access_logs
                   WHERE CAST(created_at AS TEXT) LIKE ?
                   GROUP BY ip_address ORDER BY request_count DESC""",
                (today + "%",)
            ).fetchall())
        else:
            rows = dicts_from_rows(db.execute(
                """SELECT ip_address, COUNT(*) as request_count,
                   MIN(created_at) as first_seen, MAX(created_at) as last_seen
                   FROM access_logs
                   GROUP BY ip_address ORDER BY request_count DESC"""
            ).fetchall())

        db.close()
        self.success(rows)


def make_app():
    return tornado.web.Application([
        # ── Auth ──
        (r"/api/auth/login", LoginHandler),
        (r"/api/auth/register", RegisterHandler),
        (r"/api/auth/verify-id", VerifyIdHandler),
        (r"/api/auth/profile", ProfileHandler),
        (r"/api/auth/change-password", ChangePasswordHandler),
        (r"/api/auth/language", LanguagePreferenceHandler),

        # ── Users ──
        (r"/api/users", UsersHandler),
        (r"/api/users/(\d+)", UserDetailHandler),
        (r"/api/users/(\d+)/reset-password", ResetPasswordHandler),
        (r"/api/users/bulk-import", BulkUserImportHandler),
        (r"/api/instructors", InstructorsHandler),

        # ── Courses ──
        (r"/api/courses", CoursesHandler),
        (r"/api/courses/(\d+)", CourseDetailHandler),
        (r"/api/courses/(\d+)/modules", ModulesHandler),
        (r"/api/courses/(\d+)/enroll", EnrollmentHandler),

        # ── Schedule ──
        (r"/api/schedules", SchedulesHandler),
        (r"/api/schedules/check-conflicts", ScheduleConflictCheckHandler),
        (r"/api/schedules/optimize", ScheduleOptimizeHandler),
        (r"/api/schedules/(\d+)", ScheduleDetailHandler),
        (r"/api/schedules/(\d+)/attendance", AttendanceHandler),  # FIXED: was /api/attendance
        (r"/api/schedules/(\d+)/enrollments", ScheduleEnrollmentsHandler),

        # ── Evaluations ──
        (r"/api/evaluations", EvaluationsHandler),
        (r"/api/evaluations/(\d+)", EvaluationDetailHandler),
        (r"/api/evaluations/(\d+)/submit", SubmitEvaluationHandler),
        (r"/api/evaluations/(\d+)/transfer", TransferEvaluationHandler),
        (r"/api/evaluations/bulk-create", BulkCreateEvaluationsHandler),

        # ── OJT ──
        (r"/api/ojt/programs", OJTProgramsHandler),
        (r"/api/ojt/programs/(\d+)", OJTProgramDetailHandler),
        (r"/api/ojt/programs/(\d+)/tasks", OJTTasksHandler),
        (r"/api/ojt/programs/(\d+)/enroll", OJTEnrollHandler),  # FIXED: was /api/ojt/enroll
        (r"/api/ojt/evaluations", OJTEvaluationsHandler),

        # ── Content ──
        (r"/api/content", ContentHandler),
        (r"/api/content/(\d+)", ContentDetailHandler),

        # ── Reports ──
        (r"/api/dashboard", DashboardHandler),
        (r"/api/reports/courses", CourseReportHandler),
        (r"/api/reports/trainees", TraineeReportHandler),
        (r"/api/reports/attendance", AttendanceReportHandler),
        (r"/api/reports/module-attendance", ModuleAttendanceReportHandler),
        (r"/api/reports/monthly", MonthlyStatsHandler),
        (r"/api/reports/ojt-task-completion", OJTTaskCompletionReportHandler),
        (r"/api/reports/ojt-trainee-progress", OJTTraineeProgressReportHandler),
        (r"/api/reports/ojt-leader-eval-summary", OJTLeaderEvalSummaryHandler),
        (r"/api/reports/export", ReportExportHandler),

        # ── Notifications & Surveys ──
        (r"/api/notifications", NotificationsHandler),
        (r"/api/notifications/(\d+)/read", NotificationReadHandler),
        (r"/api/notifications/read-all", NotificationReadAllHandler),
        (r"/api/notifications/preferences", NotificationPreferencesHandler),
        (r"/api/surveys", SurveyHandler),
        (r"/api/surveys/analytics", SurveyAnalyticsHandler),
        (r"/api/attendance/qr", QRAttendanceHandler),

        # ── Server-Sent Events (SSE fallback) ──
        (r"/api/sse", SSEHandler),

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

        # ── Wrap-up Tests ──
        (r"/api/wrapup-tests", WrapUpTestsHandler),
        (r"/api/wrapup-tests/(\d+)", WrapUpTestDetailHandler),
        (r"/api/wrapup-tests/(\d+)/questions", WrapUpQuestionsHandler),
        (r"/api/wrapup-questions/(\d+)", WrapUpQuestionDetailHandler),
        (r"/api/wrapup-tests/(\d+)/submit", WrapUpSubmitHandler),
        (r"/api/wrapup-tests/(\d+)/grade/(\d+)", WrapUpGradeHandler),

        # ── Assignments & Submissions ──
        (r"/api/assignment-submissions", AssignmentSubmissionsHandler),
        (r"/api/assignment-submissions/(\d+)/grade", AssignmentGradeHandler),

        # ── Digital Signatures ──
        (r"/api/digital-signatures", DigitalSignaturesHandler),
        (r"/api/digital-signatures/(\d+)/verify", DigitalSignatureVerifyHandler),

        # ── Counseling ──
        (r"/api/counseling", CounselingHandler),

        # ── User Extended Profile ──
        (r"/api/users/(\d+)/profile-ext", UserProfileExtHandler),

        # ── OJT Extended ──
        (r"/api/ojt/tasks/(\d+)/sub-tasks", OJTSubTasksHandler),
        (r"/api/ojt/sub-tasks/(\d+)", OJTSubTaskDetailHandler),
        (r"/api/ojt/programs/(\d+)/leaders", OJTLeadersHandler),
        (r"/api/ojt/leaders/(\d+)", OJTLeaderDetailHandler),
        (r"/api/ojt/training-specs", OJTTrainingSpecsHandler),
        (r"/api/ojt/training-specs/(\d+)", OJTTrainingSpecDetailHandler),
        (r"/api/ojt/eval-specs", OJTEvalSpecsHandler),
        (r"/api/ojt/eval-specs/(\d+)", OJTEvalSpecDetailHandler),
        (r"/api/ojt/pre-assignments", OJTPreAssignmentsHandler),
        (r"/api/ojt/pre-assignments/([0-9]+)/submit", OJTPreAssignmentSubmitHandler),
        (r"/api/ojt/venues", OJTVenuesHandler),
        (r"/api/ojt/venues/(\d+)", OJTVenueDetailHandler),
        (r"/api/ojt/announcements", OJTAnnouncementsHandler),
        (r"/api/ojt/announcements/(\d+)", OJTAnnouncementDetailHandler),
        (r"/api/ojt/survey-templates", OJTSurveyTemplatesHandler),
        (r"/api/ojt/survey-templates/(\d+)", OJTSurveyTemplateDetailHandler),
        (r"/api/ojt/survey-templates/(\d+)/items", OJTSurveyItemsHandler),
        (r"/api/ojt/survey-responses", OJTSurveyResponsesHandler),
        (r"/api/ojt/survey-results/(\d+)", OJTSurveyResultsHandler),
        (r"/api/ojt/schedules", OJTSchedulesHandler),
        (r"/api/ojt/schedules/(\d+)", OJTScheduleDetailHandler),
        (r"/api/ojt/training-results", OJTTrainingResultsHandler),
        (r"/api/ojt/training-results/(\d+)/approve", OJTApprovalHandler),
        (r"/api/ojt/training-results/(\d+)", OJTTrainingResultDetailHandler),
        (r"/api/ojt/programs/(\d+)/admins", OJTProgramAdminsHandler),
        (r"/api/ojt/program-admins/(\d+)", OJTProgramAdminDetailHandler),
        (r"/api/ojt/eval-templates", OJTEvalTemplateHandler),
        (r"/api/ojt/eval-templates/([0-9]+)", OJTEvalTemplateDetailHandler),
        (r"/api/ojt/eval-templates/bulk-apply", OJTEvalTemplateBulkApplyHandler),

        # ── Career Roadmap ──
        (r"/api/career-roadmap", CareerRoadmapHandler),
        (r"/api/career-roadmap/(\d+)", CareerRoadmapDetailHandler),
        (r"/api/career-roadmap/(\d+)/tasks", CareerRoadmapTasksHandler),
        (r"/api/career-roadmap-tasks/(\d+)/sub-tasks", CareerRoadmapSubTasksHandler),
        (r"/api/career-roadmap/progress", CareerRoadmapProgressHandler),

        # ── Work Schedules (근무 스케줄) ──
        (r"/api/work-schedules", WorkSchedulesHandler),
        (r"/api/work-schedules/(\d+)", WorkScheduleDetailHandler),
        (r"/api/work-schedules/summary", WorkScheduleSummaryHandler),

        # ── Audit Log ──
        (r"/api/audit-log", AuditLogHandler),

        # ── Backup ──
        (r"/api/admin/backup", BackupHandler),
        (r"/api/admin/backup/list", BackupListHandler),
        (r"/api/admin/backup/create", BackupCreateHandler),

        (r"/api/active-users", ActiveUsersHandler),
        (r"/api/access-logs", AccessLogsHandler),
        (r"/api/access-logs/unique-ips", AccessLogsUniqueIPsHandler),

        # ── WebSocket ──
        (r"/ws", ATMSWebSocketHandler),

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
