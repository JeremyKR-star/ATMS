"""Extended OJT Routes - Sub-tasks, Leaders, TS/ES, Venues, Announcements, Surveys, Career Roadmap"""
from routes.auth_routes import BaseHandler
from database import get_db, dict_from_row, dicts_from_rows
from auth import require_auth

try:
    from websocket_handler import broadcast_to_user
except ImportError:
    broadcast_to_user = None


# ── OJT Sub-tasks ──
class OJTSubTasksHandler(BaseHandler):
    @require_auth()
    def get(self, task_id):
        db = get_db()
        subs = dicts_from_rows(db.execute(
            "SELECT * FROM ojt_sub_tasks WHERE task_id = ? ORDER BY order_num", (task_id,)).fetchall())
        db.close()
        self.success(subs)

    @require_auth(roles=["admin", "ojt_admin"])
    def post(self, task_id):
        body = self.get_json_body()
        if not body.get("name"):
            return self.error("name is required")
        db = get_db()
        max_order = db.execute("SELECT COALESCE(MAX(order_num),0) FROM ojt_sub_tasks WHERE task_id = ?", (task_id,)).fetchone()[0]
        cur = db.execute("""
            INSERT INTO ojt_sub_tasks (task_id, name, description, order_num, required_hours, criteria)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (task_id, body["name"], body.get("description", ""), max_order + 1,
              body.get("required_hours"), body.get("criteria", "")))
        db.commit()
        sid = cur.lastrowid
        db.close()
        self.success({"id": sid}, "Sub-task added")


class OJTSubTaskDetailHandler(BaseHandler):
    @require_auth(roles=["admin", "ojt_admin"])
    def put(self, sub_task_id):
        body = self.get_json_body()
        allowed = ["name", "description", "order_num", "required_hours", "criteria"]
        updates = {k: body[k] for k in allowed if k in body}
        if not updates:
            return self.error("No valid fields")
        set_clause = ", ".join(f"{k} = ?" for k in updates)
        values = list(updates.values()) + [sub_task_id]
        db = get_db()
        db.execute(f"UPDATE ojt_sub_tasks SET {set_clause} WHERE id = ?", values)
        db.commit()
        db.close()
        self.success(None, "Sub-task updated")

    @require_auth(roles=["admin", "ojt_admin"])
    def delete(self, sub_task_id):
        db = get_db()
        db.execute("DELETE FROM ojt_sub_tasks WHERE id = ?", (sub_task_id,))
        db.commit()
        db.close()
        self.success(None, "Sub-task deleted")


# ── OJT Leaders ──
class OJTLeadersHandler(BaseHandler):
    @require_auth()
    def get(self, program_id):
        db = get_db()
        leaders = dicts_from_rows(db.execute("""
            SELECT ol.*, u.name as user_name, u.employee_id, u.email
            FROM ojt_leaders ol JOIN users u ON ol.user_id = u.id
            WHERE ol.program_id = ? ORDER BY ol.role, u.name
        """, (program_id,)).fetchall())
        db.close()
        self.success(leaders)

    @require_auth(roles=["admin", "ojt_admin"])
    def post(self, program_id):
        body = self.get_json_body()
        if not body.get("user_id"):
            return self.error("user_id is required")
        db = get_db()
        try:
            cur = db.execute("""
                INSERT INTO ojt_leaders (program_id, user_id, role)
                VALUES (?, ?, ?)
            """, (program_id, body["user_id"], body.get("role", "leader")))
            db.commit()
            lid = cur.lastrowid
            db.close()
            self.success({"id": lid}, "Leader assigned")
        except Exception as e:
            db.close()
            self.error(str(e), 400)


class OJTLeaderDetailHandler(BaseHandler):
    @require_auth(roles=["admin", "ojt_admin"])
    def delete(self, leader_id):
        db = get_db()
        db.execute("DELETE FROM ojt_leaders WHERE id = ?", (leader_id,))
        db.commit()
        db.close()
        self.success(None, "Leader removed")


# ── OJT Training Specs (TS) ──
class OJTTrainingSpecsHandler(BaseHandler):
    @require_auth()
    def get(self):
        program_id = self.get_argument("program_id", None)
        db = get_db()
        query = """
            SELECT ts.*, op.name as program_name, u.name as created_by_name
            FROM ojt_training_specs ts
            LEFT JOIN ojt_programs op ON ts.program_id = op.id
            LEFT JOIN users u ON ts.created_by = u.id WHERE 1=1
        """
        params = []
        if program_id:
            query += " AND ts.program_id = ?"
            params.append(program_id)
        query += " ORDER BY ts.created_at DESC"
        specs = dicts_from_rows(db.execute(query, params).fetchall())
        db.close()
        self.success(specs)

    @require_auth(roles=["admin", "ojt_admin"])
    def post(self):
        body = self.get_json_body()
        if not body.get("program_id") or not body.get("title"):
            return self.error("program_id and title are required")
        db = get_db()
        cur = db.execute("""
            INSERT INTO ojt_training_specs (program_id, title, description, content, file_path, version, status, created_by)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (body["program_id"], body["title"], body.get("description", ""),
              body.get("content", ""), body.get("file_path", ""),
              body.get("version", "1.0"), body.get("status", "draft"),
              self.current_user_data["user_id"]))
        db.commit()
        sid = cur.lastrowid
        db.close()
        self.success({"id": sid}, "Training spec created")


