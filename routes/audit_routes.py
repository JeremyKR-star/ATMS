"""Audit Log Routes - Track all user actions and changes"""
import json
from datetime import datetime
from routes.auth_routes import BaseHandler
from database import get_db, dicts_from_rows
from auth import require_auth


def log_audit(handler, action, target_type, target_id, details=''):
    """
    Helper function to log audit events.
    Call this from other routes to track changes.
    
    Args:
        handler: The request handler (for IP and user info)
        action: 'create', 'update', 'delete', etc.
        target_type: 'pilot', 'mechanic', 'course', 'schedule', 'user', 'evaluation', etc.
        target_id: ID of the affected resource (or None for bulk operations)
        details: JSON string or dict with additional details (changed fields, etc.)
    """
    try:
        # Get client IP
        forwarded = handler.request.headers.get("X-Forwarded-For", "")
        ip_address = forwarded.split(",")[0].strip() if forwarded else handler.request.remote_ip
        
        # Get current user
        user_name = None
        try:
            from auth import get_current_user
            user = get_current_user(handler)
            if user:
                user_name = user.get('name')
        except Exception:
            pass
        
        # Convert details to JSON string if it's a dict
        if isinstance(details, dict):
            details = json.dumps(details, ensure_ascii=False)
        elif not details:
            details = None
        
        db = get_db()
        db.execute("""
            INSERT INTO audit_log (user_name, action, target_type, target_id, details, ip_address)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (user_name, action, target_type, target_id, details, ip_address))
        db.commit()
        db.close()
    except Exception as e:
        # Don't break the main operation if audit logging fails
        print(f"[AUDIT] Error logging audit event: {e}")


class AuditLogHandler(BaseHandler):
    """List audit logs with optional filtering"""
    
    @require_auth(roles=["admin"])
    def get(self):
        """
        Get audit logs with optional filters:
        - target_type: filter by resource type
        - action: filter by action (create, update, delete)
        - user_name: filter by user
        - date_from: filter from date (YYYY-MM-DD)
        - date_to: filter to date (YYYY-MM-DD)
        - limit: max records (default 100)
        - offset: skip records (default 0)
        """
        # Get query parameters
        target_type = self.get_argument("target_type", None)
        action = self.get_argument("action", None)
        user_name = self.get_argument("user_name", None)
        date_from = self.get_argument("date_from", None)
        date_to = self.get_argument("date_to", None)
        
        try:
            limit = int(self.get_argument("limit", "100"))
            offset = int(self.get_argument("offset", "0"))
        except ValueError:
            limit = 100
            offset = 0
        
        db = get_db()
        
        # Build query
        query = "SELECT * FROM audit_log WHERE 1=1"
        params = []
        
        if target_type:
            query += " AND target_type = ?"
            params.append(target_type)
        
        if action:
            query += " AND action = ?"
            params.append(action)
        
        if user_name:
            query += " AND user_name = ?"
            params.append(user_name)
        
        if date_from:
            query += " AND DATE(created_at) >= ?"
            params.append(date_from)
        
        if date_to:
            query += " AND DATE(created_at) <= ?"
            params.append(date_to)
        
        # Count total
        count_query = f"SELECT COUNT(*) as cnt FROM ({query})"
        total = db.execute(count_query, params).fetchone()['cnt']
        
        # Add ordering and limit
        query += " ORDER BY created_at DESC LIMIT ? OFFSET ?"
        params.extend([limit, offset])
        
        logs = dicts_from_rows(db.execute(query, params).fetchall())
        db.close()
        
        # Parse details JSON if present
        for log in logs:
            if log.get('details'):
                try:
                    log['details'] = json.loads(log['details'])
                except json.JSONDecodeError:
                    pass
        
        self.success({
            "logs": logs,
            "total": total,
            "limit": limit,
            "offset": offset
        })
