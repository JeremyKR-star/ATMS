# ATMS - Advanced Training Management System

Aviation training management system for pilot and mechanic education tracking.

## Requirements

- Python 3.8+
- Tornado web framework

## Quick Start

```bash
pip install -r requirements.txt
python seed.py      # Initialize database with sample data
python server.py    # Start server on port 8080
```

Or use the batch file:

```bash
start.bat
```

The browser will open automatically at `http://localhost:8080`.
Other devices on the same network can access via the IP address shown in the console.

## Test Accounts

| ID | Password | Role |
|--------|-----------|------|
| ADM001 | admin1234 | Admin |
| INS001 | inst1234 | Instructor |
| TRN001 | train1234 | Trainee |
| OJT001 | ojt12345 | OJT Admin |
| MGR001 | mgr12345 | Manager |

## Project Structure

```
ATMS_System/
├── server.py           # Main entry point (Tornado)
├── database.py         # SQLite schema & helpers
├── auth.py             # Authentication (PBKDF2 + HMAC tokens)
├── seed.py             # Sample data seeder
├── requirements.txt
├── start.bat
├── routes/
│   ├── auth_routes.py      # Login, register, profile
│   ├── user_routes.py      # User management
│   ├── course_routes.py    # Courses & modules
│   ├── schedule_routes.py  # Schedules & attendance
│   ├── evaluation_routes.py# Evaluations
│   ├── ojt_routes.py       # OJT programs
│   ├── content_routes.py   # Learning content
│   ├── report_routes.py    # Dashboard & reports
│   ├── notification_routes.py
│   ├── photo_routes.py     # Photo uploads
│   └── pilot_routes.py     # Pilot records & training
├── public/
│   └── index.html          # React SPA (single file)
├── data/
│   └── atms.db             # SQLite database (auto-created)
└── logs/
    └── access.log          # Request logs (auto-created)
```

## Key Features

- Dashboard with course/user statistics
- Course & module management
- Schedule & attendance tracking
- Evaluation management
- OJT program management
- RMAF Pilot training status (SIM + Flight sorties)
- Pilot profile carousel with photo upload
- Inline training record editing
- Weekly pilot training report
- Admin pilot CRUD (create, edit, deactivate)
- Access logging with rotating file handler
- Active users indicator
- Mobile/tablet responsive design
- Collapsible sidebar with Pilot/Mechanic/Common sections

## Notes

- Database file (`data/atms.db`) is auto-created on first run
- Delete `data/atms.db` and re-run `seed.py` to reset all data
- No npm or pip dependencies beyond Tornado (stdlib auth, CDN React)
- Frontend uses React 18 via unpkg.com CDN with Babel standalone
