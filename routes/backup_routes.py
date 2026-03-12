"""Database Backup and Restore Routes - Admin only"""
import os
import shutil
from datetime import datetime
from routes.auth_routes import BaseHandler
from database import DB_PATH, get_db, dicts_from_rows
from auth import require_auth


BACKUP_DIR = os.path.join(os.path.dirname(DB_PATH), "backups")


def ensure_backup_dir():
    """Ensure backups directory exists"""
    os.makedirs(BACKUP_DIR, exist_ok=True)


class BackupCreateHandler(BaseHandler):
    """Create a new backup of the database"""
    
    @require_auth(roles=["admin"])
    def post(self):
        """Create a timestamped backup of the SQLite database"""
        try:
            ensure_backup_dir()
            
            # Generate backup filename with timestamp
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            backup_filename = f"atms_backup_{timestamp}.db"
            backup_path = os.path.join(BACKUP_DIR, backup_filename)
            
            # Copy database file
            shutil.copy2(DB_PATH, backup_path)
            
            # Get file size
            file_size = os.path.getsize(backup_path)
            
            self.success({
                "filename": backup_filename,
                "size": file_size,
                "created_at": datetime.now().isoformat()
            }, "Database backup created successfully")
        except Exception as e:
            self.error(f"Backup creation failed: {str(e)}", 500)


class BackupListHandler(BaseHandler):
    """List all available database backups"""
    
    @require_auth(roles=["admin"])
    def get(self):
        """Get list of available backups with metadata"""
        try:
            ensure_backup_dir()
            
            backups = []
            if os.path.exists(BACKUP_DIR):
                for filename in sorted(os.listdir(BACKUP_DIR), reverse=True):
                    if filename.endswith(".db"):
                        filepath = os.path.join(BACKUP_DIR, filename)
                        stat = os.stat(filepath)
                        backups.append({
                            "filename": filename,
                            "size": stat.st_size,
                            "created_at": datetime.fromtimestamp(stat.st_mtime).isoformat()
                        })
            
            self.success({
                "backups": backups,
                "count": len(backups)
            })
        except Exception as e:
            self.error(f"Failed to list backups: {str(e)}", 500)


class BackupHandler(BaseHandler):
    """Download a database backup file"""
    
    @require_auth(roles=["admin"])
    def get(self):
        """Download the current database as a file"""
        try:
            # Generate filename with timestamp
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"atms_backup_{timestamp}.db"
            
            # Set response headers for download
            self.set_header("Content-Type", "application/octet-stream")
            self.set_header("Content-Disposition", f'attachment; filename="{filename}"')
            
            # Read and send the database file
            with open(DB_PATH, "rb") as f:
                self.write(f.read())
            
            self.finish()
        except Exception as e:
            self.error(f"Download failed: {str(e)}", 500)
