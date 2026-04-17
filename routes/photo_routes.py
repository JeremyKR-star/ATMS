"""Photo Upload Routes - stores photos in database for persistence across Render restarts"""
import os
import tornado.web
from database import get_db
from auth import require_auth


class PhotoUploadHandler(tornado.web.RequestHandler):
    """Handle photo uploads (multipart/form-data) - stores in DB."""

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

        mime_map = {'.jpg': 'image/jpeg', '.jpeg': 'image/jpeg', '.png': 'image/png',
                    '.gif': 'image/gif', '.webp': 'image/webp'}
        mime_type = mime_map.get(ext, 'image/jpeg')
        photo_url = f"/api/users/{user_id}/photo"

        db = get_db()
        db.execute(
            "UPDATE users SET photo_data=?, photo_mime=?, photo_url=?, updated_at=CURRENT_TIMESTAMP WHERE id=?",
            (photo["body"], mime_type, photo_url, user_id)
        )
        db.commit()
        db.close()

        self.set_header("Content-Type", "application/json")
        self.write({"success": True, "data": {"photo_url": photo_url}, "message": "Photo uploaded"})


class UserPhotoHandler(tornado.web.RequestHandler):
    """GET serve user photo from database"""

    def get(self, user_id):
        db = get_db()
        row = db.execute("SELECT photo_data, photo_mime FROM users WHERE id=?", (user_id,)).fetchone()
        db.close()
        if not row or not row[0]:
            self.set_status(404)
            return self.finish()
        photo_data = row[0]
        if isinstance(photo_data, memoryview):
            photo_data = bytes(photo_data)
        self.set_header("Content-Type", row[1] or "image/jpeg")
        self.set_header("Cache-Control", "public, max-age=86400")
        self.write(photo_data)
        self.finish()
