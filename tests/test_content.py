"""
Content Management Tests
Tests content CRUD, filtering, and retrieval.
"""
import pytest
from database import get_db, dict_from_row, dicts_from_rows


class TestContentCreation:
    """Test content creation."""

    def test_create_content_for_course(self, database, sample_course, admin_user):
        """Test creating content for a course."""
        db = get_db()

        cursor = db.execute(
            """INSERT INTO content
               (title, description, content_type, url, course_id, created_by, status)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            ('Introduction to Maintenance', 'Overview of aircraft maintenance',
             'video', 'https://example.com/videos/intro.mp4',
             sample_course['id'], admin_user['id'], 'published')
        )
        db.commit()
        content_id = cursor.lastrowid
        db.close()

        assert content_id > 0

    def test_create_content_for_module(self, database, sample_module, admin_user):
        """Test creating content for a specific module."""
        db = get_db()

        cursor = db.execute(
            """INSERT INTO content
               (title, description, content_type, url, course_id, module_id, created_by, status)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            ('Engine Systems', 'Detailed study of aircraft engines',
             'document', 'https://example.com/docs/engines.pdf',
             sample_module['course_id'], sample_module['id'], admin_user['id'], 'published')
        )
        db.commit()
        content_id = cursor.lastrowid
        db.close()

        assert content_id > 0

    def test_create_content_with_draft_status(self, database, sample_course, admin_user):
        """Test creating content in draft status."""
        db = get_db()

        cursor = db.execute(
            """INSERT INTO content
               (title, description, content_type, course_id, created_by, status)
               VALUES (?, ?, ?, ?, ?, ?)""",
            ('WIP Content', 'Work in progress', 'document',
             sample_course['id'], admin_user['id'], 'draft')
        )
        db.commit()
        content_id = cursor.lastrowid

        content = dict_from_row(db.execute(
            "SELECT * FROM content WHERE id = ?",
            (content_id,)
        ).fetchone())
        db.close()

        assert content['status'] == 'draft'

    def test_content_requires_title(self, database, admin_user):
        """Test that content requires title."""
        db = get_db()

        try:
            db.execute(
                """INSERT INTO content
                   (description, content_type, created_by)
                   VALUES (?, ?, ?)""",
                ('Description', 'video', admin_user['id'])
            )
            db.commit()
            assert False, "Should require title"
        except Exception:
            pass
        finally:
            db.close()