class OJTTrainingSpecDetailHandler(BaseHandler):
    @require_auth(roles=["admin", "ojt_admin"])
    def put(self, spec_id):
        body = self.get_json_body()
        allowed = ["title", "description", "content", "file_path", "version", "status"]
        updates = {k: body[k] for k in allowed if k in body}
        if not updates:
            return self.error("No valid fields")
        set_clause = ", ".join(f"{k} = ?" for k in updates)
        values = list(updates.values()) + [spec_id]
        db = get_db()
        db.execute(f"UPDATE ojt_training_specs SET {set_clause}, updated_at = CURRENT_TIMESTAMP WHERE id = ?", values)
        db.commit()
        db.close()
        self.success(None, "Training spec updated")


# ── OJT Eval Specs (ES) ──
class OJTEvalSpecsHandler(BaseHandler):
    @require_auth()
    def get(self):
        program_id = self.get_argument("program_id", None)
        db = get_db()
        query = """
            SELECT es.*, op.name as program_name, u.name as created_by_name
            FROM ojt_eval_specs es
            LEFT JOIN ojt_programs op ON es.program_id = op.id
            LEFT JOIN users u ON es.created_by = u.id WHERE 1=1
        """
        params = []
        if program_id:
            query += " AND es.program_id = ?"
            params.append(program_id)
        query += " ORDER BY es.created_at DESC"
        specs = dicts_from_rows(db.execute(query, params).fetchall())
        db.close()
        self.success(specs)

    @require_auth(roles=["admin", "ojt_admin"])
    def post(self):
        body = self.get_json_body()
        if not body.get("program_id") or not body.get("title"):
            return self.error("program_id and title are required")
        db = get_db()
        cur = db.execute("""
            INSERT INTO ojt_eval_specs (program_id, title, description, content, file_path, version, status, created_by)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (body["program_id"], body["title"], body.get("description", ""),
              body.get("content", ""), body.get("file_path", ""),
              body.get("version", "1.0"), body.get("status", "draft"),
              self.current_user_data["user_id"]))
        db.commit()
        sid = cur.lastrowid
        db.close()
        self.success({"id": sid}, "Evaluation spec created")


class OJTEvalSpecDetailHandler(BaseHandler):
    @require_auth(roles=["admin", "ojt_admin"])
    def put(self, spec_id):
        body = self.get_json_body()
        allowed = ["title", "description", "content", "file_path", "version", "status"]
        updates = {k: body[k] for k in allowed if k in body}
        if not updates:
            return self.error("No valid fields")
        set_clause = ", ".join(f"{k} = ?" for k in updates)
        values = list(updates.values()) + [spec_id]
        db = get_db()
        db.execute(f"UPDATE ojt_eval_specs SET {set_clause}, updated_at = CURRENT_TIMESTAMP WHERE id = ?", values)
        db.commit()
        db.close()
        self.success(None, "Evaluation spec updated")


# ── OJT Pre-assignments ──
class OJTPreAssignmentsHandler(BaseHandler):
    @require_auth()
    def get(self):
        program_id = self.get_argument("program_id", None)
        db = get_db()
        query = """
            SELECT pa.*, op.name as program_name, u.name as created_by_name
            FROM ojt_pre_assignments pa
            LEFT JOIN ojt_programs op ON pa.program_id = op.id
            LEFT JOIN users u ON pa.created_by = u.id WHERE 1=1
        """
        params = []
        if program_id:
            query += " AND pa.program_id = ?"
            params.append(program_id)
        query += " ORDER BY pa.created_at DESC"
        items = dicts_from_rows(db.execute(query, params).fetchall())
        db.close()
        self.success(items)

    @require_auth(roles=["admin", "ojt_admin"])
    def post(self):
        body = self.get_json_body()
        if not body.get("program_id") or not body.get("title"):
            return self.error("program_id and title are required")
        db = get_db()
        cur = db.execute("""
            INSERT INTO ojt_pre_assignments (program_id, title, description, file_path, due_date, created_by)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (body["program_id"], body["title"], body.get("description", ""),
              body.get("file_path", ""), body.get("due_date", ""),
              self.current_user_data["user_id"]))
        db.commit()
        pid = cur.lastrowid
        db.close()
        self.success({"id": pid}, "Pre-assignment created")


