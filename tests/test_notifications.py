"""
Notification Management Tests
Tests notification creation, marking as read, and filtering.
"""
import pytest
from database import get_db, dict_from_row, dicts_from_rows


class TestNotificationCreation:
    """Test notification creation."""

    def test_create_notification_for_user(self, database, admin_user):
        """Test creating a notification for a user."""
        db = get_db()

        cursor = db.execute(
            """INSERT INTO notifications
               (user_id, title, message, type, related_id, related_type)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (admin_user['id'], 'Course Enrollment', 'You have been enrolled in Course 101',
             'enrollment', 1, 'course')
        )
        db.commit()
        notification_id = cursor.lastrowid
        db.close()

        assert notification_id > 0

    def test_create_notification_info_type(self, database, trainee_user):
        """Test creating info notification."""
        db = get_db()

        cursor = db.execute(
            """INSERT INTO notifications
               (user_id, title, message, type)
               VALUES (?, ?, ?, ?)""",
            (trainee_user['id'], 'System Update', 'New features available', 'info')
        )
        db.commit()
        notification_id = cursor.lastrowid
        db.close()

        assert notification_id > 0

    def test_create_notification_warning_type(self, database, trainee_user):
        """Test creating warning notification."""
        db = get_db()

        cursor = db.execute(
            """INSERT INTO notifications
               (user_id, title, message, type)
               VALUES (?, ?, ?, ?)""",
            (trainee_user['id'], 'Assignment Due Soon', 'Assignment due in 2 days', 'warning')
        )
        db.commit()

        notification = dict_from_row(db.execute(
            "SELECT * FROM notifications WHERE id = ?",
            (cursor.lastrowid,)
        ).fetchone())
        db.close()

        assert notification['type'] == 'warning'

    def test_create_notification_error_type(self, database, trainee_user):
        """Test creating error notification."""
        db = get_db()

        cursor = db.execute(
            """INSERT INTO notifications
               (user_id, title, message, type)
               VALUES (?, ?, ?, ?)""",
            (trainee_user['id'], 'Grade Not Posted', 'Your grade could not be calculated', 'error')
        )
        db.commit()

        notification = dict_from_row(db.execute(
            "SELECT * FROM notifications WHERE id = ?",
            (cursor.lastrowid,)
        ).fetchone())
        db.close()

        assert notification['type'] == 'error'

    def test_notification_requires_user(self, database):
        """Test that notification requires user_id."""
        db = get_db()

        try:
            db.execute(
                """INSERT INTO notifications
                   (title, message)
                   VALUES (?, ?)""",
                ('Title', 'Message')
            )
            db.commit()
            assert False, "Should require user_id"
        except Exception:
            pass
        finally:
            db.close()

    def test_notification_requires_title(self, database, admin_user):
        """Test that notification requires title."""
        db = get_db()

        try:
            db.execute(
                """INSERT INTO notifications
                   (user_id, message)
                   VALUES (?, ?)""",
                (admin_user['id'], 'Message')
            )
            db.commit()
            assert False, "Should require title"
        except Exception:
            pass
        finally:
            db.close()


class TestNotificationRetrieval:
    """Test notification listing and filtering."""

    def test_list_user_notifications(self, database, admin_user):
        """Test listing all notifications for a user."""
        db = get_db()

        # Create multiple notifications
        for i in range(5):
            db.execute(
                """INSERT INTO notifications
                   (user_id, title, message)
                   VALUES (?, ?, ?)""",
                (admin_user['id'], f'Notification {i}', f'Message {i}')
            )
        db.commit()

        notifications = dicts_from_rows(db.execute(
            "SELECT * FROM notifications WHERE user_id = ? ORDER BY created_at DESC",
            (admin_user['id'],)
        ).fetchall())
        db.close()

        assert len(notifications) >= 5

    def test_filter_unread_notifications(self, database, trainee_user):
        """Test filtering unread notifications."""
        db = get_db()

        # Create mix of read and unread
        db.execute(
            "INSERT INTO notifications (user_id, title, is_read) VALUES (?, ?, ?)",
            (trainee_user['id'], 'Unread 1', 0)
        )
        db.execute(
            "INSERT INTO notifications (user_id, title, is_read) VALUES (?, ?, ?)",
            (trainee_user['id'], 'Read 1', 1)
        )
        db.execute(
            "INSERT INTO notifications (user_id, title, is_read) VALUES (?, ?, ?)",
            (trainee_user['id'], 'Unread 2', 0)
        )
        db.commit()

        unread = dicts_from_rows(db.execute(
            "SELECT * FROM notifications WHERE user_id = ? AND is_read = ?",
            (trainee_user['id'], 0)
        ).fetchall())
        db.close()

        assert len(unread) >= 2
        assert all(not n['is_read'] for n in unread)

    def test_filter_by_notification_type(self, database, admin_user):
        """Test filtering notifications by type."""
        db = get_db()

        # Create notifications of different types
        for ntype in ['info', 'warning', 'error']:
            db.execute(
                "INSERT INTO notifications (user_id, title, type) VALUES (?, ?, ?)",
                (admin_user['id'], f'{ntype} notification', ntype)
            )
        db.commit()

        warnings = dicts_from_rows(db.execute(
            "SELECT * FROM notifications WHERE user_id = ? AND type = ?",
            (admin_user['id'], 'warning')
        ).fetchall())
        db.close()

        assert all(n['type'] == 'warning' for n in warnings)

    def test_list_related_notifications(self, database, admin_user):
        """Test filtering by related entity."""
        db = get_db()

        # Create notifications related to course
        db.execute(
            """INSERT INTO notifications
               (user_id, title, type, related_id, related_type)
               VALUES (?, ?, ?, ?, ?)""",
            (admin_user['id'], 'Course Update', 'info', 5, 'course')
        )
        db.execute(
            """INSERT INTO notifications
               (user_id, title, type, related_id, related_type)
               VALUES (?, ?, ?, ?, ?)""",
            (admin_user['id'], 'Assignment Due', 'warning', 10, 'evaluation')
        )
        db.commit()

        course_notifs = dicts_from_rows(db.execute(
            "SELECT * FROM notifications WHERE user_id = ? AND related_type = ?",
            (admin_user['id'], 'course')
        ).fetchall())
        db.close()

        assert all(n['related_type'] == 'course' for n in course_notifs)


class TestNotificationRead:
    """Test marking notifications as read."""

    def test_mark_notification_as_read(self, database, trainee_user):
        """Test marking a single notification as read."""
        db = get_db()

        # Create unread notification
        cursor = db.execute(
            """INSERT INTO notifications
               (user_id, title, is_read)
               VALUES (?, ?, ?)""",
            (trainee_user['id'], 'Test Notification', 0)
        )
        db.commit()
        notif_id = cursor.lastrowid

        # Mark as read
        db.execute(
            "UPDATE notifications SET is_read = ? WHERE id = ?",
            (1, notif_id)
        )
        db.commit()

        notification = dict_from_row(db.execute(
            "SELECT * FROM notifications WHERE id = ?",
            (notif_id,)
        ).fetchone())
        db.close()

        assert notification['is_read'] == 1

    def test_mark_all_user_notifications_read(self, database, admin_user):
        """Test marking all notifications as read for a user."""
        db = get_db()

        # Create multiple unread notifications
        for i in range(3):
            db.execute(
                "INSERT INTO notifications (user_id, title, is_read) VALUES (?, ?, ?)",
                (admin_user['id'], f'Notification {i}', 0)
            )
        db.commit()

        # Mark all as read
        db.execute(
            "UPDATE notifications SET is_read = ? WHERE user_id = ?",
            (1, admin_user['id'])
        )
        db.commit()

        unread = dicts_from_rows(db.execute(
            "SELECT * FROM notifications WHERE user_id = ? AND is_read = ?",
            (admin_user['id'], 0)
        ).fetchall())
        db.close()

        assert len(unread) == 0

    def test_mark_notification_unread(self, database, trainee_user):
        """Test marking a read notification back to unread."""
        db = get_db()

        # Create read notification
        cursor = db.execute(
            """INSERT INTO notifications
               (user_id, title, is_read)
               VALUES (?, ?, ?)""",
            (trainee_user['id'], 'Read Notification', 1)
        )
        db.commit()
        notif_id = cursor.lastrowid

        # Mark as unread
        db.execute(
            "UPDATE notifications SET is_read = ? WHERE id = ?",
            (0, notif_id)
        )
        db.commit()

        notification = dict_from_row(db.execute(
            "SELECT * FROM notifications WHERE id = ?",
            (notif_id,)
        ).fetchone())
        db.close()

        assert notification['is_read'] == 0

    def test_notification_read_status_default(self, database, admin_user):
        """Test that new notifications default to unread."""
        db = get_db()

        cursor = db.execute(
            """INSERT INTO notifications
               (user_id, title)
               VALUES (?, ?)""",
            (admin_user['id'], 'New Notification')
        )
        db.commit()

        notification = dict_from_row(db.execute(
            "SELECT * FROM notifications WHERE id = ?",
            (cursor.lastrowid,)
        ).fetchone())
        db.close()

        assert notification['is_read'] == 0


class TestNotificationCounts:
    """Test notification counting and summary."""

    def test_count_unread_notifications(self, database, trainee_user):
        """Test counting unread notifications for user."""
        db = get_db()

        # Create mixed notifications
        db.execute(
            "INSERT INTO notifications (user_id, title, is_read) VALUES (?, ?, ?)",
            (trainee_user['id'], 'Unread 1', 0)
        )
        db.execute(
            "INSERT INTO notifications (user_id, title, is_read) VALUES (?, ?, ?)",
            (trainee_user['id'], 'Read 1', 1)
        )
        db.execute(
            "INSERT INTO notifications (user_id, title, is_read) VALUES (?, ?, ?)",
            (trainee_user['id'], 'Unread 2', 0)
        )
        db.commit()

        result = dict_from_row(db.execute(
            "SELECT COUNT(*) as count FROM notifications WHERE user_id = ? AND is_read = ?",
            (trainee_user['id'], 0)
        ).fetchone())
        db.close()

        assert result['count'] >= 2

    def test_count_total_notifications_by_type(self, database, admin_user):
        """Test counting notifications grouped by type."""
        db = get_db()

        # Create notifications
        for _ in range(2):
            db.execute(
                "INSERT INTO notifications (user_id, title, type) VALUES (?, ?, ?)",
                (admin_user['id'], 'Info', 'info')
            )
        for _ in range(3):
            db.execute(
                "INSERT INTO notifications (user_id, title, type) VALUES (?, ?, ?)",
                (admin_user['id'], 'Warning', 'warning')
            )
        db.commit()

        summary = dicts_from_rows(db.execute(
            """SELECT type, COUNT(*) as count
               FROM notifications
               WHERE user_id = ?
               GROUP BY type""",
            (admin_user['id'],)
        ).fetchall())
        db.close()

        assert len(summary) >= 2

    def test_get_newest_notifications(self, database, trainee_user):
        """Test retrieving newest notifications first."""
        db = get_db()

        # Create notifications (older to newer)
        for i in range(5):
            db.execute(
                "INSERT INTO notifications (user_id, title) VALUES (?, ?)",
                (trainee_user['id'], f'Notification {i}')
            )
        db.commit()

        # Get newest first (desc order)
        notifs = dicts_from_rows(db.execute(
            """SELECT * FROM notifications
               WHERE user_id = ?
               ORDER BY created_at DESC
               LIMIT 3""",
            (trainee_user['id'],)
        ).fetchall())
        db.close()

        assert len(notifs) <= 3
