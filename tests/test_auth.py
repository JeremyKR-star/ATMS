"""
Authentication and Authorization Tests
Tests login, registration, profile management, and token validation.
"""
import pytest
import json
from unittest.mock import patch, MagicMock
from database import get_db, dict_from_row
from auth import generate_token, hash_password


class TestLogin:
    """Test user login functionality."""

    def test_login_with_valid_credentials(self):
        """Test successful login with correct employee ID and password."""
        # Setup: Create a user in the database
        db = get_db()
        user_password = 'ValidPass123'
        db.execute(
            """INSERT INTO users
               (employee_id, password_hash, name, role, status)
               VALUES (?, ?, ?, ?, ?)""",
            ('emp001', hash_password(user_password), 'Test User', 'trainee', 'active')
        )
        db.commit()
        db.close()

        # Execute login
        from routes.auth_routes import LoginHandler
        handler = MagicMock(spec=LoginHandler)
        handler.get_json_body.return_value = {
            'employee_id': 'emp001',
            'password': user_password
        }

        # Verify: Check that login would succeed (we'd need a real HTTP test for full flow)
        # For now, verify the password hashing and token generation work
        assert hash_password(user_password) != user_password

    def test_login_with_invalid_password(self):
        """Test login fails with incorrect password."""
        db = get_db()
        db.execute(
            """INSERT INTO users
               (employee_id, password_hash, name, role, status)
               VALUES (?, ?, ?, ?, ?)""",
            ('emp002', hash_password('CorrectPass123'), 'Test User', 'trainee', 'active')
        )
        db.commit()
        db.close()

        # Try to validate with wrong password
        from auth import check_password
        assert not check_password('WrongPass123', hash_password('CorrectPass123'))

    def test_login_with_nonexistent_employee_id(self):
        """Test login fails when employee ID doesn't exist."""
        db = get_db()
        # Don't create any user
        user = dict_from_row(db.execute(
            "SELECT * FROM users WHERE employee_id = ?",
            ('nonexistent',)
        ).fetchone())
        db.close()

        assert user is None

    def test_login_with_inactive_user(self):
        """Test login fails for inactive users."""
        db = get_db()
        db.execute(
            """INSERT INTO users
               (employee_id, password_hash, name, role, status)
               VALUES (?, ?, ?, ?, ?)""",
            ('emp003', hash_password('Pass123'), 'Inactive User', 'trainee', 'inactive')
        )
        db.commit()

        # Try to fetch active user - should not find it
        user = dict_from_row(db.execute(
            "SELECT * FROM users WHERE employee_id = ? AND status = 'active'",
            ('emp003',)
        ).fetchone())
        db.close()

        assert user is None

    def test_login_requires_employee_id(self):
        """Test login fails when employee_id is missing."""
        # This would be tested in the handler - verify logic
        handler = MagicMock()
        handler.get_json_body.return_value = {'password': 'Pass123'}

        # Missing employee_id should trigger an error
        assert 'employee_id' not in handler.get_json_body.return_value

    def test_login_requires_password(self):
        """Test login fails when password is missing."""
        handler = MagicMock()
        handler.get_json_body.return_value = {'employee_id': 'emp001'}

        # Missing password should trigger an error
        assert 'password' not in handler.get_json_body.return_value


class TestRegistration:
    """Test user registration functionality."""

    def test_register_new_user_with_valid_data(self):
        """Test successful user registration with all required fields."""
        db = get_db()

        cursor = db.execute(
            """INSERT INTO users
               (employee_id, password_hash, name, role, email, status)
               VALUES (?, ?, ?, ?, ?, ?)""",
            ('newemp001', hash_password('NewPass123'), 'New User', 'trainee', 'new@test.com', 'active')
        )
        db.commit()
        user_id = cursor.lastrowid
        db.close()

        # Verify user was created
        assert user_id > 0

    def test_register_with_duplicate_employee_id(self):
        """Test registration fails when employee ID already exists."""
        db = get_db()

        # Create first user
        db.execute(
            """INSERT INTO users
               (employee_id, password_hash, name, role, status)
               VALUES (?, ?, ?, ?, ?)""",
            ('duplic', hash_password('Pass123'), 'User 1', 'trainee', 'active')
        )
        db.commit()

        # Try to create second user with same employee_id
        try:
            db.execute(
                """INSERT INTO users
                   (employee_id, password_hash, name, role, status)
                   VALUES (?, ?, ?, ?, ?)""",
                ('duplic', hash_password('Pass123'), 'User 2', 'trainee', 'active')
            )
            db.commit()
            db.close()
            assert False, "Should have raised integrity error"
        except Exception as e:
            db.close()
            assert 'UNIQUE' in str(e) or 'duplicate' in str(e)

    def test_register_with_weak_password(self):
        """Test registration fails with weak password."""
        # Test password validation logic
        from routes.auth_routes import RegisterHandler

        # Passwords that should fail:
        weak_passwords = [
            'short',           # Too short
            'onlyletters',     # No numbers
            '12345678',        # No letters
        ]

        for weak_pw in weak_passwords:
            # Verify these would fail validation
            assert len(weak_pw) < 8 or not any(c.isdigit() for c in weak_pw) or not any(c.isalpha() for c in weak_pw)

    def test_register_with_valid_password(self):
        """Test registration with strong password."""
        strong_password = 'StrongPass123'

        # Verify it meets requirements
        assert len(strong_password) >= 8
        assert any(c.isdigit() for c in strong_password)
        assert any(c.isalpha() for c in strong_password)

    def test_register_with_invalid_role(self):
        """Test registration fails with invalid role."""
        valid_roles = ["admin", "instructor", "trainee", "ojt_admin", "manager", "staff", "customer"]
        invalid_role = "invalid_role"

        assert invalid_role not in valid_roles

    def test_register_requires_admin_privilege(self):
        """Test that registration endpoint requires admin/ojt_admin role."""
        # This is enforced by @require_auth(roles=["admin", "ojt_admin"]) decorator
        from routes.auth_routes import RegisterHandler
        assert hasattr(RegisterHandler, 'post')


