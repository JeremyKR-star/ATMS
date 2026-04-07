"""
ATMS WebSocket Handler
Real-time notification delivery via Tornado WebSocket.
"""
import json
import tornado.websocket
from auth import decode_token


# ── Connected clients registry ──
# Maps user_id -> set of WebSocket connections
_ws_clients = {}


def get_connected_count():
    """Return the number of unique users with active WebSocket connections."""
    return len(_ws_clients)


def broadcast_to_user(user_id, message_data):
    """Send a message to all WebSocket connections for a specific user.
    message_data should be a dict that will be JSON-serialized.
    """
    user_id = int(user_id)
    connections = _ws_clients.get(user_id, set())
    dead = set()
    msg = json.dumps(message_data)
    for ws in connections:
        try:
            ws.write_message(msg)
        except Exception:
            dead.add(ws)
    # Clean up dead connections
    for ws in dead:
        connections.discard(ws)
    if not connections:
        _ws_clients.pop(user_id, None)


def broadcast_to_roles(roles, message_data, db_func=None):
    """Send a message to all connected users with specific roles.
    roles: list of role strings like ['admin', 'instructor']
    db_func: callable that returns a db connection (get_db)
    """
    if not db_func:
        return
    try:
        db = db_func()
        placeholders = ','.join(['?' for _ in roles])
        rows = db.execute(
            "SELECT id FROM users WHERE role IN ({}) AND status='active'".format(placeholders),
            roles
        ).fetchall()
        db.close()
        for row in rows:
            broadcast_to_user(row[0], message_data)
    except Exception:
        pass


def broadcast_to_all(message_data):
    """Send a message to all connected WebSocket clients."""
    msg = json.dumps(message_data)
    for user_id, connections in list(_ws_clients.items()):
        dead = set()
        for ws in connections:
            try:
                ws.write_message(msg)
            except Exception:
                dead.add(ws)
        for ws in dead:
            connections.discard(ws)
        if not connections:
            _ws_clients.pop(user_id, None)


class ATMSWebSocketHandler(tornado.websocket.WebSocketHandler):
    """WebSocket handler for real-time ATMS notifications."""

    def check_origin(self, origin):
        """Allow all origins (same as CORS policy)."""
        return True

    def open(self):
        """Client connected - wait for auth message."""
        self.user_data = None
        self.authenticated = False

    def on_message(self, message):
        """Handle incoming messages from client."""
        try:
            data = json.loads(message)
        except (json.JSONDecodeError, TypeError):
            self.write_message(json.dumps({
                "type": "error",
                "message": "Invalid JSON"
            }))
            return

        msg_type = data.get("type", "")

        if msg_type == "auth":
            self._handle_auth(data)
        elif msg_type == "ping":
            self.write_message(json.dumps({"type": "pong"}))
        elif not self.authenticated:
            self.write_message(json.dumps({
                "type": "error",
                "message": "Authentication required. Send {type: 'auth', token: '...'}"
            }))

    def _handle_auth(self, data):
        """Authenticate the WebSocket connection using JWT token."""
        token = data.get("token", "")
        if not token:
            self.write_message(json.dumps({
                "type": "auth_error",
                "message": "Token required"
            }))
            return

        user = decode_token(token)
        if not user:
            self.write_message(json.dumps({
                "type": "auth_error",
                "message": "Invalid or expired token"
            }))
            return

        self.user_data = user
        self.authenticated = True
        user_id = user["user_id"]

        # Register this connection
        if user_id not in _ws_clients:
            _ws_clients[user_id] = set()
        _ws_clients[user_id].add(self)

        self.write_message(json.dumps({
            "type": "auth_success",
            "message": "Connected",
            "user_id": user_id
        }))

    def on_close(self):
        """Client disconnected - remove from registry."""
        if self.user_data:
            user_id = self.user_data["user_id"]
            connections = _ws_clients.get(user_id, set())
            connections.discard(self)
            if not connections:
                _ws_clients.pop(user_id, None)
