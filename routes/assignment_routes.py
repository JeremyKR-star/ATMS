"""Assignment Submission & Digital Signature Routes"""
import os
import time
from routes.auth_routes import BaseHandler
from database import get_db, dict_from_row, dicts_from_rows
from auth import require_auth

try:
    from websocket_handler import broadcast_to_user
except ImportError:
    broadcast_to_user = None


class AssignmentSubmissionsHandler(BaseHandler):
    @require_auth()
    def get(self):
        content_id = self.get_argument("content_id", None)
        trainee_id = self.get_argument("trainee_id", None)
        course_id = self.get_argument("course_id", None)
        status = self.get_argument("status", None)
        page = int(self.get_argument("page", "1"))
        per_page = int(self.get_argument("per_page", "50"))

        db = get_db()
        query = """
            SELECT asub.*, c.title as content_title, c.content_type,
                   u.name as trainee_name, u.employee_id,
                   u2.name as grader_name,
                   co.name as course_name
            FROM assignment_submissions asub
            JOIN content c ON asub.content_id = c.id
            JOIN users u ON asub.trainee_id = u.id
            LEFT JOIN users u2 ON asub.graded_by = u2.id
            LEFT JOIN courses co ON c.course_id = co.id
            WHERE 1=1
        """
        params = []
        if content_id:
            query += " AND asub.content_id = ?"
            params.append(content_id)
        if trainee_id:
            query += " AND asub.trainee_id = ?"
            params.append(trainee_id)
        if course_id:
            query += " AND c.course_id = ?"
            params.append(course_id)
        if status:
            query += " AND asub.status = ?"
            params.append(status)

        # Get total count
        count_query = "SELECT COUNT(*) as total FROM assignment_submissions asub JOIN content c ON asub.content_id = c.id JOIN users u ON asub.trainee_id = u.id LEFT JOIN users u2 ON asub.graded_by = u2.id LEFT JOIN courses co ON c.course_id = co.id WHERE 1=1"
        if content_id:
            count_query += " AND asub.content_id = ?"
        if trainee_id:
            count_query += " AND asub.trainee_id = ?"
        if course_id:
            count_query += " AND c.course_id = ?"
        if status:
            count_query += " AND asub.status = ?"

        total = db.execute(count_query, params).fetchone()[0]
        total_pages = (total + per_page - 1) // per_page

        # Add pagination
        query += " ORDER BY asub.submitted_at DESC"
        offset = (page - 1) * per_page
        query += " LIMIT ? OFFSET ?"
        params.append(per_page)
        params.append(offset)

        subs = dicts_from_rows(db.execute(query, params).fetchall())
        db.close()

        self.success({
            "submissions": subs,
            "pagination": {
                "page": page,
                "per_page": per_page,
                "total": total,
                "total_pages": total_pages
            }
        })

    @require_auth()
    def post(self):
        """Trainee submits an assignment (supports JSON and multipart/form-data)"""
        trainee_id = self.current_user_data["user_id"]
        file_path = ""
        submission_text = ""
        content_id = None

        # Check if this is a multipart/form-data submission
        if "assignment" in self.request.files:
            # Handle file upload
            content_id = self.get_argument("content_id", None)
            submission_text = self.get_argument("submission_text", "")

            if not content_id:
                return self.error("content_id is required")

            assignment_file = self.request.files["assignment"][0]
            filename = assignment_file["filename"]

            # Validate file
            if not filename:
                return self.error("File upload failed - no filename")

            # Max 50MB for assignment files
            if len(assignment_file["body"]) > 50 * 1024 * 1024:
                return self.error("File too large. Max 50MB")

            # Create upload directory
            upload_base = os.path.join(os.path.dirname(os.path.dirname(__file__)), "public", "uploads", "assignments")
            os.makedirs(upload_base, exist_ok=True)

            # Generate unique filename: timestamp + original filename
            timestamp = str(int(time.time() * 1000))
            filename_base = os.path.splitext(filename)[0]
            filename_ext = os.path.splitext(filename)[1]
            unique_filename = f"{timestamp}_{filename_base}{filename_ext}"
            filepath = os.path.join(upload_base, unique_filename)

            # Save file
            try:
                with open(filepath, "wb") as f:
                    f.write(assignment_file["body"])
                file_path = f"/uploads/assignments/{unique_filename}"
            except IOError as e:
                return self.error(f"Failed to save file: {str(e)}")
        else:
            # Handle JSON submission (original behavior)
            body = self.get_json_body()
            if not body.get("content_id"):
                return self.error("content_id is required")

            content_id = body["content_id"]
            file_path = body.get("file_path", "")
            submission_text = body.get("submission_text", "")

        db = get_db()
        try:
            db.execute("""
                INSERT INTO assignment_submissions (content_id, trainee_id, file_path, submission_text, status)
                VALUES (?, ?, ?, ?, 'submitted')
                ON CONFLICT (content_id, trainee_id) DO UPDATE SET
                    file_path = EXCLUDED.file_path, submission_text = EXCLUDED.submission_text,
                    status = 'submitted', submitted_at = CURRENT_TIMESTAMP
            """, (content_id, trainee_id, file_path, submission_text))
            db.commit()
        except Exception as e:
            db.rollback()
            return self.error(f"Database error: {str(e)}")
        finally:
            db.close()

        self.success({"file_path": file_path} if file_path else None, "Assignment submitted")


