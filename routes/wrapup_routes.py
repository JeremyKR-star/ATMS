"""Wrap-up Test Routes - Instructor creates daily tests, trainees take them"""
from routes.auth_routes import BaseHandler
from database import get_db, dict_from_row, dicts_from_rows
from auth import require_auth

try:
    from websocket_handler import broadcast_to_user
except ImportError:
    broadcast_to_user = None


class WrapUpTestsHandler(BaseHandler):
    @require_auth()
    def get(self):
        course_id = self.get_argument("course_id", None)
        instructor_id = self.get_argument("instructor_id", None)
        status = self.get_argument("status", None)

        db = get_db()
        query = """
            SELECT w.*, c.name as course_name, u.name as instructor_name,
                   cm.name as module_name,
                   (SELECT COUNT(*) FROM wrap_up_questions WHERE test_id = w.id) as question_count
            FROM wrap_up_tests w
            LEFT JOIN courses c ON w.course_id = c.id
            LEFT JOIN users u ON w.instructor_id = u.id
            LEFT JOIN course_modules cm ON w.module_id = cm.id
            WHERE 1=1
        """
        params = []
        if course_id:
            query += " AND w.course_id = ?"
            params.append(course_id)
        if instructor_id:
            query += " AND w.instructor_id = ?"
            params.append(instructor_id)
        if status:
            query += " AND w.status = ?"
            params.append(status)
        query += " ORDER BY w.created_at DESC"
        tests = dicts_from_rows(db.execute(query, params).fetchall())
        db.close()
        self.success(tests)

    @require_auth(roles=["admin", "instructor", "ojt_admin"])
    def post(self):
        body = self.get_json_body()
        required = ["course_id", "title"]
        for f in required:
            if not body.get(f):
                return self.error(f"'{f}' is required")

        db = get_db()
        cur = db.execute("""
            INSERT INTO wrap_up_tests (course_id, module_id, instructor_id, title, description, test_date, time_limit_minutes, status)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (body["course_id"], body.get("module_id"), self.current_user_data["user_id"],
              body["title"], body.get("description", ""), body.get("test_date", ""),
              body.get("time_limit_minutes", 30), body.get("status", "draft")))
        db.commit()
        tid = cur.lastrowid
        db.close()
        self.success({"id": tid}, "Wrap-up test created")


class WrapUpTestDetailHandler(BaseHandler):
    @require_auth()
    def get(self, test_id):
        db = get_db()
        test = dict_from_row(db.execute("""
            SELECT w.*, c.name as course_name, u.name as instructor_name
            FROM wrap_up_tests w
            LEFT JOIN courses c ON w.course_id = c.id
            LEFT JOIN users u ON w.instructor_id = u.id
            WHERE w.id = ?
        """, (test_id,)).fetchone())
        if not test:
            db.close()
            return self.error("Test not found", 404)

        test["questions"] = dicts_from_rows(db.execute(
            "SELECT * FROM wrap_up_questions WHERE test_id = ? ORDER BY order_num", (test_id,)).fetchall())

        # Get results if any
        test["results"] = dicts_from_rows(db.execute("""
            SELECT wr.*, u.name as trainee_name, u.employee_id
            FROM wrap_up_results wr
            JOIN users u ON wr.trainee_id = u.id
            WHERE wr.test_id = ? ORDER BY u.name
        """, (test_id,)).fetchall())

        db.close()
        self.success(test)

    @require_auth(roles=["admin", "instructor", "ojt_admin"])
    def put(self, test_id):
        body = self.get_json_body()
        allowed = ["title", "description", "test_date", "time_limit_minutes", "status", "module_id"]
        updates = {k: body[k] for k in allowed if k in body}
        if not updates:
            return self.error("No valid fields")
        set_clause = ", ".join(f"{k} = ?" for k in updates)
        values = list(updates.values()) + [test_id]
        db = get_db()
        db.execute(f"UPDATE wrap_up_tests SET {set_clause} WHERE id = ?", values)
        db.commit()
        db.close()
        self.success(None, "Test updated")

    @require_auth(roles=["admin", "instructor"])
    def delete(self, test_id):
        db = get_db()
        db.execute("DELETE FROM wrap_up_tests WHERE id = ?", (test_id,))
        db.commit()
        db.close()
        self.success(None, "Test deleted")


class WrapUpQuestionsHandler(BaseHandler):
    @require_auth(roles=["admin", "instructor", "ojt_admin"])
    def post(self, test_id):
        body = self.get_json_body()
        if not body.get("question"):
            return self.error("question is required")

        db = get_db()
        max_order = db.execute("SELECT COALESCE(MAX(order_num),0) FROM wrap_up_questions WHERE test_id = ?", (test_id,)).fetchone()[0]
        cur = db.execute("""
            INSERT INTO wrap_up_questions (test_id, question, question_type, options, correct_answer, points, order_num)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (test_id, body["question"], body.get("question_type", "multiple_choice"),
              body.get("options", ""), body.get("correct_answer", ""),
              body.get("points", 10), max_order + 1))
        db.commit()
        qid = cur.lastrowid
        db.close()
        self.success({"id": qid}, "Question added")


