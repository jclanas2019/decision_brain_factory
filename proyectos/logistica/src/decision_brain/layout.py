"""Locate user-owned configuration and outputs independently of installed code."""
import os
from pathlib import Path

def project_root():
    return Path(os.environ.get('BRAIN_PROJECT_ROOT', Path.cwd())).resolve()
