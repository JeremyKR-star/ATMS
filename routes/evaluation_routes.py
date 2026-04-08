"""Evaluation & Assessment Routes"""
from routes.auth_routes import BaseHandler
from database import get_db, dict_from_row, dicts_from_rows
from auth import require_auth

try:
    from websocket_handler import broadcast_to_user
except ImportError:
    broadcast_to_user = None

try:
    from email_utils import send_notification_email
except ImportError:
    send_notification_email = None


class EvaluationsHandler(BaseHandler):
    @require_auth()
    def get(self):
        course_id = self.get_argument("course_id", None)
        trainee_id = self.get_argument("trainee_id", None)
        evaluator_id = self.get_argument("evaluator_id", None)
        status = self.get_argument("status", None)
        eval_type = self.get_argument("eval_type", None)
        page = int(self.get_argument("page", 1))
        per_page = int(self.get_argument("per_page", 50))
        offset = (page - 1) * per_page

        db = get_db()
        query = """
            SELECT ev.*, c.name as course_name, u.name as trainee_name,
                   u2.name as evaluator_name, cm.name as module_name
            FROM evaluations ev
            JOIN courses c ON ev.course_id = c.id
            JOIN users u ON ev.trainee_id = u.id
            LEFT JOIN users u2 ON ev.evaluator_id = u2.id
            LEFT JOIN course_modules cm ON ev.module_id = cm.id
            WHERE 1=1
        """
        params = []
        if course_id:
            query += " AND ev.course_id = ?"
            params.append(course_id)
        if trainee_id:
            query += " AND ev.trainee_id = ?"
            params.append(trainee_id)
        if evaluator_id:
            query += " AND ev.evaluator_id = ?"
            params.append(evaluator_id)
        if status:
            query += " AND ev.status = ?"
            params.append(status)
        if eval_type:
            query += " AND ev.eval_type = ?"
            params.append(eval_type)

        # Count total before pagination
        count_q = query.replace("SELECT ev.*, c.name as course_name, u.name as trainee_name,\n                   u2.name as evaluator_name, cm.name as module_name", "SELECT COUNT(*)")
        total = db.execute(count_q, params).fetchone()[0]

        query += " ORDER BY ev.created_at DESC LIMIT ? OFFSET ?"
        params.extend([per_page, offset])
        evals = dicts_from_rows(db.execute(query, params).fetchall())
        db.close()
        self.success({"evaluations": evals, "pagination": {"page": page, "per_page": per_page, "total": total, "total_pages": (total + per_page - 1) // per_page}})

    @require_auth(roles=["admin", "instructor", "ojt_admin"])
    def post(self):
        body = self.get_json_body()
        required = ["course_id", "trainee_id", "eval_type", "title"]
        for f in required:
            if not body.get(f):
                return self.error(f"'{f}' is required")

        db = get_db()
        cur = db.execute("""
            INSERT INTO evaluations (course_id, module_id, trainee_id, evaluator_id, eval_type, title, max_score, due_date, status)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'pending')
        """, (body["course_id"], body.get("module_id"), body["trainee_id"],
              body.get("evaluator_id"), body["eval_type"], body["title"],
              body.get("max_score", 100), body.get("due_date")))
        db.commit()
        eid = cur.lastrowid
        db.close()
        self.success({"id": eid}, "Evaluation created")


class EvaluationDetailHandler(BaseHandler):
    @require_auth()
    def get(self, eval_id):
        db = get_db()
        ev = dict_from_row(db.execute("""
            SELECT ev.*, c.name as course_name, u.name as trainee_name, u2.name as evaluator_name
            FROM evaluations ev
            JOIN courses c ON ev.course_id = c.id
            JOIN users u ON ev.trainee_id = u.id
            LEFT JOIN users u2 ON ev.evaluator_id = u2.id
            WHERE ev.id = ?
        """, (eval_id,)).fetchone())
        db.close()
        if not ev:
            return self.error("Evaluation not found", 404)
        self.success(ev)

    @require_auth(roles=["admin", "instructor", "ojt_admin"])
    def put(self, eval_id):
        body = self.get_json_body()
        allowed = ["score", "grade", "feedback", "status"]
        updates = {k: body[k] for k in allowed if k in body}
        if not updates:
            return self.error("No valid fields")

        db = get_db()
        user = self.current_user_data

        # Check instructor is assigned to this course
        if user["role"] == "instructor":
            eval_data = dict_from_row(db.execute("SELECT course_id FROM evaluations WHERE id = ?", (eval_id,)).fetchone())
            if eval_data:
                ci = db.execute("SELECT id FROM course_instructors WHERE course_id = ? AND instructor_id = ?",
                                 (eval_data["course_id"], user["id"])).fetchone()
                if not ci:
                    db.close()
                    return self.error("You are not assigned to this course", 403)

        if "status" in updates and updates["status"] == "graded":
            set_clause = ", ".join(f"{k} = ?" for k in updates)
            values = list(updates.values()) + [eval_id]
            db.execute(f"UPDATE evaluations SET {set_clause}, graded_at = CURRENT_TIMESTAMP WHERE id = ?", values)
        else:
            set_clause = ", ".join(f"{k} = ?" for k in updates)
            values = list(updates.values()) + [eval_id]
            db.execute(f"UPDATE evaluations SET {set_clause} WHERE id = ?", values)

        db.commit()
        # Notify trainee when evaluation is graded
        if broadcast_to_user and "status" in updates and updates["status"] == "graded":
            try:
                ev = dict_from_row(db.execute("SELECT trainee_id, title FROM evaluations WHERE id = ?", (eval_id,)).fetchone())
                if ev:
                    broadcast_to_user(ev["trainee_id"], {
                        "type": "notification",
                        "data": {"title": "\uD3C9\uAC00 \uCC44\uC810 \uC644\uB8CC", "message": ev["title"], "notification_type": "success"}
                    })
            except Exception:
                pass
        db.close()
        self.success(None, "Evaluation updated")


class SubmitEvaluationHandler(BaseHandler):
    """Trainee submits an evaluation/assignment."""
    @require_auth(roles=["trainee"])
    def post(self, eval_id):
        db = get_db()
        ev = dict_from_row(db.execute("SELECT * FROM evaluations WHERE id = ? AND trainee_id = ?",
                                       (eval_id, self.current_user_data["user_id"])).fetchone())
        if not ev:
            db.close()
            return self.error("Evaluation not found", 404)

        db.execute("UPDATE evaluations SET status = 'submitted', submitted_at = CURRENT_TIMESTAMP WHERE id = ?", (eval_id,))
        db.commit()
        # Notify evaluator when trainee submits
        if broadcast_to_user and ev.get("evaluator_id"):
            try:
                broadcast_to_user(ev["evaluator_id"], {
                    "type": "notification",
                    "data": {"title": "\uD3C9\uAC00 \uC81C\uCD9C\uB428", "message": ev["title"], "notification_type": "info"}
                })
            except Exception:
                pass
        db.close()
        self.success(None, "Submitted successfully")


class BulkCreateEvaluationsHandler(BaseHandler):
    """Create evaluations for all enrolled trainees in a course."""
    @require_auth(roles=["admin", "instructor"])
    def post(self):
        body = self.get_json_body()
        course_id = body.get("course_id")
        eval_type = body.get("eval_type", "quiz")
        title = body.get("title", "")
        due_date = body.get("due_date")
        max_score = body.get("max_score", 100)

        if not course_id or not title:
            return self.error("course_id and title are required")

        db = get_db()
        trainees = db.execute(
            "SELECT trainee_id FROM enrollments WHERE course_id = ? AND status IN ('enrolled','in_progress')",
            (course_id,)
        ).fetchall()

        created = 0
        for t in trainees:
            db.execute("""
                INSERT INTO evaluations (course_id, trainee_id, evaluator_id, eval_type, title, max_score, due_date, status)
                VALUES (?, ?, ?, ?, ?, ?, ?, 'pending')
            """, (course_id, t[0], self.current_user_data["user_id"], eval_type, title, max_score, due_date))
            created += 1

        db.commit()
        db.close()
        self.success({"created": created}, f"Created {created} evaluations")


class TransferEvaluationHandler(BaseHandler):
    """Transfer/send evaluation results to a recipient (manager, officer, etc.)."""
    @require_auth(roles=["admin", "instructor", "manager", "ojt_admin"])
    def post(self, eval_id):
        body = self.get_json_body()
        recipient_id = body.get("recipient_id")

        if not recipient_id:
            return self.error("recipient_id is required")

        db = get_db()

        # Get evaluation details
        ev = dict_from_row(db.execute("""
            SELECT ev.*, c.name as course_name, u.name as trainee_name, u2.name as evaluator_name, u3.name as recipient_name
            FROM evaluations ev
            JOIN courses c ON ev.course_id = c.id
            JOIN users u ON ev.trainee_id = u.id
            LEFT JOIN users u2 ON ev.evaluator_id = u2.id
            LEFT JOIN users u3 ON u3.id = ?
            WHERE ev.id = ?
        """, (recipient_id, eval_id)).fetchone())

        if not ev:
            db.close()
            return self.error("Evaluation not found", 404)

        # Update evaluation status to 'transferred'
        current_user = self.current_user_data
        db.execute("""
            UPDATE evaluations
            SET status = 'transferred', transferred_at = CURRENT_TIMESTAMP, transferred_by = ?
            WHERE id = ?
        """, (current_user["user_id"], eval_id))
        db.commit()

        # Create notification for recipient
        try:
            notification_message = f"평가 '{ev['title']}'이(가) 전송되었습니다. 훈련생: {ev['trainee_name']}"
            db.execute("""
                INSERT INTO notifications (user_id, type, title, message, related_table, related_id, is_read)
                VALUES (?, ?, ?, ?, ?, ?, 0)
            """, (recipient_id, "evaluation_transfer", "평가 결과 전송", notification_message, "evaluations", eval_id))
            db.commit()
        except Exception as e:
            print(f"[TransferEvaluation] Notification creation failed: {e}")

        # Broadcast to recipient if available
        if broadcast_to_user:
            try:
                broadcast_to_user(recipient_id, {
                    "type": "notification",
                    "data": {
                        "title": "평가 결과 전송",
                        "message": notification_message,
                        "notification_type": "info"
                    }
                })
            except Exception:
                pass

        # Send email if available
        if send_notification_email:
            try:
                recipient = db.execute("SELECT email, name FROM users WHERE id = ?", (recipient_id,)).fetchone()
                if recipient and recipient.get("email"):
                    send_notification_email(
                        recipient["email"],
                        "평가 결과 전송",
                        f"평가 '{ev['title']}'이(가) 전송되었습니다.\n훈련생: {ev['trainee_name']}\n점수: {ev['score']}/{ev['max_score']}\n등급: {ev['grade'] or '-'}"
                    )
            except Exception as e:
                print(f"[TransferEvaluation] Email send failed: {e}")

        db.close()
        self.success(None, f"평가가 {ev.get('recipient_name', 'recipient')}에게 전송되었습니다")