# ── OJT Venues ──
class OJTVenuesHandler(BaseHandler):
    @require_auth()
    def get(self):
        db = get_db()
        venues = dicts_from_rows(db.execute(
            "SELECT * FROM ojt_venues ORDER BY name").fetchall())
        db.close()
        self.success(venues)

    @require_auth(roles=["admin", "ojt_admin"])
    def post(self):
        body = self.get_json_body()
        if not body.get("name"):
            return self.error("name is required")
        db = get_db()
        cur = db.execute("""
            INSERT INTO ojt_venues (name, location, capacity, equipment, notes, status)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (body["name"], body.get("location", ""), body.get("capacity"),
              body.get("equipment", ""), body.get("notes", ""),
              body.get("status", "active")))
        db.commit()
        vid = cur.lastrowid
        db.close()
        self.success({"id": vid}, "Venue created")


class OJTVenueDetailHandler(BaseHandler):
    @require_auth(roles=["admin", "ojt_admin"])
    def put(self, venue_id):
        body = self.get_json_body()
        allowed = ["name", "location", "capacity", "equipment", "notes", "status"]
        updates = {k: body[k] for k in allowed if k in body}
        if not updates:
            return self.error("No valid fields")
        set_clause = ", ".join(f"{k} = ?" for k in updates)
        values = list(updates.values()) + [venue_id]
        db = get_db()
        db.execute(f"UPDATE ojt_venues SET {set_clause} WHERE id = ?", values)
        db.commit()
        db.close()
        self.success(None, "Venue updated")

    @require_auth(roles=["admin", "ojt_admin"])
    def delete(self, venue_id):
        db = get_db()
        db.execute("DELETE FROM ojt_venues WHERE id = ?", (venue_id,))
        db.commit()
        db.close()
        self.success(None, "Venue deleted")


# ── OJT Announcements ──
class OJTAnnouncementsHandler(BaseHandler):
    @require_auth()
    def get(self):
        program_id = self.get_argument("program_id", None)
        db = get_db()
        query = """
            SELECT a.*, u.name as created_by_name, op.name as program_name
            FROM ojt_announcements a
            LEFT JOIN users u ON a.created_by = u.id
            LEFT JOIN ojt_programs op ON a.program_id = op.id
            WHERE 1=1
        """
        params = []
        if program_id:
            query += " AND a.program_id = ?"
            params.append(program_id)
        query += " ORDER BY a.created_at DESC"
        items = dicts_from_rows(db.execute(query, params).fetchall())
        db.close()
        self.success(items)

    @require_auth(roles=["admin", "ojt_admin"])
    def post(self):
        body = self.get_json_body()
        if not body.get("title"):
            return self.error("title is required")
        db = get_db()
        cur = db.execute("""
            INSERT INTO ojt_announcements (program_id, title, content, priority, created_by)
            VALUES (?, ?, ?, ?, ?)
        """, (body.get("program_id"), body["title"], body.get("content", ""),
              body.get("priority", "normal"), self.current_user_data["user_id"]))
        db.commit()
        aid = cur.lastrowid
        db.close()
        self.success({"id": aid}, "Announcement created")


class OJTAnnouncementDetailHandler(BaseHandler):
    @require_auth(roles=["admin", "ojt_admin"])
    def put(self, ann_id):
        body = self.get_json_body()
        allowed = ["title", "content", "priority", "program_id"]
        updates = {k: body[k] for k in allowed if k in body}
        if not updates:
            return self.error("No valid fields")
        set_clause = ", ".join(f"{k} = ?" for k in updates)
        values = list(updates.values()) + [ann_id]
        db = get_db()
        db.execute(f"UPDATE ojt_announcements SET {set_clause}, updated_at = CURRENT_TIMESTAMP WHERE id = ?", values)
        db.commit()
        db.close()
        self.success(None, "Announcement updated")

    @require_auth(roles=["admin", "ojt_admin"])
    def delete(self, ann_id):
        db = get_db()
        db.execute("DELETE FROM ojt_announcements WHERE id = ?", (ann_id,))
        db.commit()
        db.close()
        self.success(None, "Announcement deleted")


# ── OJT Survey Templates & Responses ──
class OJTSurveyTemplatesHandler(BaseHandler):
    @require_auth()
    def get(self):
        program_id = self.get_argument("program_id", None)
        db = get_db()
        query = """
            SELECT st.*, op.name as program_name, u.name as created_by_name,
                   (SELECT COUNT(*) FROM ojt_survey_items WHERE template_id = st.id) as item_count
            FROM ojt_survey_templates st
            LEFT JOIN ojt_programs op ON st.program_id = op.id
            LEFT JOIN users u ON st.created_by = u.id WHERE 1=1
        """
        params = []
        if program_id:
            query += " AND st.program_id = ?"
            params.append(program_id)
        query += " ORDER BY st.created_at DESC"
        templates = dicts_from_rows(db.execute(query, params).fetchall())
        db.close()
        self.success(templates)

    @require_auth(roles=["admin", "ojt_admin"])
    def post(self):
        body = self.get_json_body()
        if not body.get("title"):
            return self.error("title is required")
        db = get_db()
        cur = db.execute("""
            INSERT INTO ojt_survey_templates (program_id, title, description, start_date, end_date, status, created_by)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (body.get("program_id"), body["title"], body.get("description", ""),
              body.get("start_date", ""), body.get("end_date", ""),
              body.get("status", "draft"), self.current_user_data["user_id"]))
        db.commit()
        tid = cur.lastrowid
        db.close()
        self.success({"id": tid}, "Survey template created")