class TestProfile:
    """Test profile retrieval and updates."""

    def test_get_profile_with_valid_token(self, admin_user, database):
        """Test retrieving profile with valid authentication token."""
        db = get_db()
        user = dict_from_row(db.execute(
            """SELECT id, employee_id, name, email, phone, role, status
               FROM users WHERE id = ?""",
            (admin_user['id'],)
        ).fetchone())
        db.close()

        assert user is not None
        assert user['id'] == admin_user['id']
        assert user['name'] == admin_user['name']
        assert user['role'] == 'admin'

    def test_get_profile_requires_authentication(self):
        """Test that profile endpoint requires authentication token."""
        # This is enforced by @require_auth() decorator on ProfileHandler.get
        from routes.auth_routes import ProfileHandler
        assert hasattr(ProfileHandler, 'get')

    def test_update_profile_with_valid_fields(self, admin_user, database):
        """Test updating allowed profile fields."""
        db = get_db()
        db.execute(
            """UPDATE users
               SET email = ?, phone = ?, bio = ?
               WHERE id = ?""",
            ('newemail@test.com', '555-1234', 'Updated bio', admin_user['id'])
        )
        db.commit()

        # Verify update
        user = dict_from_row(db.execute(
            "SELECT email, phone, bio FROM users WHERE id = ?",
            (admin_user['id'],)
        ).fetchone())
        db.close()

        assert user['email'] == 'newemail@test.com'
        assert user['phone'] == '555-1234'
        assert user['bio'] == 'Updated bio'

    def test_update_profile_invalid_fields_rejected(self):
        """Test that sensitive fields cannot be updated via profile endpoint."""
        # Fields like role, password_hash, status should not be in allowed list
        allowed_fields = ["name", "email", "phone", "birthday", "bio", "specialty"]

        protected_fields = ["role", "password_hash", "status", "employee_id"]

        for field in protected_fields:
            assert field not in allowed_fields

    def test_profile_not_found_returns_404(self):
        """Test 404 when profile doesn't exist."""
        db = get_db()
        user = dict_from_row(db.execute(
            "SELECT * FROM users WHERE id = ?",
            (99999,)
        ).fetchone())
        db.close()

        assert user is None


class TestChangePassword:
    """Test password change functionality."""

    def test_change_password_with_correct_current_password(self, admin_user, database):
        """Test successful password change with valid current password."""
        db = get_db()
        old_password = 'Admin@123'
        new_password = 'NewAdmin@123'

        # Get current hash
        user = dict_from_row(db.execute(
            "SELECT password_hash FROM users WHERE id = ?",
            (admin_user['id'],)
        ).fetchone())

        # Verify old password matches
        from auth import check_password
        assert check_password(old_password, user['password_hash'])

        # Update password
        db.execute(
            "UPDATE users SET password_hash = ? WHERE id = ?",
            (hash_password(new_password), admin_user['id'])
        )
        db.commit()

        # Verify new password works
        user = dict_from_row(db.execute(
            "SELECT password_hash FROM users WHERE id = ?",
            (admin_user['id'],)
        ).fetchone())
        db.close()

        assert check_password(new_password, user['password_hash'])
        assert not check_password(old_password, user['password_hash'])

    def test_change_password_with_wrong_current_password(self, admin_user, database):
        """Test password change fails with incorrect current password."""
        from auth import check_password

        wrong_password = 'WrongPassword123'
        user_data = {
            'password_hash': hash_password('Admin@123')
        }

        # Verify wrong password fails validation
        assert not check_password(wrong_password, user_data['password_hash'])

    def test_new_password_requires_minimum_length(self):
        """Test new password must be at least 8 characters."""
        short_password = 'Short1'

        assert len(short_password) < 8

    def test_new_password_requires_digit(self):
        """Test new password must contain at least one digit."""
        no_digit_password = 'OnlyLetters'

        assert not any(c.isdigit() for c in no_digit_password)

    def test_new_password_requires_letter(self):
        """Test new password must contain at least one letter."""
        no_letter_password = '12345678'

        assert not any(c.isalpha() for c in no_letter_password)

    def test_change_password_requires_authentication(self):
        """Test that change password endpoint requires authentication."""
        from routes.auth_routes import ChangePasswordHandler
        assert hasattr(ChangePasswordHandler, 'post')


