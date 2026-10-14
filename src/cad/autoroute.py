"""Headless Specctra DSN to Freerouting CLI and SES merger.

Automates the bridge between KiCad .kicad_pcb layout files and the Java-based
Freerouting router for unassisted copper trace routing.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path
from typing import Optional

from src.env_discovery import resolve_tool


class SpecctraRouter:
    """Wraps headless Freerouting jar execution and Specctra DSN/SES file handling."""

    def __init__(self, freerouting_jar: Optional[str] = None, java_binary: Optional[str] = None):
        self.freerouting_jar = freerouting_jar or resolve_tool("freerouting")
        self.java_binary = java_binary or shutil.which("java")
        self.kicad_cli = resolve_tool("kicad_cli")

    def is_available(self) -> bool:
        """Returns True if Java and Freerouting are both executable."""
        if not self.freerouting_jar:
            return False
        # If it's a jar, we must have java
        if str(self.freerouting_jar).endswith(".jar"):
            return self.java_binary is not None
        # If it's a native binary or scoop shim
        return Path(self.freerouting_jar).exists() or shutil.which(self.freerouting_jar) is not None

    def export_dsn(self, pcb_path: str | Path, dsn_output: str | Path) -> bool:
        """Exports a KiCad PCB to Specctra DSN format using kicad-cli."""
        if not self.kicad_cli:
            return False
        dsn_p = Path(dsn_output).resolve()
        dsn_p.parent.mkdir(parents=True, exist_ok=True)
        pcb_p = Path(pcb_path).resolve()

        cmd = [self.kicad_cli, "pcb", "export", "specctra_dsn", "-o", str(dsn_p), str(pcb_p)]
        try:
            res = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
            return res.returncode == 0 and dsn_p.exists()
        except Exception:
            return False

    def run_autoroute(
        self,
        dsn_path: str | Path,
        ses_output: str | Path,
        max_passes: int = 30,
        threads: int = 4,
        timeout_sec: int = 300,
    ) -> bool:
        """Executes Freerouting in headless mode on the DSN file."""
        if not self.is_available():
            return False

        dsn_p = Path(dsn_path).resolve()
        ses_p = Path(ses_output).resolve()
        ses_p.parent.mkdir(parents=True, exist_ok=True)

        jar_or_bin = str(self.freerouting_jar)
        if jar_or_bin.endswith(".jar"):
            cmd = [
                self.java_binary or "java",
                "-jar",
                jar_or_bin,
                "-de",
                str(dsn_p),
                "-do",
                str(ses_p),
                "-mp",
                str(max_passes),
                "-us",
                "gui=false",
            ]
        else:
            cmd = [
                jar_or_bin,
                "-de",
                str(dsn_p),
                "-do",
                str(ses_p),
                "-mp",
                str(max_passes),
            ]

        try:
            res = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout_sec)
            return res.returncode == 0 and ses_p.exists()
        except Exception:
            return False

    def autoroute_pipeline(
        self,
        pcb_path: str | Path,
        output_pcb_path: Optional[str | Path] = None,
        max_passes: int = 30,
    ) -> bool:
        """Full end-to-end pipeline: PCB -> DSN -> Freerouting -> SES -> Routed PCB."""
        pcb_p = Path(pcb_path).resolve()
        work_dir = pcb_p.parent / "build" / "autoroute"
        work_dir.mkdir(parents=True, exist_ok=True)

        dsn_file = work_dir / f"{pcb_p.stem}.dsn"
        ses_file = work_dir / f"{pcb_p.stem}.ses"

        # 1. Export DSN
        if not self.export_dsn(pcb_p, dsn_file):
            return False

        # 2. Run Freerouting
        if not self.run_autoroute(dsn_file, ses_file, max_passes=max_passes):
            return False

        # 3. Session routing file is ready for import in KiCad
        return ses_file.exists()