class OJTSurveyTemplateDetailHandler(BaseHandler):
    @require_auth()
    def get(self, template_id):
        db = get_db()
        tmpl = dict_from_row(db.execute(
            "SELECT * FROM ojt_survey_templates WHERE id = ?", (template_id,)).fetchone())
        if not tmpl:
            db.close()
            return self.error("Template not found", 404)
        tmpl["items"] = dicts_from_rows(db.execute(
            "SELECT * FROM ojt_survey_items WHERE template_id = ? ORDER BY order_num",
            (template_id,)).fetchall())
        # Response count
        tmpl["response_count"] = db.execute(
            "SELECT COUNT(DISTINCT trainee_id) FROM ojt_survey_responses WHERE template_id = ?",
            (template_id,)).fetchone()[0]
        db.close()
        self.success(tmpl)

    @require_auth(roles=["admin", "ojt_admin"])
    def put(self, template_id):
        body = self.get_json_body()
        allowed = ["title", "description", "start_date", "end_date", "status", "program_id"]
        updates = {k: body[k] for k in allowed if k in body}
        if not updates:
            return self.error("No valid fields")
        set_clause = ", ".join(f"{k} = ?" for k in updates)
        values = list(updates.values()) + [template_id]
        db = get_db()
        db.execute(f"UPDATE ojt_survey_templates SET {set_clause} WHERE id = ?", values)
        db.commit()
        db.close()
        self.success(None, "Template updated")

    @require_auth(roles=["admin", "ojt_admin"])
    def delete(self, template_id):
        db = get_db()
        db.execute("DELETE FROM ojt_survey_templates WHERE id = ?", (template_id,))
        db.commit()
        db.close()
        self.success(None, "Template deleted")


class OJTSurveyItemsHandler(BaseHandler):
    @require_auth(roles=["admin", "ojt_admin"])
    def post(self, template_id):
        body = self.get_json_body()
        if not body.get("question"):
            return self.error("question is required")
        db = get_db()
        max_order = db.execute("SELECT COALESCE(MAX(order_num),0) FROM ojt_survey_items WHERE template_id = ?", (template_id,)).fetchone()[0]
        cur = db.execute("""
            INSERT INTO ojt_survey_items (template_id, question, question_type, options, order_num, required)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (template_id, body["question"], body.get("question_type", "rating"),
              body.get("options", ""), max_order + 1, body.get("required", 1)))
        db.commit()
        iid = cur.lastrowid
        db.close()
        self.success({"id": iid}, "Survey item added")


class OJTSurveyResponsesHandler(BaseHandler):
    """Trainee submits survey responses"""
    @require_auth()
    def get(self):
        template_id = self.get_argument("template_id", None)
        db = get_db()
        query = """
            SELECT sr.*, u.name as trainee_name, si.question
            FROM ojt_survey_responses sr
            JOIN users u ON sr.trainee_id = u.id
            JOIN ojt_survey_items si ON sr.item_id = si.id
            WHERE 1=1
        """
        params = []
        if template_id:
            query += " AND sr.template_id = ?"
            params.append(template_id)
        query += " ORDER BY sr.created_at DESC"
        responses = dicts_from_rows(db.execute(query, params).fetchall())
        db.close()
        self.success(responses)

    @require_auth()
    def post(self):
        body = self.get_json_body()
        template_id = body.get("template_id")
        responses = body.get("responses", [])
        if not template_id or not responses:
            return self.error("template_id and responses are required")

        trainee_id = self.current_user_data["user_id"]
        db = get_db()
        for resp in responses:
            db.execute("""
                INSERT INTO ojt_survey_responses (template_id, item_id, trainee_id, response, rating)
                VALUES (?, ?, ?, ?, ?)
            """, (template_id, resp["item_id"], trainee_id,
                  resp.get("response", ""), resp.get("rating")))
        db.commit()

        # Fetch template name for broadcast
        template = db.execute("SELECT title FROM ojt_survey_templates WHERE id = ?", (template_id,)).fetchone()
        trainee = db.execute("SELECT name FROM users WHERE id = ?", (trainee_id,)).fetchone()
        db.close()

        # Broadcast survey submission event
        if broadcast_to_user:
            try:
                broadcast_to_user(trainee_id, {
                    "type": "survey_submission",
                    "data": {
                        "template_name": template[0] if template else "",
                        "trainee_name": trainee[0] if trainee else "",
                        "response_count": len(responses)
                    }
                })
            except Exception:
                pass

        self.success(None, "Survey submitted")


class OJTSurveyResultsHandler(BaseHandler):
    """Get aggregated survey results"""
    @require_auth(roles=["admin", "ojt_admin", "manager"])
    def get(self, template_id):
        db = get_db()
        items = dicts_from_rows(db.execute("""
            SELECT si.id, si.question, si.question_type,
                   AVG(sr.rating) as avg_rating,
                   COUNT(sr.id) as response_count
            FROM ojt_survey_items si
            LEFT JOIN ojt_survey_responses sr ON si.id = sr.item_id
            WHERE si.template_id = ?
            GROUP BY si.id, si.question, si.question_type
            ORDER BY si.order_num
        """, (template_id,)).fetchall())

        # Text responses
        for item in items:
            if item.get("question_type") == "text":
                text_responses = dicts_from_rows(db.execute("""
                    SELECT sr.response, u.name as trainee_name
                    FROM ojt_survey_responses sr JOIN users u ON sr.trainee_id = u.id
                    WHERE sr.item_id = ? ORDER BY sr.created_at DESC
                """, (item["id"],)).fetchall())
                item["text_responses"] = text_responses

        db.close()
        self.success(items)


# ── OJT Schedules ──
class OJTSchedulesHandler(BaseHandler):
    @require_auth()
    def get(self):
        program_id = self.get_argument("program_id", None)
        db = get_db()
        query = """
            SELECT os.*, op.name as program_name, v.name as venue_name, u.name as instructor_name
            FROM ojt_schedules os
            LEFT JOIN ojt_programs op ON os.program_id = op.id
            LEFT JOIN ojt_venues v ON os.venue_id = v.id
            LEFT JOIN users u ON os.instructor_id = u.id WHERE 1=1
        """
        params = []
        if program_id:
            query += " AND os.program_id = ?"
            params.append(program_id)
        query += " ORDER BY os.schedule_date, os.start_time"
        items = dicts_from_rows(db.execute(query, params).fetchall())
        db.close()
        self.success(items)

    @require_auth(roles=["admin", "ojt_admin"])
    def post(self):
        body = self.get_json_body()
        if not body.get("program_id") or not body.get("title") or not body.get("schedule_date"):
            return self.error("program_id, title, and schedule_date are required")
        db = get_db()
        cur = db.execute("""
            INSERT INTO ojt_schedules (program_id, title, schedule_date, start_time, end_time, venue_id, instructor_id, notes)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (body["program_id"], body["title"], body["schedule_date"],
              body.get("start_time", ""), body.get("end_time", ""),
              body.get("venue_id"), body.get("instructor_id"), body.get("notes", "")))
        db.commit()
        sid = cur.lastrowid
        db.close()
        self.success({"id": sid}, "OJT schedule created")