class WrapUpQuestionDetailHandler(BaseHandler):
    @require_auth(roles=["admin", "instructor"])
    def put(self, question_id):
        body = self.get_json_body()
        allowed = ["question", "question_type", "options", "correct_answer", "points", "order_num"]
        updates = {k: body[k] for k in allowed if k in body}
        if not updates:
            return self.error("No valid fields")
        set_clause = ", ".join(f"{k} = ?" for k in updates)
        values = list(updates.values()) + [question_id]
        db = get_db()
        db.execute(f"UPDATE wrap_up_questions SET {set_clause} WHERE id = ?", values)
        db.commit()
        db.close()
        self.success(None, "Question updated")

    @require_auth(roles=["admin", "instructor"])
    def delete(self, question_id):
        db = get_db()
        db.execute("DELETE FROM wrap_up_questions WHERE id = ?", (question_id,))
        db.commit()
        db.close()
        self.success(None, "Question deleted")


class WrapUpSubmitHandler(BaseHandler):
    """Trainee submits answers to a wrap-up test"""
    @require_auth()
    def post(self, test_id):
        body = self.get_json_body()
        answers = body.get("answers", [])
        if not answers:
            return self.error("No answers provided")

        trainee_id = self.current_user_data["user_id"]
        db = get_db()

        total_score = 0
        max_score = 0

        for ans in answers:
            question_id = ans.get("question_id")
            answer = ans.get("answer", "")

            # Get correct answer and points
            q = dict_from_row(db.execute(
                "SELECT correct_answer, points, question_type FROM wrap_up_questions WHERE id = ?",
                (question_id,)).fetchone())
            if not q:
                continue

            points = float(q.get("points", 10) or 10)
            max_score += points
            is_correct = 0
            score = 0

            if q.get("question_type") in ("multiple_choice", "true_false"):
                if str(answer).strip().lower() == str(q.get("correct_answer", "")).strip().lower():
                    is_correct = 1
                    score = points
            else:
                # Short answer / essay - needs manual grading
                score = 0

            total_score += score

            db.execute("""
                INSERT INTO wrap_up_responses (test_id, trainee_id, question_id, answer, is_correct, score)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT (test_id, trainee_id, question_id) DO UPDATE SET
                    answer = EXCLUDED.answer, is_correct = EXCLUDED.is_correct,
                    score = EXCLUDED.score, submitted_at = CURRENT_TIMESTAMP
            """, (test_id, trainee_id, question_id, answer, is_correct, score))

        percentage = round((total_score / max_score * 100) if max_score > 0 else 0, 1)

        db.execute("""
            INSERT INTO wrap_up_results (test_id, trainee_id, total_score, max_score, percentage, status, submitted_at)
            VALUES (?, ?, ?, ?, ?, 'submitted', CURRENT_TIMESTAMP)
            ON CONFLICT (test_id, trainee_id) DO UPDATE SET
                total_score = EXCLUDED.total_score, max_score = EXCLUDED.max_score,
                percentage = EXCLUDED.percentage, status = 'submitted', submitted_at = CURRENT_TIMESTAMP
        """, (test_id, trainee_id, total_score, max_score, percentage))

        db.commit()
        db.close()
        self.success({"total_score": total_score, "max_score": max_score, "percentage": percentage}, "Test submitted")


class WrapUpGradeHandler(BaseHandler):
    """Instructor grades a wrap-up test response"""
    @require_auth(roles=["admin", "instructor", "ojt_admin"])
    def put(self, test_id, trainee_id):
        body = self.get_json_body()
        db = get_db()

        # Update individual question scores if provided
        if body.get("question_scores"):
            for qs in body["question_scores"]:
                db.execute("""
                    UPDATE wrap_up_responses SET score = ?, feedback = ?
                    WHERE test_id = ? AND trainee_id = ? AND question_id = ?
                """, (qs.get("score", 0), qs.get("feedback", ""), test_id, trainee_id, qs["question_id"]))

        # Recalculate total
        rows = dicts_from_rows(db.execute(
            "SELECT score FROM wrap_up_responses WHERE test_id = ? AND trainee_id = ?",
            (test_id, trainee_id)).fetchall())
        total_score = sum(float(r.get("score", 0) or 0) for r in rows)

        max_score_row = db.execute(
            "SELECT SUM(points) as total FROM wrap_up_questions WHERE test_id = ?", (test_id,)).fetchone()
        max_score = float(max_score_row[0] or 0) if max_score_row else 0
        percentage = round((total_score / max_score * 100) if max_score > 0 else 0, 1)

        db.execute("""
            UPDATE wrap_up_results SET total_score = ?, max_score = ?, percentage = ?,
                status = 'graded', instructor_feedback = ?, graded_at = CURRENT_TIMESTAMP
            WHERE test_id = ? AND trainee_id = ?
        """, (total_score, max_score, percentage, body.get("feedback", ""), test_id, trainee_id))

        db.commit()
        # Notify trainee that their wrap-up test has been graded
        if broadcast_to_user:
            try:
                broadcast_to_user(int(trainee_id), {
                    "type": "notification",
                    "data": {
                        "title": "Wrap-up Test \uCC44\uC810 \uC644\uB8CC",
                        "message": str(round(percentage, 1)) + "\uC810",
                        "notification_type": "success"
                    }
                })
            except Exception:
                pass
        db.close()
        self.success({"total_score": total_score, "percentage": percentage}, "Grading saved")
