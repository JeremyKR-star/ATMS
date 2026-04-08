# ATMS Test Suite - Complete Guide

## Quick Start

```bash
# Install test dependencies
pip install -r requirements-test.txt

# Run all tests
pytest tests/

# Run with coverage report
pytest tests/ --cov=. --cov-report=html

# Run tests in parallel (faster)
pytest tests/ -n auto
```

## Test Suite Overview

**Total Test Files:** 8
**Total Test Cases:** 165+
**Average Test Runtime:** < 30 seconds
**Database:** SQLite in-memory (isolated, fast)

### Test Coverage Breakdown

| Module | Tests | Focus |
|--------|-------|-------|
| test_auth.py | 32 | Login, registration, tokens, rate limiting |
| test_courses.py | 24 | CRUD, modules, enrollment, filtering |
| test_schedules.py | 22 | Scheduling, attendance, conflict detection |
| test_evaluations.py | 17 | Assessment, grading, submission workflows |
| test_ojt.py | 21 | OJT programs, tasks, enrollment |
| test_content.py | 16 | Content CRUD, status, filtering |
| test_notifications.py | 17 | Notification management, read status |
| test_reports.py | 16 | Dashboard stats, analytics |

## Installation

### System Requirements
- Python 3.8 or higher
- pip package manager
- ~500MB disk space

### Step 1: Install Dependencies

```bash
cd /path/to/ATMS_System
pip install -r requirements-test.txt
```

### Step 2: Verify Installation

```bash
pytest --version
python -c "import tornado; print('Tornado OK')"
```

## Running Tests

### Basic Commands

```bash
# Run all tests
pytest tests/

# Run specific test file
pytest tests/test_auth.py

# Run specific test class
pytest tests/test_auth.py::TestLogin

# Run specific test
pytest tests/test_auth.py::TestLogin::test_login_with_valid_credentials
```

### Common Options

```bash
# Verbose output
pytest tests/ -v

# Very verbose (show test names and progress)
pytest tests/ -vv

# Show print statements
pytest tests/ -s

# Stop on first failure
pytest tests/ -x

# Run last failed
pytest tests/ --lf

# Run failed then all
pytest tests/ --ff

# Show slowest 10 tests
pytest tests/ --durations=10
```

### Coverage Reports

```bash
# HTML coverage report
pytest tests/ --cov=. --cov-report=html
# Open htmlcov/index.html in browser

# Terminal coverage summary
pytest tests/ --cov=. --cov-report=term-missing

# Coverage with specific threshold
pytest tests/ --cov=. --cov-fail-under=80
```

### Parallel Execution

```bash
# Run tests in parallel (requires pytest-xdist)
pytest tests/ -n auto

# Run with 4 workers
pytest tests/ -n 4

# Show test distribution
pytest tests/ -n 4 -v
```

## Detailed Test Documentation

### 1. Authentication Tests (test_auth.py)

**Classes:** TestLogin, TestRegistration, TestProfile, TestChangePassword, TestTokenGeneration, TestRateLimit

**Key Tests:**
- ✅ Login with valid/invalid credentials
- ✅ Password validation (length, complexity)
- ✅ User registration with role validation
- ✅ Profile updates with allowed fields
- ✅ Password change workflow
- ✅ JWT token generation/validation
- ✅ Rate limiting after failed attempts

**Example Run:**
```bash
pytest tests/test_auth.py -v
```

### 2. Course Tests (test_courses.py)

**Classes:** TestCourseCreation, TestCourseRetrieval, TestCourseModules, TestEnrollment

**Key Tests:**
- ✅ Course CRUD with role-based access
- ✅ Unique code validation
- ✅ Module sequencing
- ✅ Instructor assignment
- ✅ Trainee enrollment
- ✅ Duplicate prevention
- ✅ Search and filtering

**Example Run:**
```bash
pytest tests/test_courses.py::TestEnrollment -v
```

### 3. Schedule Tests (test_schedules.py)

**Classes:** TestScheduleCreation, TestScheduleRetrieval, TestConflictDetection, TestAttendance

**Key Tests:**
- ✅ Schedule creation with validation
- ✅ Date range filtering
- ✅ Conflict detection (time, room, instructor)
- ✅ Attendance recording (present/absent/late)
- ✅ Duplicate attendance prevention
- ✅ Attendance statistics

**Example Run:**
```bash
pytest tests/test_schedules.py::TestConflictDetection -v
```

### 4. Evaluation Tests (test_evaluations.py)