class OJTScheduleDetailHandler(BaseHandler):
    @require_auth(roles=["admin", "ojt_admin"])
    def put(self, schedule_id):
        body = self.get_json_body()
        allowed = ["title", "schedule_date", "start_time", "end_time", "venue_id", "instructor_id", "notes"]
        updates = {k: body[k] for k in allowed if k in body}
        if not updates:
            return self.error("No valid fields")
        set_clause = ", ".join(f"{k} = ?" for k in updates)
        values = list(updates.values()) + [schedule_id]
        db = get_db()
        db.execute(f"UPDATE ojt_schedules SET {set_clause} WHERE id = ?", values)
        db.commit()
        db.close()
        self.success(None, "Schedule updated")

    @require_auth(roles=["admin", "ojt_admin"])
    def delete(self, schedule_id):
        db = get_db()
        db.execute("DELETE FROM ojt_schedules WHERE id = ?", (schedule_id,))
        db.commit()
        db.close()
        self.success(None, "Schedule deleted")


# ── Career Development Roadmap ──
class CareerRoadmapHandler(BaseHandler):
    @require_auth()
    def get(self):
        level = self.get_argument("level", None)
        db = get_db()
        query = "SELECT * FROM career_roadmap WHERE 1=1"
        params = []
        if level:
            query += " AND level = ?"
            params.append(level)
        query += " ORDER BY level"
        roadmaps = dicts_from_rows(db.execute(query, params).fetchall())

        # Include tasks for each roadmap
        for rm in roadmaps:
            rm["tasks"] = dicts_from_rows(db.execute(
                "SELECT * FROM career_roadmap_tasks WHERE roadmap_id = ? ORDER BY order_num",
                (rm["id"],)).fetchall())
            for task in rm["tasks"]:
                task["sub_tasks"] = dicts_from_rows(db.execute(
                    "SELECT * FROM career_roadmap_sub_tasks WHERE task_id = ? ORDER BY order_num",
                    (task["id"],)).fetchall())

        db.close()
        self.success(roadmaps)

    @require_auth(roles=["admin", "ojt_admin"])
    def post(self):
        body = self.get_json_body()
        if not body.get("level") or not body.get("title") or not body.get("level_name"):
            return self.error("level, level_name, and title are required")
        db = get_db()
        cur = db.execute("""
            INSERT INTO career_roadmap (level, level_name, title, description, requirements, duration_months)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (body["level"], body["level_name"], body["title"],
              body.get("description", ""), body.get("requirements", ""),
              body.get("duration_months")))
        db.commit()
        rid = cur.lastrowid
        db.close()
        self.success({"id": rid}, "Roadmap level created")


class CareerRoadmapDetailHandler(BaseHandler):
    @require_auth(roles=["admin", "ojt_admin"])
    def put(self, roadmap_id):
        body = self.get_json_body()
        allowed = ["level", "level_name", "title", "description", "requirements", "duration_months"]
        updates = {k: body[k] for k in allowed if k in body}
        if not updates:
            return self.error("No valid fields")
        set_clause = ", ".join(f"{k} = ?" for k in updates)
        values = list(updates.values()) + [roadmap_id]
        db = get_db()
        db.execute(f"UPDATE career_roadmap SET {set_clause} WHERE id = ?", values)
        db.commit()
        db.close()
        self.success(None, "Roadmap updated")


class CareerRoadmapTasksHandler(BaseHandler):
    @require_auth(roles=["admin", "ojt_admin"])
    def post(self, roadmap_id):
        body = self.get_json_body()
        if not body.get("name"):
            return self.error("name is required")
        db = get_db()
        max_order = db.execute("SELECT COALESCE(MAX(order_num),0) FROM career_roadmap_tasks WHERE roadmap_id = ?", (roadmap_id,)).fetchone()[0]
        cur = db.execute("""
            INSERT INTO career_roadmap_tasks (roadmap_id, name, description, order_num, required)
            VALUES (?, ?, ?, ?, ?)
        """, (roadmap_id, body["name"], body.get("description", ""), max_order + 1, body.get("required", 1)))
        db.commit()
        tid = cur.lastrowid
        db.close()
        self.success({"id": tid}, "Task added")


class CareerRoadmapSubTasksHandler(BaseHandler):
    @require_auth(roles=["admin", "ojt_admin"])
    def post(self, task_id):
        body = self.get_json_body()
        if not body.get("name"):
            return self.error("name is required")
        db = get_db()
        max_order = db.execute("SELECT COALESCE(MAX(order_num),0) FROM career_roadmap_sub_tasks WHERE task_id = ?", (task_id,)).fetchone()[0]
        cur = db.execute("""
            INSERT INTO career_roadmap_sub_tasks (task_id, name, description, order_num)
            VALUES (?, ?, ?, ?)
        """, (task_id, body["name"], body.get("description", ""), max_order + 1))
        db.commit()
        sid = cur.lastrowid
        db.close()
        self.success({"id": sid}, "Sub-task added")


class CareerRoadmapProgressHandler(BaseHandler):
    @require_auth()
    def get(self):
        trainee_id = self.get_argument("trainee_id", None)
        roadmap_id = self.get_argument("roadmap_id", None)
        db = get_db()
        query = """
            SELECT crp.*, u.name as trainee_name, cr.title as roadmap_title,
                   crt.name as task_name, crst.name as sub_task_name
            FROM career_roadmap_progress crp
            JOIN users u ON crp.trainee_id = u.id
            JOIN career_roadmap cr ON crp.roadmap_id = cr.id
            LEFT JOIN career_roadmap_tasks crt ON crp.task_id = crt.id
            LEFT JOIN career_roadmap_sub_tasks crst ON crp.sub_task_id = crst.id
            WHERE 1=1
        """
        params = []
        if trainee_id:
            query += " AND crp.trainee_id = ?"
            params.append(trainee_id)
        if roadmap_id:
            query += " AND crp.roadmap_id = ?"
            params.append(roadmap_id)
        query += " ORDER BY cr.level, crp.task_id"
        items = dicts_from_rows(db.execute(query, params).fetchall())
        db.close()
        self.success(items)

    @require_auth(roles=["admin", "ojt_admin", "instructor"])
    def post(self):
        body = self.get_json_body()
        required = ["trainee_id", "roadmap_id"]
        for f in required:
            if not body.get(f):
                return self.error(f"'{f}' is required")
        db = get_db()
        db.execute("""
            INSERT INTO career_roadmap_progress (trainee_id, roadmap_id, task_id, sub_task_id, status, notes)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT (trainee_id, roadmap_id, task_id, sub_task_id) DO UPDATE SET
                status = EXCLUDED.status, notes = EXCLUDED.notes
        """, (body["trainee_id"], body["roadmap_id"], body.get("task_id"),
              body.get("sub_task_id"), body.get("status", "pending"), body.get("notes", "")))
        db.commit()
        db.close()
        self.success(None, "Progress updated")


# ── OJT Training Results ──
class OJTTrainingResultsHandler(BaseHandler):
    @require_auth()
    def get(self):
        enrollment_id = self.get_argument("enrollment_id", None)
        program_id = self.get_argument("program_id", None)
        db = get_db()
        query = """
            SELECT tr.*, ot.name as task_name, u.name as trainee_name, op.name as program_name
            FROM ojt_training_results tr
            JOIN ojt_tasks ot ON tr.task_id = ot.id
            JOIN ojt_enrollments oe ON tr.enrollment_id = oe.id
            JOIN users u ON oe.trainee_id = u.id
            JOIN ojt_programs op ON oe.program_id = op.id
            WHERE 1=1
        """
        params = []
        if enrollment_id:
            query += " AND tr.enrollment_id = ?"
            params.append(enrollment_id)
        if program_id:
            query += " AND oe.program_id = ?"
            params.append(program_id)
        query += " ORDER BY tr.result_date DESC"
        results = dicts_from_rows(db.execute(query, params).fetchall())
        db.close()
        self.success(results)

    @require_auth(roles=["admin", "ojt_admin", "instructor"])
    def post(self):
        body = self.get_json_body()
        required = ["enrollment_id", "task_id"]
        for f in required:
            if not body.get(f):
                return self.error(f"'{f}' is required")
        db = get_db()
        cur = db.execute("""
            INSERT INTO ojt_training_results (enrollment_id, task_id, attendance_status, completion_status, score, notes, result_date)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (body["enrollment_id"], body["task_id"],
              body.get("attendance_status", "present"), body.get("completion_status", "pending"),
              body.get("score"), body.get("notes", ""), body.get("result_date", "")))
        db.commit()
        rid = cur.lastrowid
        db.close()
        self.success({"id": rid}, "Training result recorded")