class AssignmentGradeHandler(BaseHandler):
    @require_auth(roles=["admin", "instructor", "ojt_admin"])
    def put(self, submission_id):
        """Instructor grades an assignment"""
        body = self.get_json_body()
        db = get_db()
        user = self.current_user_data

        # Check instructor is assigned to this course
        if user["role"] == "instructor":
            sub_data = dict_from_row(db.execute("""
                SELECT c.course_id FROM assignment_submissions asub
                JOIN content c ON asub.content_id = c.id
                WHERE asub.id = ?
            """, (submission_id,)).fetchone())
            if sub_data:
                ci = db.execute("SELECT id FROM course_instructors WHERE course_id = ? AND instructor_id = ?",
                                 (sub_data["course_id"], user["id"])).fetchone()
                if not ci:
                    db.close()
                    return self.error("You are not assigned to this course", 403)

        db.execute("""
            UPDATE assignment_submissions SET score = ?, feedback = ?, status = ?,
                graded_at = CURRENT_TIMESTAMP, graded_by = ?
            WHERE id = ?
        """, (body.get("score"), body.get("feedback", ""),
              body.get("status", "graded"), self.current_user_data["user_id"], submission_id))
        db.commit()
        # Notify trainee that their assignment has been graded
        if broadcast_to_user:
            try:
                sub = db.execute("SELECT trainee_id FROM assignment_submissions WHERE id = ?", (submission_id,)).fetchone()
                if sub:
                    broadcast_to_user(sub[0], {
                        "type": "notification",
                        "data": {
                            "title": "\uACFC\uC81C \uCC44\uC810 \uC644\uB8CC",
                            "message": str(body.get("score", "")) + "\uC810",
                            "notification_type": "success"
                        }
                    })
            except Exception:
                pass
        db.close()
        self.success(None, "Assignment graded")


class DigitalSignaturesHandler(BaseHandler):
    @require_auth()
    def get(self):
        trainee_id = self.get_argument("trainee_id", None)
        course_id = self.get_argument("course_id", None)

        db = get_db()
        query = """
            SELECT ds.*, u.name as trainee_name, c.name as course_name,
                   cm.name as module_name, u2.name as verifier_name
            FROM digital_signatures ds
            JOIN users u ON ds.trainee_id = u.id
            JOIN courses c ON ds.course_id = c.id
            LEFT JOIN course_modules cm ON ds.module_id = cm.id
            LEFT JOIN users u2 ON ds.verified_by = u2.id
            WHERE 1=1
        """
        params = []
        if trainee_id:
            query += " AND ds.trainee_id = ?"
            params.append(trainee_id)
        if course_id:
            query += " AND ds.course_id = ?"
            params.append(course_id)
        query += " ORDER BY ds.signed_at DESC"
        sigs = dicts_from_rows(db.execute(query, params).fetchall())
        db.close()
        self.success(sigs)

    @require_auth()
    def post(self):
        """Trainee submits a JPG signature"""
        body = self.get_json_body()
        required = ["course_id"]
        for f in required:
            if not body.get(f):
                return self.error(f"'{f}' is required")

        trainee_id = self.current_user_data["user_id"]
        db = get_db()
        cur = db.execute("""
            INSERT INTO digital_signatures (trainee_id, course_id, module_id, signature_data, signature_path, purpose, status)
            VALUES (?, ?, ?, ?, ?, ?, 'signed')
        """, (trainee_id, body["course_id"], body.get("module_id"),
              body.get("signature_data", ""), body.get("signature_path", ""),
              body.get("purpose", "course_completion")))
        db.commit()
        sid = cur.lastrowid
        db.close()
        self.success({"id": sid}, "Signature submitted")


