"""
ATMS Test Suite

This package contains comprehensive automated tests for the Advanced Training Management System.

Test modules:
- test_auth.py: Authentication, authorization, and token management
- test_courses.py: Course CRUD, enrollment, and module management
- test_schedules.py: Schedule creation, conflict detection, attendance recording
- test_evaluations.py: Evaluation CRUD, scoring, and grading workflows
- test_ojt.py: OJT program management, tasks, and enrollment
- test_content.py: Content management and filtering
- test_notifications.py: Notification creation and status tracking
- test_reports.py: Dashboard stats, reports, and analytics

Fixtures defined in conftest.py:
- database: In-memory SQLite database
- app: Tornado test application
- admin_user, instructor_user, trainee_user: Pre-created users
- sample_course, sample_module, sample_schedule: Common test resources
- sample_ojt_program, sample_ojt_task: OJT test resources

Run tests with: pytest tests/
"""

__version__ = "1.0.0"
__author__ = "ATMS Development Team"

# Silence import warnings during test collection
import warnings
warnings.filterwarnings("ignore", category=DeprecationWarning)
