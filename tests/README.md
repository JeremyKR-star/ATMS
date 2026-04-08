# ATMS Test Suite

Comprehensive automated test suite for the Advanced Training Management System (ATMS) using pytest and SQLite in-memory databases.

## Overview

The test suite provides:
- **10 test modules** covering all major features
- **100+ test cases** with positive and negative scenarios
- **In-memory SQLite database** for fast, isolated testing
- **Pytest fixtures** for common setup (users, courses, schedules, etc.)
- **Role-based access control** testing
- **Database constraint** validation

## Test Coverage

### 1. Authentication & Authorization (`test_auth.py`)
- Login with valid/invalid credentials
- User registration with validation
- Profile retrieval and updates
- Password change with requirements
- Token generation and validation
- Rate limiting and lockout

**Test Count:** 25+ tests

### 2. Course Management (`test_courses.py`)
- Course CRUD operations
- Module management and sequencing
- Enrollment tracking
- Filtering by status/type/search
- Role-based access control
- Course details with related data

**Test Count:** 20+ tests

### 3. Schedules (`test_schedules.py`)
- Schedule creation with date/time validation
- Attendance recording (present/absent/late)
- Schedule conflict detection
- Date range filtering
- Instructor and room assignment
- Attendance statistics

**Test Count:** 22+ tests

### 4. Evaluations (`test_evaluations.py`)
- Evaluation creation and submission
- Scoring and grading workflows
- Status tracking (pending/submitted/graded)
- Bulk evaluation operations
- Filter by course/trainee/evaluator
- Feedback recording

**Test Count:** 18+ tests

### 5. OJT Programs (`test_ojt.py`)
- OJT program CRUD
- Task sequencing
- Trainee enrollment
- Progress tracking
- OJT-specific evaluations
- Task completion

**Test Count:** 20+ tests

### 6. Content Management (`test_content.py`)
- Content creation for courses/modules
- Status management (draft/published/archived)
- Content type filtering
- URL and description updates
- Creator tracking
- Search and filtering

**Test Count:** 18+ tests

### 7. Notifications (`test_notifications.py`)
- Notification creation with types
- Read/unread status tracking
- Filtering by type/user/status
- Related entity linking
- Bulk read operations
- Count and summary queries

**Test Count:** 20+ tests

### 8. Reports & Analytics (`test_reports.py`)
- Dashboard statistics
- Course enrollment reports
- Trainee performance summaries
- Attendance reports
- Monthly statistics
- Average calculations

**Test Count:** 18+ tests

## Installation

### Prerequisites
- Python 3.8+
- pip

### Setup

1. Install test dependencies:
```bash
pip install -r requirements-test.txt
```

2. Ensure main dependencies are installed:
```bash
pip install tornado
```

## Running Tests

### Run all tests:
```bash
pytest tests/
```

### Run specific test file:
```bash
pytest tests/test_auth.py
```

### Run specific test:
```bash
pytest tests/test_auth.py::TestLogin::test_login_with_valid_credentials
```

### Run with coverage report:
```bash
pytest tests/ --cov=. --cov-report=html
```

### Run in parallel (faster):
```bash
pytest tests/ -n auto
```

### Run with verbose output:
```bash
pytest tests/ -v
```

### Run with output capture disabled (for debugging):
```bash
pytest tests/ -s
```

## Test Structure

### conftest.py
Central fixture configuration providing:
- **database**: Session-scoped in-memory SQLite database
- **app**: Tornado test application
- **admin_user**: Pre-created admin user with token
- **instructor_user**: Pre-created instructor user
- **trainee_user**: Pre-created trainee user
- **sample_course**: Course with instructor
- **sample_module**: Module in sample course
- **sample_schedule**: Schedule with date/time
- **sample_ojt_program**: OJT program
- **sample_ojt_task**: Task in OJT program

### Test File Organization
Each test file contains multiple test classes:
- **TestClassName**: Groups related tests
- **test_method_name**: Individual test cases
- Descriptive docstrings explain what's tested

