"""Photo Upload Routes"""
import os
import uuid
import tornado.web
from database import get_db
from auth import require_auth

UPLOAD_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "public", "uploads")


class PhotoUploadHandler(tornado.web.RequestHandler):
    """Handle photo uploads (multipart/form-data)."""

    def set_default_headers(self):
        self.set_header("Access-Control-Allow-Origin", "*")
        self.set_header("Access-Control-Allow-Methods", "POST,OPTIONS")
        self.set_header("Access-Control-Allow-Headers", "Content-Type,Authorization")

    def options(self):
        self.set_status(204)
        self.finish()

    @require_auth()
    def post(self):
        user_id = self.get_argument("user_id", None)
        if not user_id:
            user_id = self.current_user_data["user_id"]

        # Only admin can change others' photos
        if int(user_id) != self.current_user_data["user_id"] and self.current_user_data["role"] != "admin":
            self.set_status(403)
            self.write({"error": "Cannot change another user's photo"})
            return

        if "photo" not in self.request.files:
            self.set_status(400)
            self.write({"error": "No photo file uploaded"})
            return

        photo = self.request.files["photo"][0]
        ext = os.path.splitext(photo["filename"])[1].lower()
        if ext not in (".jpg", ".jpeg", ".png", ".gif", ".webp"):
            self.set_status(400)
            self.write({"error": "Invalid image format. Use JPG, PNG, GIF, or WebP"})
            return

        # Max 5MB
        if len(photo["body"]) > 5 * 1024 * 1024:
            self.set_status(400)
            self.write({"error": "File too large. Max 5MB"})
            return

        os.makedirs(UPLOAD_DIR, exist_ok=True)
        filename = f"user_{user_id}_{uuid.uuid4().hex[:8]}{ext}"
        filepath = os.path.join(UPLOAD_DIR, filename)

        with open(filepath, "wb") as f:
            f.write(photo["body"])

        photo_url = f"/uploads/{filename}"

        db = get_db()
        # Delete old photo file if exists
        old = db.execute("SELECT photo_url FROM users WHERE id = ?", (user_id,)).fetchone()
        if old and old[0]:
            old_path = os.path.join(UPLOAD_DIR, os.path.basename(old[0]))
            if os.path.exists(old_path):
                try:
                    os.remove(old_path)
                except OSError:
                    pass

        db.execute("UPDATE users SET photo_url = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?", (photo_url, user_id))
        db.commit()
        db.close()

        self.set_header("Content-Type", "application/json")
        self.write({"success": True, "data": {"photo_url": photo_url}, "message": "Photo uploaded"})
