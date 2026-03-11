"""Content & Learning Materials Routes"""
from routes.auth_routes import BaseHandler
from database import get_db, dict_from_row, dicts_from_rows
from auth import require_auth


class ContentHandler(BaseHandler):
    @require_auth()
    def get(self):
        course_id = self.get_argument("course_id", None)
        content_type = self.get_argument("content_type", None)
        status = self.get_argument("status", "active")

        db = get_db()
        query = """
            SELECT ct.*, c.name as course_name, u.name as uploader_name,
                   cm.name as module_name
            FROM content ct
            LEFT JOIN courses c ON ct.course_id = c.id
            LEFT JOIN users u ON ct.uploaded_by = u.id
            LEFT JOIN course_modules cm ON ct.module_id = cm.id
            WHERE 1=1
        """
        params = []
        if course_id:
            query += " AND ct.course_id = ?"
            params.append(course_id)
        if content_type:
            query += " AND ct.content_type = ?"
            params.append(content_type)
        if status:
            query += " AND ct.status = ?"
            params.append(status)
        query += " ORDER BY ct.created_at DESC"
        items = dicts_from_rows(db.execute(query, params).fetchall())
        db.close()
        self.success(items)

    @require_auth(roles=["admin", "instructor", "ojt_admin"])
    def post(self):
        body = self.get_json_body()
        if not body.get("title") or not body.get("content_type"):
            return self.error("title and content_type are required")

        db = get_db()
        cur = db.execute("""
            INSERT INTO content (course_id, module_id, title, content_type, description, file_path, uploaded_by, status)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (body.get("course_id"), body.get("module_id"), body["title"],
              body["content_type"], body.get("description", ""),
              body.get("file_path", ""), self.current_user_data["user_id"],
              body.get("status", "active")))
        db.commit()
        cid = cur.lastrowid
        db.close()
        self.success({"id": cid}, "Content added")


class ContentDetailHandler(BaseHandler):
    @require_auth()
    def get(self, content_id):
        db = get_db()
        item = dict_from_row(db.execute("""
            SELECT ct.*, c.name as course_name, u.name as uploader_name
            FROM content ct
            LEFT JOIN courses c ON ct.course_id = c.id
            LEFT JOIN users u ON ct.uploaded_by = u.id
            WHERE ct.id = ?
        """, (content_id,)).fetchone())
        db.close()
        if not item:
            return self.error("Content not found", 404)
        self.success(item)

    @require_auth(roles=["admin", "instructor", "ojt_admin"])
    def put(self, content_id):
        body = self.get_json_body()
        allowed = ["title", "description", "content_type", "file_path", "status", "course_id", "module_id"]
        updates = {k: body[k] for k in allowed if k in body}
        if not updates:
            return self.error("No valid fields")

        set_clause = ", ".join(f"{k} = ?" for k in updates)
        values = list(updates.values()) + [content_id]
        db = get_db()
        db.execute(f"UPDATE content SET {set_clause}, updated_at = CURRENT_TIMESTAMP WHERE id = ?", values)
        db.commit()
        db.close()
        self.success(None, "Content updated")

    @require_auth(roles=["admin", "instructor"])
    def delete(self, content_id):
        db = get_db()
        db.execute("UPDATE content SET status = 'archived', updated_at = CURRENT_TIMESTAMP WHERE id = ?", (content_id,))
        db.commit()
        db.close()
        self.success(None, "Content archived")