class OJTTrainingResultDetailHandler(BaseHandler):
    @require_auth(roles=["admin", "ojt_admin", "instructor"])
    def put(self, result_id):
        body = self.get_json_body()
        db = get_db()
        # Check exists
        result = db.execute("SELECT enrollment_id, task_id FROM ojt_training_results WHERE id = ?", (result_id,)).fetchone()
        if not result:
            db.close()
            return self.error("Training result not found", 404)

        fields = []
        params = []
        for col in ["attendance_status", "completion_status", "score", "notes", "result_date"]:
            if col in body:
                fields.append(col + " = ?")
                params.append(body[col])
        if not fields:
            db.close()
            return self.error("No fields to update")
        params.append(result_id)
        db.execute("UPDATE ojt_training_results SET " + ", ".join(fields) + " WHERE id = ?", params)
        db.commit()

        # Fetch related data for broadcast
        enrollment = db.execute("SELECT trainee_id, program_id FROM ojt_enrollments WHERE id = ?", (result[0],)).fetchone()
        task = db.execute("SELECT name FROM ojt_tasks WHERE id = ?", (result[1],)).fetchone()
        program = db.execute("SELECT name FROM ojt_programs WHERE id = ?", (enrollment[1],)).fetchone() if enrollment else None
        db.close()

        # Broadcast training result update event
        if broadcast_to_user and enrollment:
            try:
                broadcast_to_user(enrollment[0], {
                    "type": "training_result_update",
                    "data": {
                        "program_name": program[0] if program else "",
                        "task_name": task[0] if task else "",
                        "completion_status": body.get("completion_status"),
                        "score": body.get("score")
                    }
                })
            except Exception:
                pass

        self.success(None, "Training result updated")

    @require_auth(roles=["admin", "ojt_admin"])
    def delete(self, result_id):
        db = get_db()
        existing = db.execute("SELECT id FROM ojt_training_results WHERE id = ?", (result_id,)).fetchone()
        if not existing:
            db.close()
            return self.error("Training result not found", 404)
        db.execute("DELETE FROM ojt_training_results WHERE id = ?", (result_id,))
        db.commit()
        db.close()
        self.success(None, "Training result deleted")