**Classes:** TestEvaluationCreation, TestEvaluationRetrieval, TestEvaluationSubmission, TestBulkEvaluation

**Key Tests:**
- ✅ Evaluation creation with required fields
- ✅ Submission recording
- ✅ Grading workflow
- ✅ Score updates
- ✅ Status transitions
- ✅ Bulk operations

**Example Run:**
```bash
pytest tests/test_evaluations.py::TestEvaluationSubmission -v
```

### 5. OJT Tests (test_ojt.py)

**Classes:** TestOJTProgramCreation, TestOJTTasks, TestOJTEnrollment, TestOJTEvaluation, TestOJTProgramManagement

**Key Tests:**
- ✅ Program CRUD
- ✅ Task sequencing
- ✅ Trainee enrollment
- ✅ Progress tracking
- ✅ OJT evaluations
- ✅ Program details with tasks

**Example Run:**
```bash
pytest tests/test_ojt.py -v
```

### 6. Content Tests (test_content.py)

**Classes:** TestContentCreation, TestContentRetrieval, TestContentUpdate, TestContentDeletion

**Key Tests:**
- ✅ Content creation (video, document, etc.)
- ✅ Status management (draft/published/archived)
- ✅ Filtering by type, status, course
- ✅ Search by title
- ✅ URL updates
- ✅ Archival

**Example Run:**
```bash
pytest tests/test_content.py::TestContentFiltering -v
```

### 7. Notification Tests (test_notifications.py)

**Classes:** TestNotificationCreation, TestNotificationRetrieval, TestNotificationRead, TestNotificationCounts

**Key Tests:**
- ✅ Notification creation (info, warning, error)
- ✅ Mark as read/unread
- ✅ Bulk read operations
- ✅ Filtering by type, status
- ✅ Count by status
- ✅ Related entity linking

**Example Run:**
```bash
pytest tests/test_notifications.py::TestNotificationRead -v
```

### 8. Report Tests (test_reports.py)

**Classes:** TestDashboardStats, TestCourseReports, TestAttendanceReports, TestTraineeReports, TestMonthlyStats

**Key Tests:**
- ✅ User and course counting
- ✅ Enrollment statistics
- ✅ Attendance rate calculation
- ✅ Average score computation
- ✅ Trainee performance summary
- ✅ Monthly trends

**Example Run:**
```bash
pytest tests/test_reports.py::TestDashboardStats -v
```

## Test Fixtures

All tests use fixtures defined in `conftest.py`:

### Database Fixtures
```python
@pytest.fixture
def database():
    """In-memory SQLite database (session-scoped)"""
    
@pytest.fixture
def admin_user(database):
    """Admin user with token"""
    
@pytest.fixture
def instructor_user(database):
    """Instructor user with token"""
    
@pytest.fixture
def trainee_user(database):
    """Trainee user with token"""
```

### Course Fixtures
```python
@pytest.fixture
def sample_course(database, instructor_user):
    """Sample course with instructor"""
    
@pytest.fixture
def sample_module(database, sample_course):
    """Module in sample course"""
```

### Schedule & OJT Fixtures
```python
@pytest.fixture
def sample_schedule(database, sample_course, instructor_user):
    """Schedule for sample course"""
    
@pytest.fixture
def sample_ojt_program(database):
    """OJT program"""
    
@pytest.fixture
def sample_ojt_task(database, sample_ojt_program):
    """Task in OJT program"""
```

## Test Patterns

### Positive Test (Should Succeed)
```python
def test_create_course_with_valid_data(self, database):
    """Test successful course creation."""
    db = get_db()
    cursor = db.execute(
        "INSERT INTO courses (code, name, type) VALUES (?, ?, ?)",
        ('COURSE1', 'Test Course', 'theory')
    )
    db.commit()
    course_id = cursor.lastrowid
    db.close()
    
    assert course_id > 0
```

### Negative Test (Should Fail)
```python
def test_create_course_without_code_fails(self, database):
    """Test course creation without code is rejected."""
    db = get_db()
    
    try:
        db.execute(
            "INSERT INTO courses (name, type) VALUES (?, ?)",
            ('Test', 'theory')
        )
        db.commit()
        assert False, "Should have failed"
    except Exception:
        pass  # Expected
    finally:
        db.close()
```

### Fixture Usage
```python
def test_with_fixtures(self, admin_user, sample_course):
    """Test using fixtures."""
    # admin_user is automatically created and in database
    assert admin_user['role'] == 'admin'
    assert sample_course['code'] == 'COURSE001'
```