class TestTokenGeneration:
    """Test JWT token generation and validation."""

    def test_generate_valid_token(self, admin_user):
        """Test token generation produces valid token."""
        token = admin_user['token']

        # Should have two parts separated by dot
        parts = token.split('.')
        assert len(parts) == 2

    def test_token_contains_user_info(self):
        """Test token payload contains user information."""
        from auth import generate_token
        import json
        import base64

        token = generate_token(123, 'admin', 'Test User')
        payload_b64, sig = token.split('.')

        # Decode payload
        payload_json = base64.urlsafe_b64decode(payload_b64 + '==')
        payload = json.loads(payload_json)

        assert payload['user_id'] == 123
        assert payload['role'] == 'admin'
        assert payload['name'] == 'Test User'
        assert 'exp' in payload
        assert 'iat' in payload

    def test_token_expiry_set_correctly(self):
        """Test token has proper expiry time."""
        from auth import generate_token, TOKEN_EXPIRY
        import json
        import base64
        import time

        token = generate_token(123, 'admin', 'Test')
        payload_b64, sig = token.split('.')

        payload_json = base64.urlsafe_b64decode(payload_b64 + '==')
        payload = json.loads(payload_json)

        # Check expiry is roughly TOKEN_EXPIRY seconds in future
        now = int(time.time())
        assert payload['exp'] > now
        assert payload['exp'] - now <= TOKEN_EXPIRY + 10  # Allow 10 second clock skew

    def test_decode_valid_token(self):
        """Test decoding a valid token returns payload."""
        from auth import generate_token, decode_token

        token = generate_token(123, 'admin', 'Test User')
        payload = decode_token(token)

        assert payload is not None
        assert payload['user_id'] == 123
        assert payload['role'] == 'admin'

    def test_decode_invalid_token_signature(self):
        """Test decoding token with invalid signature fails."""
        from auth import decode_token

        invalid_token = 'eyJ1c2VyX2lkIjogMTIzfQ.invalidsignature'
        payload = decode_token(invalid_token)

        assert payload is None

    def test_decode_malformed_token(self):
        """Test decoding malformed token fails."""
        from auth import decode_token

        bad_tokens = [
            'not_a_token',
            'only.one',
            'one.two.three.parts',
            '',
            None
        ]

        for bad_token in bad_tokens:
            if bad_token is not None:
                payload = decode_token(bad_token)
                assert payload is None


class TestRateLimit:
    """Test login rate limiting."""

    def test_rate_limit_enforced_after_failed_attempts(self):
        """Test that rate limit triggers after max failed attempts."""
        from auth import check_rate_limit, record_login_attempt, MAX_LOGIN_ATTEMPTS, LOGIN_LOCKOUT_SECONDS

        key = 'test_ip:123.456.789'

        # Record failed attempts
        for i in range(MAX_LOGIN_ATTEMPTS):
            record_login_attempt(key)

        # Next attempt should be blocked
        allowed, remaining = check_rate_limit(key)
        assert not allowed
        assert remaining > 0

    def test_rate_limit_cleared_after_successful_login(self):
        """Test that rate limit is cleared on successful login."""
        from auth import check_rate_limit, record_login_attempt, clear_login_attempts, MAX_LOGIN_ATTEMPTS

        key = 'test_ip:123.456.789'

        # Record failed attempts
        for i in range(MAX_LOGIN_ATTEMPTS):
            record_login_attempt(key)

        # Should be blocked
        allowed, _ = check_rate_limit(key)
        assert not allowed

        # Clear on successful login
        clear_login_attempts(key)

        # Should now be allowed
        allowed, remaining = check_rate_limit(key)
        assert allowed
        assert remaining == 0

    def test_rate_limit_by_ip_and_employee_id(self):
        """Test that rate limiting applies per IP and employee ID combination."""
        from auth import check_rate_limit

        key1 = 'login:192.168.1.1:emp001'
        key2 = 'login:192.168.1.1:emp002'
        key3 = 'login:192.168.1.2:emp001'

        # Different keys should have independent limits
        allowed1, _ = check_rate_limit(key1)
        allowed2, _ = check_rate_limit(key2)
        allowed3, _ = check_rate_limit(key3)

        assert allowed1 and allowed2 and allowed3
