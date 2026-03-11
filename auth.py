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

SECRET_KEY = "atms-secret-key-2026-change-in-production"
TOKEN_EXPIRY = 86400 * 7  # 7 days


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
