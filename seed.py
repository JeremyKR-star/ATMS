"""
ATMS Sample Data Seeder
Run: python seed.py
"""
import os
import sys
from database import get_db, init_db, DB_PATH, IS_POSTGRES
from auth import hash_password

def seed():
    if not IS_POSTGRES:
        os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    init_db()
    db = get_db()
    c = db.cursor()

    # Check if already seeded
    row = db.execute("SELECT COUNT(*) as cnt FROM users").fetchone()
    if row.get('cnt', row[0]) > 0:
        print("[Seed] Data already exists. Skipping.")
        db.close()
        return

    print("[Seed] Inserting sample data...")

    # ── Users ──
    users = [
        ("ADM001", hash_password("admin1234"), "김관리자", "admin@atms.com", "010-1234-5678", "1980-03-15", "admin", "시스템 관리자", "IT부서", None),
        ("INS001", hash_password("inst1234"), "이교관", "lee.inst@atms.com", "010-2345-6789", "1985-07-22", "instructor", "수석 교관", "훈련부", "B737/B777 Type Training"),
        ("INS002", hash_password("inst1234"), "박교관", "park.inst@atms.com", "010-3456-7890", "1983-11-10", "instructor", "교관", "훈련부", "A320/A330 Type Training"),
        ("INS003", hash_password("inst1234"), "최교관", "choi.inst@atms.com", "010-4567-8901", "1987-05-18", "instructor", "교관", "OJT부", "OJT Practical Training"),
        ("TRN001", hash_password("train1234"), "정훈련생A", "jung@atms.com", "010-5678-9012", "1995-01-20", "trainee", "훈련생", "정비1팀", None),
        ("TRN002", hash_password("train1234"), "한훈련생B", "han@atms.com", "010-6789-0123", "1996-08-05", "trainee", "훈련생", "정비1팀", None),
        ("TRN003", hash_password("train1234"), "윤훈련생C", "yoon@atms.com", "010-7890-1234", "1994-12-30", "trainee", "훈련생", "정비2팀", None),
        ("TRN004", hash_password("train1234"), "임훈련생D", "lim@atms.com", "010-8901-2345", "1997-04-11", "trainee", "훈련생", "정비2팀", None),
        ("TRN005", hash_password("train1234"), "서훈련생E", "seo@atms.com", "010-9012-3456", "1993-09-25", "trainee", "훈련생", "정비3팀", None),
        ("OJT001", hash_password("ojt12345"), "강OJT관리자", "kang@atms.com", "010-1111-2222", "1982-06-14", "ojt_admin", "OJT 관리자", "OJT부", None),
        ("MGR001", hash_password("mgr12345"), "조매니저", "cho.mgr@atms.com", "010-3333-4444", "1978-02-28", "manager", "훈련팀장", "훈련부", None),
    ]
    c.executemany("""
        INSERT INTO users (employee_id, password_hash, name, email, phone, birthday, role, title, department, specialty)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, users)

    # ── Courses ──
    courses = [
        ("TT-B737-2026-01", "B737 Type Training 과정 1기", "TT", "B737 항공기 정비를 위한 기본 Type Training 과정입니다.", 8, 15, "B737", "active", "2026-03-01", "2026-04-26"),
        ("TT-A320-2026-01", "A320 Type Training 과정 1기", "TT", "A320 항공기 Type Training 과정", 6, 12, "A320", "active", "2026-03-15", "2026-04-25"),
        ("OJT-B777-2026-01", "B777 OJT 과정 1기", "OJT", "B777 정비 OJT 현장실습 과정", 12, 10, "B777", "planned", "2026-05-01", "2026-07-24"),
        ("TT-B737-2025-02", "B737 Type Training 과정 2기 (2025)", "TT", "2025년 하반기 B737 TT 과정", 8, 15, "B737", "completed", "2025-09-01", "2025-10-26"),
    ]
    c.executemany("""
        INSERT INTO courses (code, name, type, description, duration_weeks, max_trainees, aircraft_type, status, start_date, end_date)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, courses)

    # ── Course Modules ──
    modules = [
        (1, "항공기 시스템 개론", "B737 기본 시스템 구조 이해", 1, 16, "theory"),
        (1, "ATA 21 - 공조 시스템", "에어컨 및 압력 시스템", 2, 12, "theory"),
        (1, "ATA 27 - 조종 시스템", "비행 조종 시스템", 3, 12, "theory"),
        (1, "ATA 32 - 착륙장치", "착륙장치 시스템", 4, 10, "theory"),
        (1, "실기 평가 1", "중간 실기 평가", 5, 4, "assessment"),
        (1, "ATA 71-80 - 엔진 시스템", "파워플랜트 시스템", 6, 16, "theory"),
        (1, "종합 실기 시험", "최종 실기 평가", 7, 8, "assessment"),
        (1, "과정 마무리", "과정 총정리 및 피드백", 8, 4, "wrap_up"),
        (2, "A320 시스템 개론", "A320 기본 시스템 구조", 1, 14, "theory"),
        (2, "FCOM 및 AMM 활용", "매뉴얼 활용법", 2, 10, "theory"),
        (2, "A320 실기 평가", "A320 실기 시험", 3, 6, "assessment"),
    ]
    c.executemany("""
        INSERT INTO course_modules (course_id, name, description, order_num, duration_hours, module_type)
        VALUES (?, ?, ?, ?, ?, ?)
    """, modules)

    # ── Course Instructors ──
    c.executemany("INSERT INTO course_instructors (course_id, instructor_id, role) VALUES (?, ?, ?)", [
        (1, 2, "lead"), (1, 3, "assistant"), (2, 3, "lead"), (3, 4, "lead"), (4, 2, "lead"),
    ])

    # ── Enrollments ──
    enrollments = [
        (1, 5, "in_progress", 45.0, None), (1, 6, "in_progress", 38.0, None),
        (1, 7, "in_progress", 52.0, None), (1, 8, "enrolled", 10.0, None),
        (2, 9, "in_progress", 60.0, None), (2, 5, "enrolled", 5.0, None),
        (4, 5, "completed", 100.0, 92.5), (4, 6, "completed", 100.0, 88.0),
        (4, 7, "completed", 100.0, 95.0), (4, 9, "failed", 100.0, 55.0),
    ]
    c.executemany("INSERT INTO enrollments (course_id, trainee_id, status, progress, final_score) VALUES (?, ?, ?, ?, ?)", enrollments)

    # ── Schedules ──
    schedules = [
        (1, 2, 1, "B737 시스템 개론 강의", "2026-03-11", "09:00", "12:00", "Training Room A", "lecture", None),
        (1, 2, 2, "ATA 21 공조 시스템", "2026-03-12", "09:00", "12:00", "Training Room A", "lecture", None),
        (1, 3, 3, "ATA 27 조종 시스템 실습", "2026-03-13", "13:00", "17:00", "Hangar Lab 1", "practical", None),
        (1, 2, 5, "중간 실기 평가", "2026-03-18", "09:00", "13:00", "Assessment Room", "assessment", None),
        (2, 3, 9, "A320 시스템 개론", "2026-03-15", "09:00", "12:00", "Training Room B", "lecture", None),
        (1, 2, 6, "엔진 시스템 이론", "2026-03-19", "09:00", "12:00", "Training Room A", "lecture", None),
        (1, None, None, "교관 회의", "2026-03-14", "15:00", "16:00", "회의실 1", "meeting", "주간 교관 회의"),
    ]
    c.executemany("""
        INSERT INTO schedules (course_id, instructor_id, module_id, title, schedule_date, start_time, end_time, room, schedule_type, notes)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, schedules)

    # ── Attendance ──
    attendance = [
        (1, 5, "present", "08:55"), (1, 6, "present", "08:58"), (1, 7, "late", "09:12"), (1, 8, "absent", None),
        (2, 5, "present", "08:50"), (2, 6, "present", "08:57"), (2, 7, "present", "08:59"), (2, 8, "excused", None),
    ]
    c.executemany("INSERT INTO attendance (schedule_id, trainee_id, status, check_in_time) VALUES (?, ?, ?, ?)", attendance)

    # ── Evaluations ──
    evaluations = [
        (1, 1, 5, 2, "quiz", "시스템 개론 퀴즈", 85, 100, "B+", "Good understanding", "graded", None, "2026-03-11", "2026-03-11"),
        (1, 1, 6, 2, "quiz", "시스템 개론 퀴즈", 78, 100, "C+", "Needs more study on hydraulics", "graded", None, "2026-03-11", "2026-03-11"),
        (1, 1, 7, 2, "quiz", "시스템 개론 퀴즈", 92, 100, "A", "Excellent", "graded", None, "2026-03-11", "2026-03-11"),
        (1, 5, 5, 2, "exam", "중간 필기시험", None, 100, None, None, "pending", "2026-03-18", None, None),
        (1, 5, 6, 2, "exam", "중간 필기시험", None, 100, None, None, "pending", "2026-03-18", None, None),
        (4, None, 5, 2, "exam", "최종 시험", 92.5, 100, "A", "Outstanding performance", "graded", None, "2025-10-26", "2025-10-26"),
        (4, None, 6, 2, "exam", "최종 시험", 88.0, 100, "B+", "Good overall", "graded", None, "2025-10-26", "2025-10-26"),
        (4, None, 7, 2, "exam", "최종 시험", 95.0, 100, "A+", "Excellent performance", "graded", None, "2025-10-26", "2025-10-26"),
    ]
    c.executemany("""
        INSERT INTO evaluations (course_id, module_id, trainee_id, evaluator_id, eval_type, title, score, max_score, grade, feedback, status, due_date, submitted_at, graded_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, evaluations)

    # ── Content / Materials ──
    content = [
        (1, 1, "B737 시스템 개론 교재", "ebook", "B737 시스템 기본 이론 교재 (PDF)", "/files/b737_systems_intro.pdf", 2),
        (1, 2, "ATA 21 공조시스템 교안", "lesson_plan", "공조시스템 강의 교안", "/files/ata21_lesson.pdf", 2),
        (1, 5, "중간 실기 평가지", "assessment", "실기 평가 체크리스트", "/files/midterm_practical.pdf", 2),
        (1, None, "B737 AMM 참고자료", "supplementary", "B737 AMM 주요 챕터 발췌", "/files/b737_amm_ref.pdf", 2),
        (2, 9, "A320 시스템 개론 교재", "ebook", "A320 기본 이론 교재", "/files/a320_systems.pdf", 3),
        (1, None, "정비 안전 동영상", "video", "항공기 정비 안전 교육 영상", "/files/safety_video.mp4", 2),
    ]
    c.executemany("""
        INSERT INTO content (course_id, module_id, title, content_type, description, file_path, uploaded_by)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, content)

    # ── OJT Programs ──
    c.execute("INSERT INTO ojt_programs (name, description, duration_weeks, aircraft_type, status) VALUES ('B777 엔진정비 OJT', 'B777 엔진 정비 실습 과정 - GE90 엔진 중심', 12, 'B777', 'planned')")
    c.execute("INSERT INTO ojt_programs (name, description, duration_weeks, aircraft_type, status) VALUES ('B737 기체정비 OJT', 'B737 기체 구조 점검 및 정비 OJT', 8, 'B737', 'active')")

    # ── OJT Tasks ──
    ojt_tasks = [
        (1, "엔진 외관 점검", "GE90 엔진 외관 점검 절차 숙달", 1, 8, "외관 점검 체크리스트 완료"),
        (1, "보어스코프 검사", "엔진 내부 보어스코프 검사 실습", 2, 12, "보어스코프 리포트 작성"),
        (1, "오일 시스템 점검", "엔진 오일 시스템 서비싱", 3, 6, "오일량 측정 및 보급 완료"),
        (1, "엔진 런업 참관", "엔진 시운전 참관 및 데이터 기록", 4, 4, "런업 데이터 시트 작성"),
        (2, "기체 외관 점검", "B737 기체 외관 점검 (Walk-around)", 1, 10, "점검 리포트 작성"),
        (2, "구조 수리 기초", "기체 구조 수리 기본 실습", 2, 16, "수리 작업 완료 및 검사 통과"),
    ]
    c.executemany("INSERT INTO ojt_tasks (program_id, name, description, order_num, required_hours, criteria) VALUES (?, ?, ?, ?, ?, ?)", ojt_tasks)

    # ── OJT Enrollments ──
    c.executemany("INSERT INTO ojt_enrollments (program_id, trainee_id, trainer_id, status, progress) VALUES (?, ?, ?, ?, ?)", [
        (2, 5, 4, "in_progress", 35.0),
        (2, 6, 4, "enrolled", 0.0),
    ])

    # ── OJT Evaluations ──
    c.executemany("INSERT INTO ojt_evaluations (enrollment_id, task_id, evaluator_id, score, status, feedback, eval_date) VALUES (?, ?, ?, ?, ?, ?, ?)", [
        (1, 5, 4, 88, "pass", "외관 점검 절차 잘 수행함", "2026-03-05"),
    ])

    # ── Notifications ──
    notifications = [
        (5, "과정 등록 완료", "B737 Type Training 과정에 등록되었습니다.", "success", "/courses/1"),
        (5, "일정 안내", "내일 09:00 시스템 개론 강의가 있습니다.", "info", "/schedule"),
        (5, "평가 안내", "중간 필기시험이 3/18 예정입니다.", "warning", "/evaluations"),
        (6, "과정 등록 완료", "B737 Type Training 과정에 등록되었습니다.", "success", "/courses/1"),
        (2, "강의 배정", "B737 TT 과정 수석교관으로 배정되었습니다.", "info", "/courses/1"),
    ]
    c.executemany("INSERT INTO notifications (user_id, title, message, notification_type, link) VALUES (?, ?, ?, ?, ?)", notifications)

    # ── Surveys ──
    c.executemany("INSERT INTO surveys (course_id, trainee_id, overall_rating, instructor_rating, content_rating, facility_rating, comments) VALUES (?, ?, ?, ?, ?, ?, ?)", [
        (4, 5, 4.5, 4.8, 4.2, 4.0, "교관님 강의가 매우 유익했습니다. 실습 시간이 좀 더 있었으면 좋겠습니다."),
        (4, 6, 4.0, 4.5, 4.0, 3.8, "전반적으로 좋은 과정이었습니다."),
        (4, 7, 4.8, 5.0, 4.5, 4.2, "최고의 과정입니다. 적극 추천합니다."),
    ])

    # ═══════════════════════════════════════════════
    # ── Pilot Nationalities ──
    # ═══════════════════════════════════════════════
    nationalities = [
        ('Malaysia', '말레이시아', 1),
        ('Poland', '폴란드', 2),
        ('Iraq', '이라크', 3),
    ]
    c.executemany("INSERT INTO pilot_nationalities (code, label_ko, sort_order) VALUES (?,?,?)", nationalities)

    # ═══════════════════════════════════════════════
    # ── Pilot Data ──
    # ═══════════════════════════════════════════════

    # ── Pilots (personal records) ──
    pilots = [
        ('Mohd Jamil bin Awang', 'Jamil', 'Major', 'RMAF-2019-0451', 'RMAF-01', 'Malaysia',
         'No. 12 Squadron', '1990-04-12', 'T-50 Transition Batch 1', '2026-01-26', '2026-05-08',
         '+60-11-2345-6701', 'jamil@rmaf.mil.my', '', 1),
        ('Muhmmad Ashraf bin Wahab', 'Ashraf', 'Major', 'RMAF-2019-0467', 'RMAF-02', 'Malaysia',
         'No. 12 Squadron', '1991-08-23', 'T-50 Transition Batch 1', '2026-01-26', '2026-05-08',
         '+60-11-2345-6702', 'ashraf@rmaf.mil.my', '', 2),
        ('Ahmad Nur Ikhwan bin Ahmad Tridi', 'Ikhwan', 'Major', 'RMAF-2020-0512', 'RMAF-03', 'Malaysia',
         'No. 15 Squadron', '1992-01-15', 'T-50 Transition Batch 1', '2026-01-26', '2026-05-08',
         '+60-11-2345-6703', 'ikhwan@rmaf.mil.my', '', 3),
        ('Muhammad Faiz bin Abdul Kadir', 'Faiz', 'Major', 'RMAF-2020-0528', 'RMAF-04', 'Malaysia',
         'No. 15 Squadron', '1991-11-30', 'T-50 Transition Batch 1', '2026-01-26', '2026-05-08',
         '+60-11-2345-6704', 'faiz@rmaf.mil.my', '', 4),
        ('Muhamad Luqman bin Mohamad Aziz', 'Luqman', 'Major', 'RMAF-2020-0541', 'RMAF-05', 'Malaysia',
         'No. 18 Squadron', '1993-06-08', 'T-50 Transition Batch 1', '2026-01-26', '2026-05-08',
         '+60-11-2345-6705', 'luqman@rmaf.mil.my', '', 5),
        ('Abdul Samad bin Daud', 'Samad', 'Major', 'RMAF-2021-0603', 'RMAF-06', 'Malaysia',
         'No. 18 Squadron', '1994-03-21', 'T-50 Transition Batch 1', '2026-01-26', '2026-05-08',
         '+60-11-2345-6706', 'samad@rmaf.mil.my', '', 6),
    ]
    # Polish pilots
    pilots += [
        ('Tomasz Kowalski', 'Kowalski', 'Captain', 'PAF-2024-0112', 'PLK-01', 'Poland',
         'No. 12 Squadron', '1992-05-18', 'T-50 Transition Batch 1', '2026-01-26', '2026-05-08',
         '+48-501-234-567', 'kowalski@paf.mil.pl', '', 7),
        ('Jakub Wiśniewski', 'Wisniewski', 'First Lieutenant', 'PAF-2024-0118', 'PLK-02', 'Poland',
         'No. 15 Squadron', '1994-09-03', 'T-50 Transition Batch 1', '2026-01-26', '2026-05-08',
         '+48-502-345-678', 'wisniewski@paf.mil.pl', '', 8),
    ]
    # Iraqi pilots
    pilots += [
        ('Ahmed Al-Rashid', 'Al-Rashid', 'Major', 'IQAF-2023-0301', 'IQA-01', 'Iraq',
         'No. 18 Squadron', '1991-03-27', 'T-50 Transition Batch 1', '2026-01-26', '2026-05-08',
         '+964-770-123-4567', 'alrashid@iqaf.mil.iq', '', 9),
        ('Omar Hassan', 'Hassan', 'Captain', 'IQAF-2023-0315', 'IQA-02', 'Iraq',
         'No. 18 Squadron', '1993-11-14', 'T-50 Transition Batch 1', '2026-01-26', '2026-05-08',
         '+964-770-234-5678', 'hassan@iqaf.mil.iq', '', 10),
    ]
    c.executemany("""
        INSERT INTO pilots (name, short_name, rank, service_number, callsign, nationality,
            squadron, date_of_birth, course_class, training_start_date, training_end_date,
            phone, email, notes, sort_order)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
    """, pilots)

    # ── Pilot Training Courses (SIM + Flight syllabus) ──
    sim_courses = [
        ('C-01', 'sim', 1, 'TR-1S', 'Normal Procedure/CRM', '1:00', 1),
        ('C-02', 'sim', 2, 'TR-2S', 'Normal Procedure/CRM', '1:00', 2),
        ('C-03', 'sim', 3, 'TR-3S', 'Normal/Emergency Procedure, CRM', '1:00', 3),
        ('C-04', 'sim', 4, 'TR-4S', 'Normal/Emergency Procedure, CRM', '1:00', 4),
        ('C-05', 'sim', 5, 'TR-5S', 'Transition/Aerobatic', '1:00', 5),
        ('C-06', 'sim', 6, 'TR-6S', 'Transition/Aerobatic', '1:00', 6),
        ('C-07', 'sim', 7, 'TR-7S', 'Transition/Aerobatic', '1:00', 7),
        ('C-08', 'sim', 8, 'TR-8S', 'Normal/Emergency Procedure, CRM', '1:00', 8),
        ('C-09', 'sim', 9, 'TR-9S', 'Normal/Emergency Procedure, CRM', '1:00', 9),
        ('C-10', 'sim', 10, 'INST-1S', 'Basic Instrument', '1:00', 10),
        ('C-11', 'sim', 11, 'INST-2S', 'Basic Instrument', '1:00', 11),
        ('C-12', 'sim', 12, 'INST-3S', 'Advanced Instrument', '1:00', 12),
        ('C-13', 'sim', 13, 'INST-4S', 'Advanced Instrument', '1:00', 13),
        ('C-14', 'sim', 14, 'INST-5S', 'Advanced Instrument', '1:00', 14),
        ('C-15', 'sim', 15, 'FD-1S', 'Normal & Tactical Formation', '1:00', 15),
        ('C-16', 'sim', 16, 'FD-2S', 'Normal & Tactical Formation', '1:00', 16),
        ('C-17', 'sim', 17, 'FD-3S', 'Normal & Tactical Formation', '1:00', 17),
        ('C-18', 'sim', 18, 'NN-1S', 'Night Formation/Navigation', '1:00', 18),
    ]
    flt_courses = [
        ('C-19', 'flight', 1, 'TR-1', 'Familiarization/CRM', '0:46', 19),
        ('C-20', 'flight', 2, 'TR-2', 'Transition/Aerobatic', '0:46', 20),
        ('C-21', 'flight', 3, 'TR-3', 'Transition/Aerobatic', '0:46', 21),
        ('C-22', 'flight', 4, 'TR-4', 'Transition/Aerobatic', '0:46', 22),
        ('C-23', 'flight', 5, 'TR-5', 'Transition/Aerobatic', '0:46', 23),
        ('C-24', 'flight', 6, 'TR-6', 'Transition/Aerobatic', '0:46', 24),
        ('C-25', 'flight', 7, 'INST-1', 'Basic Instrument', '0:46', 25),
        ('C-26', 'flight', 8, 'INST-2', 'Advanced Instrument', '0:46', 26),
        ('C-27', 'flight', 9, 'FD-1', 'Basic & Tactical Formation', '0:46', 27),
        ('C-28', 'flight', 10, 'FD-2', 'Basic & Tactical Formation', '0:46', 28),
        ('C-29', 'flight', 11, 'NN-1', 'Night Formation/Navigation', '0:46', 29),
        ('C-30', 'flight', 12, 'NN-2', 'Night Formation/Navigation', '0:46', 30),
        ('C-31', 'flight', 13, 'NN-3', 'Night Formation/Navigation', '0:46', 31),
    ]
    c.executemany("INSERT INTO pilot_courses (course_no, category, seq_no, subject, contents, duration, sort_order) VALUES (?,?,?,?,?,?,?)", sim_courses + flt_courses)

    # ── Pilot Training Records (from Excel data) ──
    # Map: subject -> pilot_courses.id (sim 1-18, flight 19-31)
    # pilot IDs: Jamil=1, Ashraf=2, Ikhwan=3, Faiz=4, Luqman=5, Samad=6
    training_records = [
        # Jamil (pilot 1): SIM TR-1S..TR-5S, INST-1S, INST-2S
        (1, 1, '2026-02-09', '1:00'), (1, 2, '2026-02-11', '1:00'), (1, 3, '2026-02-12', '1:00'),
        (1, 4, '2026-02-13', '1:00'), (1, 5, '2026-02-24', '1:00'),
        (1, 10, '2026-02-26', '1:00'), (1, 11, '2026-02-27', '1:00'),
        # Ashraf (pilot 2): SIM TR-1S..TR-7S, INST-1S, INST-2S + Flight TR-1
        (2, 1, '2026-02-09', '1:00'), (2, 2, '2026-02-10', '1:00'), (2, 3, '2026-02-11', '1:00'),
        (2, 4, '2026-02-12', '1:00'), (2, 5, '2026-02-13', '1:00'), (2, 6, '2026-02-23', '1:00'),
        (2, 7, '2026-03-03', '1:00'), (2, 10, '2026-02-24', '1:00'), (2, 11, '2026-02-27', '1:00'),
        (2, 19, '2026-03-05', '0:46'),
        # Ikhwan (pilot 3): SIM TR-1S..TR-5S, INST-1S, INST-2S
        (3, 1, '2026-02-09', '1:00'), (3, 2, '2026-02-11', '1:00'), (3, 3, '2026-02-12', '1:00'),
        (3, 4, '2026-02-13', '1:00'), (3, 5, '2026-02-24', '1:00'),
        (3, 10, '2026-02-25', '1:00'), (3, 11, '2026-02-27', '1:00'),
        # Faiz (pilot 4): SIM TR-1S..TR-5S, INST-1S, INST-2S
        (4, 1, '2026-02-09', '1:00'), (4, 2, '2026-02-11', '1:00'), (4, 3, '2026-02-12', '1:00'),
        (4, 4, '2026-02-19', '1:00'), (4, 5, '2026-02-24', '1:00'),
        (4, 10, '2026-02-25', '1:00'), (4, 11, '2026-02-26', '1:00'),
        # Luqman (pilot 5): SIM TR-1S..TR-8S, INST-1S, INST-2S + Flight TR-1
        (5, 1, '2026-02-09', '1:00'), (5, 2, '2026-02-10', '1:00'), (5, 3, '2026-02-11', '1:00'),
        (5, 4, '2026-02-12', '1:00'), (5, 5, '2026-02-13', '1:00'), (5, 6, '2026-02-23', '1:00'),
        (5, 7, '2026-03-04', '1:00'), (5, 8, '2026-03-05', '1:00'),
        (5, 10, '2026-02-27', '1:00'), (5, 11, '2026-03-03', '1:00'),
        (5, 19, '2026-03-05', '0:46'),
        # Samad (pilot 6): SIM TR-1S..TR-9S, INST-1S, INST-2S
        (6, 1, '2026-02-09', '1:00'), (6, 2, '2026-02-10', '1:00'), (6, 3, '2026-02-11', '1:00'),
        (6, 4, '2026-02-13', '1:00'), (6, 5, '2026-02-20', '1:00'), (6, 6, '2026-02-23', '1:00'),
        (6, 7, '2026-03-04', '1:00'), (6, 8, '2026-03-05', '1:00'), (6, 9, '2026-03-05', '1:00'),
        (6, 10, '2026-02-27', '1:00'), (6, 11, '2026-03-03', '1:00'),
        # Kowalski (pilot 7 - Poland): SIM TR-1S..TR-4S, INST-1S
        (7, 1, '2026-02-10', '1:00'), (7, 2, '2026-02-12', '1:00'), (7, 3, '2026-02-13', '1:00'),
        (7, 4, '2026-02-19', '1:00'), (7, 10, '2026-02-25', '1:00'),
        # Wisniewski (pilot 8 - Poland): SIM TR-1S..TR-3S
        (8, 1, '2026-02-10', '1:00'), (8, 2, '2026-02-12', '1:00'), (8, 3, '2026-02-14', '1:00'),
        # Al-Rashid (pilot 9 - Iraq): SIM TR-1S..TR-5S, INST-1S
        (9, 1, '2026-02-09', '1:00'), (9, 2, '2026-02-11', '1:00'), (9, 3, '2026-02-12', '1:00'),
        (9, 4, '2026-02-14', '1:00'), (9, 5, '2026-02-25', '1:00'), (9, 10, '2026-02-27', '1:00'),
        # Hassan (pilot 10 - Iraq): SIM TR-1S..TR-3S
        (10, 1, '2026-02-10', '1:00'), (10, 2, '2026-02-12', '1:00'), (10, 3, '2026-02-14', '1:00'),
    ]
    c.executemany("INSERT INTO pilot_training (pilot_id, course_id, completed_date, completed_time) VALUES (?,?,?,?)", training_records)

    db.commit()
    db.close()
    print("[Seed] Sample data inserted successfully!")
    print("  - 11 users (admin/instructors/trainees/ojt_admin/manager)")
    print("  - 4 courses, 11 modules")
    print("  - 10 enrollments, 7 schedules, 8 attendance records")
    print("  - 8 evaluations, 6 content items")
    print("  - 2 OJT programs, 6 OJT tasks, 2 OJT enrollments")
    print("  - 5 notifications, 3 surveys")
    print("  - 10 pilots (6 Malaysian + 2 Polish + 2 Iraqi), 3 nationalities")
    print("  - 31 training courses, 70+ training records")
    print()
    print("Login credentials:")
    print("  Admin:      ADM001 / admin1234")
    print("  Instructor: INS001 / inst1234")
    print("  Trainee:    TRN001 / train1234")
    print("  OJT Admin:  OJT001 / ojt12345")
    print("  Manager:    MGR001 / mgr12345")


if __name__ == "__main__":
    seed()
