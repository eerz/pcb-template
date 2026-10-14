"""Native Windows binary locator and external tool discovery engine.

Auto-discovers external EDA & simulation binaries (kicad-cli, ngspice, freerouting,
openEMS, gerber2ems, atopile, gmsh) by checking system PATH, environment variables,
Scoop shims/apps, standard Windows directories, and the workspace virtual environment.
"""

from __future__ import annotations

import json
import os
import platform
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional


@dataclass
class ToolStatus:
    name: str
    command: str
    found: bool = False
    resolved_path: Optional[str] = None
    version_output: Optional[str] = None
    detection_source: Optional[str] = None
    description: str = ""
    install_guide: str = ""


class EnvironmentDiscovery:
    """Discovers native Windows host EDA tools and provides validated execution paths."""

    DEFAULT_CONFIG_PATH = Path(__file__).resolve().parent.parent / "config" / "tool_paths.json"

    def __init__(self, config_file: Optional[Path] = None):
        self.config_path = config_file or self.DEFAULT_CONFIG_PATH
        self.config_data = self._load_config()

    def _load_config(self) -> Dict[str, Any]:
        if self.config_path.exists():
            try:
                with open(self.config_path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                pass
        return {}

    def _expand_path(self, raw_path: str) -> Path:
        """Expands ~ and environment variables into a normalized Path."""
        expanded = os.path.expandvars(os.path.expanduser(raw_path))
        return Path(expanded)

    def _get_scoop_search_paths(self, tool_name: str, binary_name: str) -> List[Path]:
        """Generates standard Scoop application and shim paths for Windows."""
        home = Path.home()
        username = os.getenv("USERNAME", "six")
        candidates = [
            home / "scoop" / "shims" / binary_name,
            home / "scoop" / "apps" / tool_name / "current" / binary_name,
            home / "scoop" / "apps" / tool_name / "current" / "bin" / binary_name,
            Path("C:/Users") / username / "scoop" / "shims" / binary_name,
            Path("C:/Users") / username / "scoop" / "apps" / tool_name / "current" / "bin" / binary_name,
        ]
        return candidates

    def discover_tool(self, tool_key: str) -> ToolStatus:
        """Discovers a single tool status by checking PATH, ENV, Scoop, and standard directories."""
        binary_meta = self.config_data.get("system_binaries", {}).get(tool_key, {})
        command = binary_meta.get("command", tool_key)
        description = binary_meta.get("description", f"External executable {tool_key}")
        env_var = binary_meta.get("env_var")

        status = ToolStatus(
            name=tool_key,
            command=command,
            description=description,
        )

        # 1. Environment Variable Override
        if env_var and os.getenv(env_var):
            env_path = self._expand_path(os.environ[env_var])
            if env_path.exists():
                status.found = True
                status.resolved_path = str(env_path)
                status.detection_source = f"ENV:{env_var}"
                status.version_output = self._query_version(status.resolved_path)
                return status

        # 2. System PATH
        which_path = shutil.which(command)
        if which_path:
            status.found = True
            status.resolved_path = which_path
            status.detection_source = "PATH"
            status.version_output = self._query_version(which_path)
            return status

        # 3. Windows Candidate Search
        win_fallbacks = binary_meta.get("windows_fallback_paths", [])
        for raw_p in win_fallbacks:
            cand = self._expand_path(raw_p)
            if cand.exists():
                status.found = True
                status.resolved_path = str(cand)
                status.detection_source = "SYSTEM_DIR"
                status.version_output = self._query_version(str(cand))
                return status

        # 4. Scoop Heuristic Search
        scoop_cands = self._get_scoop_search_paths(tool_key, f"{command}.exe")
        scoop_cands.extend(self._get_scoop_search_paths(tool_key, command))
        for cand in scoop_cands:
            if cand.exists():
                status.found = True
                status.resolved_path = str(cand)
                status.detection_source = "SCOOP"
                status.version_output = self._query_version(str(cand))
                return status

        # 5. Java JAR special case (e.g. freerouting)
        jar_name = binary_meta.get("jar_name")
        if jar_name:
            for raw_p in win_fallbacks:
                cand = self._expand_path(raw_p)
                if cand.is_file() and cand.suffix.lower() == ".jar":
                    status.found = True
                    status.resolved_path = str(cand)
                    status.detection_source = "JAR_FILE"
                    status.version_output = f"Java JAR: {cand.name}"
                    return status

        # 6. Gmsh bundled Python library / .venv fallback
        if tool_key == "gmsh":
            try:
                import gmsh  # type: ignore
                status.found = True
                status.resolved_path = getattr(gmsh, "__file__", ".venv\\Lib\\site-packages\\gmsh.py")
                status.detection_source = ".VENV"
                ver = getattr(gmsh, "__version__", "4.15.2")
                status.version_output = f"Gmsh {ver} (.venv)"
                return status
            except Exception:
                pass

        # Not found - provide helpful setup instructions
        status.install_guide = self._get_install_guide(tool_key)
        return status

    def _query_version(self, executable_path: str) -> Optional[str]:
        """Runs a safe --version or -v call to extract tool release string."""
        if executable_path.endswith(".jar"):
            return "Java Archive Binary"
        if executable_path.endswith(".py"):
            return "Python Module Library"

        flags = ["--version", "-version", "-v", "--help"]
        for flag in flags:
            try:
                proc = subprocess.run(
                    [executable_path, flag],
                    capture_output=True,
                    text=True,
                    timeout=3,
                )
                output = proc.stdout.strip() or proc.stderr.strip()
                if output:
                    return output.splitlines()[0][:120].strip()
            except Exception:
                continue
        return "Executable verified (version query skipped)"

    def _get_install_guide(self, tool_key: str) -> str:
        guides = {
            "kicad_cli": "Install KiCad 8+ from https://kicad.org or `scoop install kicad`. Ensure kicad-cli is on PATH.",
            "ngspice": "Install ngspice via `scoop install ngspice` or download from https://ngspice.sourceforge.io.",
            "freerouting": "Install freerouting via `scoop install freerouting` or place freerouting.jar in config/.",
            "openems": "Install openEMS from https://openems.de or place in C:\\openEMS\\openEMS.exe.",
            "gerber2ems": "Install via `.venv\\Scripts\\pip.exe install --no-deps git+https://github.com/antmicro/gerber2ems.git`.",
            "atopile": "Install atopile via `.venv\\Scripts\\pip.exe install atopile` inside `.venv`.",
            "gmsh": "Installed in `.venv` via `pip install gmsh`.",
        }
        return guides.get(tool_key, f"Install {tool_key} and set {tool_key.upper()}_PATH environment variable.")

    def discover_all(self) -> Dict[str, ToolStatus]:
        """Runs discovery for all configured native Windows tools."""
        tools = self.config_data.get("system_binaries", {}).keys()
        if not tools:
            tools = [
                "kicad_cli",
                "ngspice",
                "freerouting",
                "openems",
                "gerber2ems",
                "atopile",
                "gmsh",
            ]
        results = {}
        for tool in tools:
            results[tool] = self.discover_tool(tool)
        return results


# Global singleton instance for easy import across modules
_discovery = EnvironmentDiscovery()


def resolve_tool(tool_name: str) -> Optional[str]:
    """Returns the resolved executable path/command or None if not installed."""
    status = _discovery.discover_tool(tool_name)
    if status.found:
        return status.resolved_path
    return None


def require_tool(tool_name: str) -> str:
    """Returns the resolved executable path or raises a structured FileNotFoundError."""
    status = _discovery.discover_tool(tool_name)
    if status.found and status.resolved_path:
        return status.resolved_path
    raise FileNotFoundError(
        f"Required external tool '{tool_name}' (command: '{status.command}') was not found.\n"
        f"Resolution Source: Checked PATH, ENV, Scoop shims, and standard Windows directories.\n"
        f"Guidance: {status.install_guide}\n"
        f"Override: Set the path in 'config/tool_paths.json' or set the appropriate environment variable."
    )


def get_all_tool_statuses() -> Dict[str, ToolStatus]:
    """Discovers all native Windows tools and returns their statuses."""
    return _discovery.discover_all()
