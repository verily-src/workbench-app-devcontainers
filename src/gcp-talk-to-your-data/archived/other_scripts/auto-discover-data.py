#!/usr/bin/env python3
"""
Auto-discovery script for data files in Workbench mounted workspaces.
This script finds data files and generates a pre-configured notebook.
"""

import os
import json
from pathlib import Path
from typing import Optional, List, Tuple

# Possible mount locations
MOUNT_LOCATIONS = [
    "/home/jovyan/workspace",
    "/home/jovyan/workspaces",
    "/home/jovyan/work",
]

# Supported file extensions
DATA_EXTENSIONS = ['.csv', '.parquet', '.json', '.xlsx', '.xls', '.tsv']

def find_data_files(base_path: str) -> List[Tuple[str, str]]:
    """Find all data files in the given path."""
    data_files = []
    base = Path(base_path)
    
    if not base.exists():
        return data_files
    
    for ext in DATA_EXTENSIONS:
        for file_path in base.rglob(f"*{ext}"):
            # Skip hidden files and very large directories
            if file_path.name.startswith('.'):
                continue
            try:
                # Check if file is readable and not too large (rough check)
                if file_path.stat().st_size < 10 * 1024 * 1024 * 1024:  # 10GB limit
                    data_files.append((str(file_path), ext))
            except (OSError, PermissionError):
                continue
    
    return data_files

def detect_file_format(file_path: str) -> str:
    """Detect file format from extension."""
    ext = Path(file_path).suffix.lower()
    format_map = {
        '.csv': 'csv',
        '.tsv': 'csv',
        '.parquet': 'parquet',
        '.json': 'json',
        '.xlsx': 'excel',
        '.xls': 'excel',
    }
    return format_map.get(ext, 'csv')

def auto_discover_data() -> Optional[dict]:
    """Auto-discover data files in mounted workspaces."""
    all_files = []
    
    for mount_location in MOUNT_LOCATIONS:
        files = find_data_files(mount_location)
        all_files.extend([(f, mount_location) for f, _ in files])
    
    if not all_files:
        return None
    
    # Prefer CSV files, then parquet, then others
    priority = {'.csv': 0, '.tsv': 0, '.parquet': 1, '.json': 2, '.xlsx': 3, '.xls': 3}
    
    def sort_key(item):
        file_path, _ = item
        ext = Path(file_path).suffix.lower()
        return (priority.get(ext, 99), file_path)
    
    all_files.sort(key=sort_key)
    selected_file, mount_base = all_files[0]
    
    # Get relative path from mount base
    rel_path = os.path.relpath(selected_file, mount_base)
    
    return {
        'file_path': selected_file,
        'mount_base': mount_base,
        'relative_path': rel_path,
        'file_format': detect_file_format(selected_file),
        'use_mounted_path': True
    }

def generate_config(config: dict) -> str:
    """Generate Python configuration code."""
    if config['use_mounted_path']:
        return f"""
# Auto-discovered configuration
USE_MOUNTED_PATH = True
MOUNTED_FILE_PATH = "{config['file_path']}"
FILE_FORMAT = "{config['file_format']}"
WORKSPACE_NAME = "{Path(config['mount_base']).name}"
"""
    else:
        return f"""
# Auto-discovered configuration
GCS_BUCKET = "{config.get('bucket', '')}"
FILE_NAME = "{config.get('file_name', '')}"
FILE_FORMAT = "{config['file_format']}"
"""

if __name__ == "__main__":
    config = auto_discover_data()
    
    if config:
        print(json.dumps(config, indent=2))
        print("\n" + "="*60)
        print("Generated Configuration:")
        print("="*60)
        print(generate_config(config))
    else:
        print("No data files found in mounted workspaces.")
        print("Falling back to sample data generation.")