# ── OJT Program Admins ──
class OJTProgramAdminsHandler(BaseHandler):
    @require_auth(roles=["admin", "ojt_admin"])
    def get(self, program_id):
        db = get_db()
        admins = dicts_from_rows(db.execute("""
            SELECT pa.*, u.name as user_name, u.email, u.role as user_role
            FROM ojt_program_admins pa
            JOIN users u ON pa.user_id = u.id
            WHERE pa.program_id = ?
            ORDER BY pa.assigned_at DESC
        """, (program_id,)).fetchall())
        db.close()
        self.success(admins)

    @require_auth(roles=["admin", "ojt_admin"])
    def post(self, program_id):
        body = self.get_json_body()
        user_id = body.get("user_id")
        admin_role = body.get("admin_role", "dedicated_admin")
        permissions = body.get("permissions", "read,write")
        if not user_id:
            return self.error("user_id is required", 400)

        db = get_db()
        try:
            db.execute("""
                INSERT INTO ojt_program_admins (program_id, user_id, admin_role, permissions)
                VALUES (?, ?, ?, ?)
            """, (program_id, user_id, admin_role, permissions))
            db.commit()
            db.close()
            self.success(None, "Program admin assigned")
        except Exception as e:
            db.close()
            self.error(str(e), 400)


class OJTProgramAdminDetailHandler(BaseHandler):
    @require_auth(roles=["admin", "ojt_admin"])
    def delete(self, admin_id):
        db = get_db()
        db.execute("DELETE FROM ojt_program_admins WHERE id = ?", (admin_id,))
        db.commit()
        db.close()
        self.success(None, "Program admin removed")