## Debugging Tests

### Run with Debug Output
```bash
# Show all print statements and errors
pytest tests/test_auth.py::TestLogin::test_login_with_valid_credentials -s -vv

# Stop on first failure and drop to debugger
pytest tests/ -x --pdb

# Run last failed test
pytest --lf -s
```

### Add Debugging to Test
```python
def test_something(self):
    db = get_db()
    result = db.execute("SELECT * FROM users").fetchone()
    
    # Print for debugging
    print(f"Result: {result}")
    
    # Drop into debugger
    import pdb; pdb.set_trace()
    
    db.close()
```

### View Database State
```python
def test_debug_database(self, database):
    """Debug: inspect database state."""
    # Query the actual in-memory database
    cursor = database.execute("SELECT COUNT(*) as count FROM users")
    row = cursor.fetchone()
    print(f"Users in DB: {row}")
```

## Performance Testing

### Find Slowest Tests
```bash
pytest tests/ --durations=10
```

### Benchmark Test Execution
```bash
pytest tests/ --benchmark-only
```

### Profile Tests
```bash
pip install pytest-profiling
pytest tests/ --profile
```

## CI/CD Integration

### GitHub Actions
```yaml
name: Tests
on: [push, pull_request]

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v2
      - uses: actions/setup-python@v2
        with:
          python-version: '3.9'
      - run: pip install -r requirements-test.txt
      - run: pytest tests/ --cov --cov-report=xml
      - uses: codecov/codecov-action@v2
```

### GitLab CI
```yaml
test:
  image: python:3.9
  script:
    - pip install -r requirements-test.txt
    - pytest tests/ --cov
```

## Troubleshooting

### Common Issues

**Issue:** "No module named 'tornado'"
```bash
# Solution
pip install tornado>=6.0.0
```

**Issue:** "Database is locked"
```bash
# Solution: Use in-memory database (default in conftest.py)
# Already handled - all tests use :memory:
```

**Issue:** Tests fail with "fixture not found"
```bash
# Solution: Check conftest.py is in tests/ directory
ls -la tests/conftest.py
```

**Issue:** Tests modify each other's data
```bash
# Solution: Use proper fixture scope (default: function)
# Already handled - each test gets fresh database
```

**Issue:** "pytest: command not found"
```bash
# Solution
pip install pytest>=7.0.0
```

## Best Practices

1. **Always use fixtures** for setup/teardown
2. **One assertion per test** when possible
3. **Use descriptive test names** that explain what's tested
4. **Clean up resources** with try/finally
5. **Test both success and failure** cases
6. **Document complex test logic** with docstrings
7. **Keep tests independent** - no cross-test dependencies
8. **Mock external services** if needed
9. **Use parametrization** for similar tests
10. **Review test coverage** regularly

## Advanced Topics

### Parametrized Tests
```python
@pytest.mark.parametrize("role", ["admin", "instructor", "trainee"])
def test_with_different_roles(self, role):
    """Test with multiple roles."""
    assert role in ["admin", "instructor", "trainee"]
```

### Skip Tests
```python
@pytest.mark.skip(reason="Not implemented yet")
def test_future_feature(self):
    pass

@pytest.mark.skipif(os.environ.get('SKIP_SLOW'), reason="Slow test")
def test_slow_operation(self):
    pass
```

### Expected Failures
```python
@pytest.mark.xfail(reason="Known bug in database layer")
def test_known_issue(self):
    assert False  # Expected to fail
```

## Resources

- **Pytest Docs:** https://docs.pytest.org/
- **Tornado Testing:** https://www.tornadoweb.org/en/stable/testing.html
- **SQLite Docs:** https://www.sqlite.org/
- **Test Fixtures:** https://docs.pytest.org/en/stable/fixture.html

## Support

For issues or questions:
1. Check the [tests/README.md](tests/README.md) for detailed information
2. Review existing tests for examples
3. Check test output for specific error messages
4. Run with `-vv -s` for detailed debugging output

## Next Steps

1. ✅ Run test suite: `pytest tests/`
2. ✅ Check coverage: `pytest tests/ --cov`
3. ✅ Review failing tests: `pytest tests/ -x`
4. ✅ Extend tests: Add new test files
5. ✅ Integrate with CI/CD

---

**Test Suite Version:** 1.0.0
**Last Updated:** 2026-04-08
**Maintainer:** ATMS Development Team
