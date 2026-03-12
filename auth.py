"""
ATMS Authentication Module
Token generation/validation and password hashing.
Uses only Python standard library (no external dependencies).
"""
import hashlib
import hmac
import base64
import time
import functools
import json
import os
import threading

# ── Secret key: use environment variable or generate a random one per startup ──
SECRET_KEY = os.environ.get("ATMS_SECRET_KEY", "")
if not SECRET_KEY:
    SECRET_KEY = base64.urlsafe_b64encode(os.urandom(32)).decode()
    print("[AUTH] WARNING: No ATMS_SECRET_KEY env var set. Generated random key (tokens will invalidate on restart).")

TOKEN_EXPIRY = 86400 * 7  # 7 days

# ── Rate Limiting ──
_login_attempts = {}  # {ip_or_employee_id: [timestamp, timestamp, ...]}
_login_lock = threading.Lock()
MAX_LOGIN_ATTEMPTS = 5
LOGIN_LOCKOUT_SECONDS = 300  # 5 minutes


def check_rate_limit(key):
    """Check if a login key (IP or employee_id) is rate-limited. Returns (allowed, seconds_remaining)."""
    now = time.time()
    with _login_lock:
        if key not in _login_attempts:
            return True, 0
        # Clean old attempts outside window
        _login_attempts[key] = [t for t in _login_attempts[key] if now - t < LOGIN_LOCKOUT_SECONDS]
        if len(_login_attempts[key]) >= MAX_LOGIN_ATTEMPTS:
            oldest = _login_attempts[key][0]
            remaining = int(LOGIN_LOCKOUT_SECONDS - (now - oldest))
            return False, max(remaining, 1)
        return True, 0


def record_login_attempt(key):
    """Record a failed login attempt."""
    with _login_lock:
        if key not in _login_attempts:
            _login_attempts[key] = []
        _login_attempts[key].append(time.time())


def clear_login_attempts(key):
    """Clear login attempts on successful login."""
    with _login_lock:
        _login_attempts.pop(key, None)


def hash_password(password: str) -> str:
    """Hash a password using PBKDF2-SHA256 (stdlib)."""
    salt = os.urandom(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 100000)
    return base64.b64encode(salt + dk).decode("utf-8")


def check_password(password: str, hashed: str) -> bool:
    """Verify a password against its PBKDF2 hash."""
    try:
        raw = base64.b64decode(hashed.encode("utf-8"))
        salt = raw[:16]
        stored_dk = raw[16:]
        dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 100000)
        return hmac.compare_digest(dk, stored_dk)
    except Exception:
        return False


def generate_token(user_id: int, role: str, name: str) -> str:
    """Generate an HMAC-signed token (no JWT dependency)."""
    payload = {
        "user_id": user_id,
        "role": role,
        "name": name,
        "exp": int(time.time()) + TOKEN_EXPIRY,
        "iat": int(time.time()),
    }
    payload_b64 = base64.urlsafe_b64encode(json.dumps(payload).encode()).decode()
    sig = hmac.new(SECRET_KEY.encode(), payload_b64.encode(), hashlib.sha256).hexdigest()
    return f"{payload_b64}.{sig}"


def decode_token(token: str) -> dict:
    """Decode and validate an HMAC-signed token. Returns payload or None."""
    try:
        parts = token.split(".")
        if len(parts) != 2:
            return None
        payload_b64, sig = parts
        expected_sig = hmac.new(SECRET_KEY.encode(), payload_b64.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(sig, expected_sig):
            return None
        payload = json.loads(base64.urlsafe_b64decode(payload_b64.encode()).decode())
        if payload.get("exp", 0) < time.time():
            return None
        return payload
    except Exception:
        return None


def get_current_user(handler):
    """Extract current user from request Authorization header."""
    auth = handler.request.headers.get("Authorization", "")
    if auth.startswith("Bearer "):
        token = auth[7:]
        return decode_token(token)
    return None


def require_auth(roles=None):
    """Decorator to require authentication and optional role check."""
    def decorator(method):
        @functools.wraps(method)
        def wrapper(self, *args, **kwargs):
            user = get_current_user(self)
            if not user:
                self.set_status(401)
                self.write({"error": "Authentication required"})
                return
            if roles and user.get("role") not in roles:
                self.set_status(403)
                self.write({"error": "Insufficient permissions"})
                return
            self.current_user_data = user
            return method(self, *args, **kwargs)
        return wrapper
    return decorator
