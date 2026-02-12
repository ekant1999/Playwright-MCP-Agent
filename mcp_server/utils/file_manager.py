"""File management utilities for downloads."""

import os
from pathlib import Path
from typing import Optional
import hashlib
from datetime import datetime


class FileManager:
    """Manage downloaded files and screenshots."""
    
    def __init__(self, base_dir: Optional[str] = None):
        """Initialize file manager with base directory."""
        if base_dir is None:
            # Default to downloads/ in the mcp_server directory
            base_dir = Path(__file__).parent.parent / "downloads"
        
        self.base_dir = Path(base_dir)
        self.base_dir.mkdir(parents=True, exist_ok=True)
    
    def get_unique_filename(self, filename: str) -> str:
        """Generate a unique filename if file already exists."""
        filepath = self.base_dir / filename
        
        if not filepath.exists():
            return filename
        
        # Add timestamp to make it unique
        name_parts = filename.rsplit('.', 1)
        if len(name_parts) == 2:
            name, ext = name_parts
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            new_filename = f"{name}_{timestamp}.{ext}"
        else:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            new_filename = f"{filename}_{timestamp}"
        
        return new_filename
    
    def save_file(self, content: bytes, filename: str) -> dict:
        """Save binary content to file."""
        unique_filename = self.get_unique_filename(filename)
        filepath = self.base_dir / unique_filename
        
        filepath.write_bytes(content)
        
        file_size = filepath.stat().st_size
        
        return {
            "filename": unique_filename,
            "path": str(filepath.absolute()),
            "size": file_size,
            "size_mb": round(file_size / (1024 * 1024), 2)
        }
    
    def save_text(self, content: str, filename: str) -> dict:
        """Save text content to file."""
        unique_filename = self.get_unique_filename(filename)
        filepath = self.base_dir / unique_filename
        
        filepath.write_text(content, encoding='utf-8')
        
        file_size = filepath.stat().st_size
        
        return {
            "filename": unique_filename,
            "path": str(filepath.absolute()),
            "size": file_size,
            "size_kb": round(file_size / 1024, 2)
        }
    
    def list_files(self) -> list:
        """List all files in the downloads directory."""
        files = []
        
        for filepath in self.base_dir.iterdir():
            if filepath.is_file():
                stat = filepath.stat()
                files.append({
                    "filename": filepath.name,
                    "path": str(filepath.absolute()),
                    "size": stat.st_size,
                    "modified": datetime.fromtimestamp(stat.st_mtime).isoformat()
                })
        
        return sorted(files, key=lambda x: x['modified'], reverse=True)
    
    def get_path(self, filename: str) -> Path:
        """Get full path for a filename."""
        return self.base_dir / filename


# Global file manager instance
file_manager = FileManager()