### Naming Conventions
- **test_positive_scenario**: Tests success cases
- **test_validates_requirement**: Tests data validation
- **test_requires_field**: Tests required fields
- **test_rejects_invalid**: Tests error handling
- **test_filter_by_field**: Tests filtering
- **test_with_role**: Tests role-based access

## Database Schema

Tests use an in-memory SQLite database with the following tables:
- users
- courses
- course_modules
- course_instructors
- enrollments
- schedules
- attendance
- evaluations
- evaluation_submissions
- ojt_programs
- ojt_tasks
- ojt_enrollments
- ojt_evaluations
- content
- notifications
- access_logs

## Key Testing Patterns

### 1. Fixture-Based Setup
```python
def test_something(database, admin_user, sample_course):
    db = get_db()
    # Use fixtures - they're already in database
```

### 2. Data Isolation
Each test gets a fresh session with fixtures. Tests don't interfere with each other.

### 3. Positive & Negative Tests
```python
def test_login_with_valid_credentials(self):
    # Positive: should work
    
def test_login_with_invalid_password(self):
    # Negative: should fail
```

### 4. Role-Based Testing
```python
def test_create_course_with_admin_role(self, admin_user):
    # Admin can create
    
def test_create_course_with_trainee_role_fails(self, trainee_user):
    # Trainee cannot create
```

## Common Test Assertions

```python
# Row exists
assert result is not None

# Value matches
assert user['name'] == 'Test User'

# Count matches
assert len(courses) >= 2

# List is empty
assert len(results) == 0

# Exception raised
with pytest.raises(Exception):
    db.execute(bad_query)
```

## Debugging Tests

### Print statement debugging:
```python
pytest tests/test_file.py::test_function -s
```

### Drop into debugger:
```python
import pdb; pdb.set_trace()
```

### View test details:
```python
pytest tests/ -v --tb=short
```

### Run single test with max verbosity:
```python
pytest tests/test_auth.py::TestLogin::test_login_with_valid_credentials -vv -s
```

## Extending Tests

### Add new test file:
1. Create `tests/test_feature.py`
2. Import fixtures from conftest
3. Create test classes and methods
4. Use consistent naming

### Add new fixture:
1. Add to `conftest.py`
2. Create the resource (user, course, etc.)
3. Document parameter needs
4. Use in test files

### Add new test:
```python
def test_new_feature_behavior(self, fixture_name):
    """Describe what's being tested."""
    # Setup
    db = get_db()
    
    # Execute
    result = db.execute(...).fetchone()
    
    # Assert
    assert result['field'] == expected_value
    
    db.close()
```

## Performance Considerations

- **In-memory database**: Tests run very fast (< 1 second per test)
- **No external dependencies**: No API calls or file I/O
- **Parallel execution**: Use `pytest -n auto` for 10x+ speedup
- **Session fixtures**: Database schema loaded once per session
- **Fresh data per test**: Each test has clean fixture data

## Continuous Integration

### GitHub Actions example:
```yaml
name: Tests
on: [push, pull_request]
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v2
      - uses: actions/setup-python@v2
      - run: pip install -r requirements-test.txt
      - run: pytest tests/ --cov
```

## Troubleshooting

### "No module named 'tornado'"
```bash
pip install tornado>=6.0.0
```

### "Database is locked"
- Tests should use in-memory database `:memory:`
- Check fixtures aren't creating file-based DB

### "Fixture not found"
- Ensure conftest.py is in tests/ directory
- Check fixture spelling matches parameter name

### Tests modify each other
- Should not happen with proper fixture scope
- Verify database fixture is properly isolated

## Contributing

When adding new features:
1. Write tests first (TDD)
2. Implement feature
3. Ensure tests pass
4. Check coverage
5. Add documentation

## Test Metrics

Target metrics:
- **Code coverage**: > 80%
- **Test execution time**: < 30 seconds
- **Pass rate**: 100%
- **Test count**: 1 test per 20 lines of code

## Resources

- [pytest documentation](https://docs.pytest.org/)
- [Tornado testing guide](https://www.tornadoweb.org/en/stable/testing.html)
- [SQLite documentation](https://www.sqlite.org/docs.html)
- [ATMS API Documentation](../API.md)

## License

Tests are part of the ATMS project.