class DigitalSignatureVerifyHandler(BaseHandler):
    @require_auth(roles=["admin", "instructor", "ojt_admin"])
    def put(self, sig_id):
        """Verify or reject a signature"""
        body = self.get_json_body()
        status = body.get("status", "verified")
        db = get_db()
        db.execute("""
            UPDATE digital_signatures SET status = ?, verified_by = ?, verified_at = CURRENT_TIMESTAMP
            WHERE id = ?
        """, (status, self.current_user_data["user_id"], sig_id))
        db.commit()
        db.close()
        self.success(None, "Signature " + status)


class CounselingHandler(BaseHandler):
    @require_auth()
    def get(self):
        trainee_id = self.get_argument("trainee_id", None)
        course_id = self.get_argument("course_id", None)

        db = get_db()
        query = """
            SELECT cr.*, u.name as trainee_name, u2.name as counselor_name, c.name as course_name
            FROM counseling_records cr
            JOIN users u ON cr.trainee_id = u.id
            JOIN users u2 ON cr.counselor_id = u2.id
            LEFT JOIN courses c ON cr.course_id = c.id
            WHERE 1=1
        """
        params = []
        if trainee_id:
            query += " AND cr.trainee_id = ?"
            params.append(trainee_id)
        if course_id:
            query += " AND cr.course_id = ?"
            params.append(course_id)
        query += " ORDER BY cr.counseling_date DESC"
        records = dicts_from_rows(db.execute(query, params).fetchall())
        db.close()
        self.success(records)

    @require_auth(roles=["admin", "instructor", "ojt_admin"])
    def post(self):
        body = self.get_json_body()
        if not body.get("trainee_id") or not body.get("topic"):
            return self.error("trainee_id and topic are required")

        db = get_db()
        cur = db.execute("""
            INSERT INTO counseling_records (trainee_id, counselor_id, course_id, topic, content, action_items, counseling_date)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (body["trainee_id"], self.current_user_data["user_id"],
              body.get("course_id"), body["topic"], body.get("content", ""),
              body.get("action_items", ""), body.get("counseling_date", "")))
        db.commit()
        cid = cur.lastrowid
        db.close()
        self.success({"id": cid}, "Counseling record created")


class UserProfileExtHandler(BaseHandler):
    """Extended user profile management"""
    @require_auth()
    def get(self, user_id):
        db = get_db()
        profile = dict_from_row(db.execute(
            "SELECT * FROM user_profiles WHERE user_id = ?", (user_id,)).fetchone())
        db.close()
        if not profile:
            return self.success({})
        self.success(profile)

    @require_auth()
    def put(self, user_id):
        body = self.get_json_body()
        allowed = ["major", "career_history", "qualifications", "pre_training",
                    "visa_info", "visa_expiry", "medical_check", "medical_check_date",
                    "military_number", "payroll", "gender", "date_of_birth",
                    "organization", "job_experience", "specialty_skill",
                    "equipment_issued", "rnr", "bio_data", "training_system"]
        updates = {k: body[k] for k in allowed if k in body}
        if not updates:
            return self.error("No valid fields")

        db = get_db()
        # Check if profile exists
        existing = db.execute("SELECT id FROM user_profiles WHERE user_id = ?", (user_id,)).fetchone()

        if existing:
            set_clause = ", ".join(f"{k} = ?" for k in updates)
            values = list(updates.values()) + [user_id]
            db.execute(f"UPDATE user_profiles SET {set_clause} WHERE user_id = ?", values)
        else:
            updates["user_id"] = user_id
            cols = ", ".join(updates.keys())
            placeholders = ", ".join(["?" for _ in updates])
            db.execute(f"INSERT INTO user_profiles ({cols}) VALUES ({placeholders})", list(updates.values()))

        db.commit()
        db.close()
        self.success(None, "Profile updated")