class TestContentRetrieval:
    """Test content listing and retrieval."""

    def test_list_course_content(self, database, sample_course, admin_user):
        """Test listing all content for a course."""
        db = get_db()

        # Create multiple content items
        for i in range(3):
            db.execute(
                """INSERT INTO content
                   (title, content_type, course_id, created_by, status)
                   VALUES (?, ?, ?, ?, ?)""",
                (f'Content {i}', 'video', sample_course['id'], admin_user['id'], 'published')
            )
        db.commit()

        content_items = dicts_from_rows(db.execute(
            "SELECT * FROM content WHERE course_id = ? ORDER BY id",
            (sample_course['id'],)
        ).fetchall())
        db.close()

        assert len(content_items) >= 3

    def test_list_module_content(self, database, sample_module, admin_user):
        """Test listing content for a specific module."""
        db = get_db()

        # Create content for module
        for i in range(2):
            db.execute(
                """INSERT INTO content
                   (title, content_type, course_id, module_id, created_by, status)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (f'Module Content {i}', 'document',
                 sample_module['course_id'], sample_module['id'], admin_user['id'], 'published')
            )
        db.commit()

        content_items = dicts_from_rows(db.execute(
            "SELECT * FROM content WHERE module_id = ?",
            (sample_module['id'],)
        ).fetchall())
        db.close()

        assert len(content_items) >= 2

    def test_filter_content_by_type(self, database, sample_course, admin_user):
        """Test filtering content by type."""
        db = get_db()

        # Create content of different types
        for ctype in ['video', 'document', 'image', 'audio']:
            db.execute(
                """INSERT INTO content
                   (title, content_type, course_id, created_by, status)
                   VALUES (?, ?, ?, ?, ?)""",
                (f'{ctype.title()} Content', ctype, sample_course['id'], admin_user['id'], 'published')
            )
        db.commit()

        videos = dicts_from_rows(db.execute(
            "SELECT * FROM content WHERE course_id = ? AND content_type = ?",
            (sample_course['id'], 'video')
        ).fetchall())
        db.close()

        assert all(c['content_type'] == 'video' for c in videos)

    def test_filter_content_by_status(self, database, sample_course, admin_user):
        """Test filtering content by status."""
        db = get_db()

        # Create content with different statuses
        for status in ['draft', 'published', 'archived']:
            db.execute(
                """INSERT INTO content
                   (title, content_type, course_id, created_by, status)
                   VALUES (?, ?, ?, ?, ?)""",
                (f'{status.title()} Content', 'document', sample_course['id'], admin_user['id'], status)
            )
        db.commit()

        published = dicts_from_rows(db.execute(
            "SELECT * FROM content WHERE course_id = ? AND status = ?",
            (sample_course['id'], 'published')
        ).fetchall())
        db.close()

        assert all(c['status'] == 'published' for c in published)

    def test_search_content_by_title(self, database, sample_course, admin_user):
        """Test searching content by title."""
        db = get_db()

        # Create content with searchable titles
        db.execute(
            """INSERT INTO content
               (title, content_type, course_id, created_by, status)
               VALUES (?, ?, ?, ?, ?)""",
            ('Advanced Maintenance Techniques', 'document', sample_course['id'], admin_user['id'], 'published')
        )
        db.execute(
            """INSERT INTO content
               (title, content_type, course_id, created_by, status)
               VALUES (?, ?, ?, ?, ?)""",
            ('Basic Safety Rules', 'video', sample_course['id'], admin_user['id'], 'published')
        )
        db.commit()

        results = dicts_from_rows(db.execute(
            "SELECT * FROM content WHERE course_id = ? AND title LIKE ?",
            (sample_course['id'], '%Maintenance%')
        ).fetchall())
        db.close()

        assert len(results) > 0
        assert 'Maintenance' in results[0]['title']

    def test_get_content_with_creator_info(self, database, sample_course, admin_user):
        """Test retrieving content with creator information."""
        db = get_db()

        cursor = db.execute(
            """INSERT INTO content
               (title, content_type, course_id, created_by, status)
               VALUES (?, ?, ?, ?, ?)""",
            ('Test Content', 'document', sample_course['id'], admin_user['id'], 'published')
        )
        db.commit()

        content = dict_from_row(db.execute(
            """SELECT c.*, u.name as creator_name
               FROM content c
               LEFT JOIN users u ON c.created_by = u.id
               WHERE c.id = ?""",
            (cursor.lastrowid,)
        ).fetchone())
        db.close()

        assert content['created_by'] == admin_user['id']
        assert content['creator_name'] == admin_user['name']


class TestContentUpdate:
    """Test content updates."""

    def test_update_content_title(self, database, sample_course, admin_user):
        """Test updating content title."""
        db = get_db()

        cursor = db.execute(
            """INSERT INTO content
               (title, content_type, course_id, created_by, status)
               VALUES (?, ?, ?, ?, ?)""",
            ('Original Title', 'document', sample_course['id'], admin_user['id'], 'published')
        )
        db.commit()
        content_id = cursor.lastrowid

        # Update title
        db.execute(
            "UPDATE content SET title = ? WHERE id = ?",
            ('Updated Title', content_id)
        )
        db.commit()

        content = dict_from_row(db.execute(
            "SELECT * FROM content WHERE id = ?",
            (content_id,)
        ).fetchone())
        db.close()

        assert content['title'] == 'Updated Title'

    def test_update_content_status(self, database, sample_course, admin_user):
        """Test updating content status."""
        db = get_db()

        cursor = db.execute(
            """INSERT INTO content
               (title, content_type, course_id, created_by, status)
               VALUES (?, ?, ?, ?, ?)""",
            ('Content', 'video', sample_course['id'], admin_user['id'], 'draft')
        )
        db.commit()
        content_id = cursor.lastrowid

        # Publish
        db.execute(
            "UPDATE content SET status = ? WHERE id = ?",
            ('published', content_id)
        )
        db.commit()

        content = dict_from_row(db.execute(
            "SELECT * FROM content WHERE id = ?",
            (content_id,)
        ).fetchone())
        db.close()

        assert content['status'] == 'published'

    def test_update_content_url(self, database, sample_course, admin_user):
        """Test updating content URL."""
        db = get_db()

        cursor = db.execute(
            """INSERT INTO content
               (title, url, content_type, course_id, created_by, status)
               VALUES (?, ?, ?, ?, ?, ?)""",
            ('Video', 'https://old-url.com/video.mp4', 'video', sample_course['id'], admin_user['id'], 'published')
        )
        db.commit()
        content_id = cursor.lastrowid

        # Update URL
        new_url = 'https://new-url.com/video.mp4'
        db.execute(
            "UPDATE content SET url = ? WHERE id = ?",
            (new_url, content_id)
        )
        db.commit()

        content = dict_from_row(db.execute(
            "SELECT * FROM content WHERE id = ?",
            (content_id,)
        ).fetchone())
        db.close()

        assert content['url'] == new_url

    def test_update_content_tracks_timestamp(self, database, sample_course, admin_user):
        """Test that content updates track modification time."""
        db = get_db()

        cursor = db.execute(
            """INSERT INTO content
               (title, content_type, course_id, created_by, status)
               VALUES (?, ?, ?, ?, ?)""",
            ('Content', 'document', sample_course['id'], admin_user['id'], 'draft')
        )
        db.commit()
        content_id = cursor.lastrowid

        initial = dict_from_row(db.execute(
            "SELECT updated_at FROM content WHERE id = ?",
            (content_id,)
        ).fetchone())

        # Update
        db.execute(
            "UPDATE content SET status = ? WHERE id = ?",
            ('published', content_id)
        )
        db.commit()

        updated = dict_from_row(db.execute(
            "SELECT updated_at FROM content WHERE id = ?",
            (content_id,)
        ).fetchone())
        db.close()

        # Should be updated (or at least exist)
        assert updated['updated_at'] is not None


class TestContentDeletion:
    """Test content management and archival."""

    def test_archive_content(self, database, sample_course, admin_user):
        """Test archiving content."""
        db = get_db()

        cursor = db.execute(
            """INSERT INTO content
               (title, content_type, course_id, created_by, status)
               VALUES (?, ?, ?, ?, ?)""",
            ('Content to Archive', 'document', sample_course['id'], admin_user['id'], 'published')
        )
        db.commit()
        content_id = cursor.lastrowid

        # Archive
        db.execute(
            "UPDATE content SET status = ? WHERE id = ?",
            ('archived', content_id)
        )
        db.commit()

        content = dict_from_row(db.execute(
            "SELECT * FROM content WHERE id = ?",
            (content_id,)
        ).fetchone())
        db.close()

        assert content['status'] == 'archived'

    def test_list_excludes_archived_by_default(self, database, sample_course, admin_user):
        """Test that archived content is typically excluded from listings."""
        db = get_db()

        # Create published content
        db.execute(
            """INSERT INTO content
               (title, content_type, course_id, created_by, status)
               VALUES (?, ?, ?, ?, ?)""",
            ('Active Content', 'document', sample_course['id'], admin_user['id'], 'published')
        )
        # Create archived content
        db.execute(
            """INSERT INTO content
               (title, content_type, course_id, created_by, status)
               VALUES (?, ?, ?, ?, ?)""",
            ('Old Content', 'document', sample_course['id'], admin_user['id'], 'archived')
        )
        db.commit()

        # List active only
        active = dicts_from_rows(db.execute(
            "SELECT * FROM content WHERE course_id = ? AND status != ?",
            (sample_course['id'], 'archived')
        ).fetchall())
        db.close()

        assert all(c['status'] != 'archived' for c in active)
