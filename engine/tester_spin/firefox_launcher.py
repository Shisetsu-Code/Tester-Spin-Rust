from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path
from urllib.parse import urlsplit


def open_firefox(url: str) -> None:
    parsed = urlsplit(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("El juego no tiene un enlace web válido")
    executable = shutil.which("firefox")
    if not executable:
        for folder in (os.environ.get("ProgramFiles", "C:/Program Files"), os.environ.get("ProgramFiles(x86)", "C:/Program Files (x86)")):
            candidate = Path(folder) / "Mozilla Firefox" / "firefox.exe"
            if candidate.is_file():
                executable = str(candidate)
                break
    if not executable:
        raise FileNotFoundError("Firefox no está instalado o no se encontró su ejecutable")
    subprocess.Popen([executable, "-new-tab", url])