# ── OJT Evaluation Templates ──
class OJTEvalTemplateHandler(BaseHandler):
    @require_auth()
    def get(self):
        program_id = self.get_argument("program_id", None)
        db = get_db()
        query = """
            SELECT et.*, u.name as created_by_name, op.name as program_name
            FROM ojt_eval_templates et
            LEFT JOIN users u ON et.created_by = u.id
            LEFT JOIN ojt_programs op ON et.program_id = op.id
            WHERE 1=1
        """
        params = []
        if program_id:
            query += " AND et.program_id = ?"
            params.append(program_id)
        query += " ORDER BY et.created_at DESC"
        templates = dicts_from_rows(db.execute(query, params).fetchall())
        db.close()
        self.success(templates)

    @require_auth(roles=["admin", "ojt_admin", "instructor"])
    def post(self):
        body = self.get_json_body()
        if not body.get("name"):
            return self.error("name is required")
        if not body.get("program_id"):
            return self.error("program_id is required")
        db = get_db()
        cur = db.execute("""
            INSERT INTO ojt_eval_templates (program_id, name, description, criteria, max_score, template_data, created_by)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (body["program_id"], body["name"], body.get("description", ""),
              body.get("criteria", ""), body.get("max_score", 100),
              body.get("template_data", ""), self.current_user_data["user_id"]))
        db.commit()
        template_id = cur.lastrowid
        db.close()
        self.success({"id": template_id}, "Evaluation template created")


class OJTEvalTemplateDetailHandler(BaseHandler):
    @require_auth()
    def get(self, template_id):
        db = get_db()
        template = dict_from_row(db.execute("""
            SELECT et.*, u.name as created_by_name, op.name as program_name
            FROM ojt_eval_templates et
            LEFT JOIN users u ON et.created_by = u.id
            LEFT JOIN ojt_programs op ON et.program_id = op.id
            WHERE et.id = ?
        """, (template_id,)).fetchone())
        db.close()
        if not template:
            return self.error("Template not found", 404)
        self.success(template)

    @require_auth(roles=["admin", "ojt_admin", "instructor"])
    def put(self, template_id):
        body = self.get_json_body()
        allowed = ["name", "description", "criteria", "max_score", "template_data", "program_id"]
        updates = {k: body[k] for k in allowed if k in body}
        if not updates:
            return self.error("No valid fields")
        updates["updated_at"] = "CURRENT_TIMESTAMP"
        set_clause = ", ".join(f"{k} = ?" for k in updates if k != "updated_at")
        set_clause += ", updated_at = CURRENT_TIMESTAMP"
        values = [v for k, v in updates.items() if k != "updated_at"] + [template_id]
        db = get_db()
        db.execute(f"UPDATE ojt_eval_templates SET {set_clause} WHERE id = ?", values)
        db.commit()
        db.close()
        self.success(None, "Evaluation template updated")

    @require_auth(roles=["admin", "ojt_admin", "instructor"])
    def delete(self, template_id):
        db = get_db()
        db.execute("DELETE FROM ojt_eval_templates WHERE id = ?", (template_id,))
        db.commit()
        db.close()
        self.success(None, "Evaluation template deleted")


class OJTEvalTemplateBulkApplyHandler(BaseHandler):
    @require_auth(roles=["admin", "ojt_admin", "instructor"])
    def post(self):
        body = self.get_json_body()
        template_id = body.get("template_id")
        program_id = body.get("program_id")
        if not template_id:
            return self.error("template_id is required")
        if not program_id:
            return self.error("program_id is required")

        db = get_db()

        # Get template
        template = dict_from_row(db.execute(
            "SELECT * FROM ojt_eval_templates WHERE id = ?", (template_id,)).fetchone())
        if not template:
            db.close()
            return self.error("Template not found", 404)

        # Get all trainees enrolled in the program
        enrollments = dicts_from_rows(db.execute("""
            SELECT DISTINCT oe.trainee_id, oe.id as enrollment_id
            FROM ojt_enrollments oe
            WHERE oe.program_id = ?
        """, (program_id,)).fetchall())

        if not enrollments:
            db.close()
            return self.success({"created_count": 0}, "No trainees to evaluate")

        created_count = 0
        try:
            for enrollment in enrollments:
                # Check if evaluation already exists
                existing = db.execute("""
                    SELECT id FROM ojt_evaluations
                    WHERE enrollment_id = ? AND template_id = ?
                """, (enrollment["enrollment_id"], template_id)).fetchone()

                if not existing:
                    db.execute("""
                        INSERT INTO ojt_evaluations
                        (enrollment_id, template_id, criteria, max_score, template_data, created_at)
                        VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                    """, (enrollment["enrollment_id"], template_id,
                          template.get("criteria", ""), template.get("max_score", 100),
                          template.get("template_data", "")))
                    created_count += 1
            db.commit()
        except Exception as e:
            db.close()
            return self.error(f"Error applying template: {str(e)}", 400)

        db.close()
        self.success({"created_count": created_count}, f"Template applied to {created_count} trainee(s)")
