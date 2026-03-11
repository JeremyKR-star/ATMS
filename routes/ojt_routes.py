"""OJT (On the Job Training) Routes"""
from routes.auth_routes import BaseHandler
from database import get_db, dict_from_row, dicts_from_rows
from auth import require_auth


class OJTProgramsHandler(BaseHandler):
    @require_auth()
    def get(self):
        status = self.get_argument("status", None)
        db = get_db()
        query = """
            SELECT p.*,
                COUNT(DISTINCT oe.trainee_id) as trainee_count,
                COUNT(DISTINCT ot.id) as task_count
            FROM ojt_programs p
            LEFT JOIN ojt_enrollments oe ON p.id = oe.program_id
            LEFT JOIN ojt_tasks ot ON p.id = ot.program_id
            WHERE 1=1
        """
        params = []
        if status:
            query += " AND p.status = ?"
            params.append(status)
        query += " GROUP BY p.id ORDER BY p.created_at DESC"
        programs = dicts_from_rows(db.execute(query, params).fetchall())
        db.close()
        self.success(programs)

    @require_auth(roles=["admin", "ojt_admin"])
    def post(self):
        body = self.get_json_body()
        if not body.get("name"):
            return self.error("Program name is required")

        db = get_db()
        cur = db.execute("""
            INSERT INTO ojt_programs (name, description, duration_weeks, aircraft_type, status)
            VALUES (?, ?, ?, ?, ?)
        """, (body["name"], body.get("description", ""), body.get("duration_weeks"),
              body.get("aircraft_type", ""), body.get("status", "planned")))
        db.commit()
        pid = cur.lastrowid
        db.close()
        self.success({"id": pid}, "OJT Program created")


class OJTProgramDetailHandler(BaseHandler):
    @require_auth()
    def get(self, program_id):
        db = get_db()
        program = dict_from_row(db.execute("SELECT * FROM ojt_programs WHERE id = ?", (program_id,)).fetchone())
        if not program:
            db.close()
            return self.error("Program not found", 404)

        program["tasks"] = dicts_from_rows(db.execute(
            "SELECT * FROM ojt_tasks WHERE program_id = ? ORDER BY order_num", (program_id,)).fetchall())
        program["enrollments"] = dicts_from_rows(db.execute("""
            SELECT oe.*, u.name as trainee_name, u.employee_id, u2.name as trainer_name
            FROM ojt_enrollments oe
            JOIN users u ON oe.trainee_id = u.id
            LEFT JOIN users u2 ON oe.trainer_id = u2.id
            WHERE oe.program_id = ? ORDER BY u.name
        """, (program_id,)).fetchall())
        db.close()
        self.success(program)

    @require_auth(roles=["admin", "ojt_admin"])
    def put(self, program_id):
        body = self.get_json_body()
        allowed = ["name", "description", "duration_weeks", "aircraft_type", "status"]
        updates = {k: body[k] for k in allowed if k in body}
        if updates:
            set_clause = ", ".join(f"{k} = ?" for k in updates)
            values = list(updates.values()) + [program_id]
            db = get_db()
            db.execute(f"UPDATE ojt_programs SET {set_clause} WHERE id = ?", values)
            db.commit()
            db.close()
        self.success(None, "Program updated")


class OJTTasksHandler(BaseHandler):
    @require_auth(roles=["admin", "ojt_admin", "instructor"])
    def post(self, program_id):
        body = self.get_json_body()
        if not body.get("name"):
            return self.error("Task name is required")

        db = get_db()
        max_order = db.execute("SELECT COALESCE(MAX(order_num),0) FROM ojt_tasks WHERE program_id = ?", (program_id,)).fetchone()[0]
        cur = db.execute("""
            INSERT INTO ojt_tasks (program_id, name, description, order_num, required_hours, criteria)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (program_id, body["name"], body.get("description", ""), max_order + 1,
              body.get("required_hours"), body.get("criteria", "")))
        db.commit()
        tid = cur.lastrowid
        db.close()
        self.success({"id": tid}, "OJT Task added")


class OJTEnrollHandler(BaseHandler):
    @require_auth(roles=["admin", "ojt_admin"])
    def post(self, program_id):
        body = self.get_json_body()
        trainee_id = body.get("trainee_id")
        trainer_id = body.get("trainer_id")
        if not trainee_id:
            return self.error("trainee_id is required")

        db = get_db()
        try:
            db.execute("""
                INSERT INTO ojt_enrollments (program_id, trainee_id, trainer_id, status)
                VALUES (?, ?, ?, 'enrolled')
            """, (program_id, trainee_id, trainer_id))
            db.commit()
            db.close()
            self.success(None, "Trainee enrolled in OJT")
        except Exception as e:
            db.close()
            self.error(str(e), 400)


class OJTEvaluationsHandler(BaseHandler):
    @require_auth()
    def get(self):
        program_id = self.get_argument("program_id", None)
        trainee_id = self.get_argument("trainee_id", None)
        status = self.get_argument("status", None)

        db = get_db()
        query = """
            SELECT oe2.*, ot.name as task_name, u.name as trainee_name,
                   u2.name as evaluator_name, op.name as program_name
            FROM ojt_evaluations oe2
            JOIN ojt_tasks ot ON oe2.task_id = ot.id
            JOIN ojt_enrollments oe ON oe2.enrollment_id = oe.id
            JOIN ojt_programs op ON oe.program_id = op.id
            JOIN users u ON oe.trainee_id = u.id
            LEFT JOIN users u2 ON oe2.evaluator_id = u2.id
            WHERE 1=1
        """
        params = []
        if program_id:
            query += " AND oe.program_id = ?"
            params.append(program_id)
        if trainee_id:
            query += " AND oe.trainee_id = ?"
            params.append(trainee_id)
        if status:
            query += " AND oe2.status = ?"
            params.append(status)
        query += " ORDER BY oe2.created_at DESC"
        evals = dicts_from_rows(db.execute(query, params).fetchall())
        db.close()
        self.success(evals)

    @require_auth(roles=["admin", "ojt_admin", "instructor"])
    def post(self):
        body = self.get_json_body()
        required = ["enrollment_id", "task_id"]
        for f in required:
            if not body.get(f):
                return self.error(f"'{f}' is required")

        db = get_db()
        cur = db.execute("""
            INSERT INTO ojt_evaluations (enrollment_id, task_id, evaluator_id, score, status, feedback, eval_date)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (body["enrollment_id"], body["task_id"], body.get("evaluator_id"),
              body.get("score"), body.get("status", "pending"),
              body.get("feedback", ""), body.get("eval_date", "")))
        db.commit()
        eid = cur.lastrowid
        db.close()
        self.success({"id": eid}, "OJT Evaluation created")
