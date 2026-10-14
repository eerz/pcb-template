"""Workspace Smoke-Test and Environment Verification Script.

Tests all installed Python EDA, RF, and meshing libraries, runs cross-platform external
tool discovery, and prints a rich diagnostics table.
"""

from __future__ import annotations

import sys
from pathlib import Path

# Add project root to sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from src.env_discovery import get_all_tool_statuses


def verify_python_packages(console: Console) -> bool:
    """Verifies that all required Python EDA and RF packages can be imported and initialized."""
    packages = [
        ("numpy", "Core Numerical Computing", "numpy"),
        ("scipy", "Scientific & Optimization Engine", "scipy"),
        ("matplotlib", "Plotting & Visuals", "matplotlib"),
        ("pydantic", "Data Validation & Models", "pydantic"),
        ("rich", "Terminal Output & Logging", "rich"),
        ("typer", "CLI Framework", "typer"),
        ("jinja2", "Template Rendering", "jinja2"),
        ("yaml", "YAML Parser", "pyyaml"),
        ("kiutils", "KiCad S-Expression AST Manipulation", "kiutils"),
        ("gdsfactory", "Parametric 2D Photonic & RF Layouts", "gdsfactory"),
        ("gdstk", "C++ GDSII / OASIS Engine", "gdstk"),
        ("shapely", "2D Computational Geometry", "shapely"),
        ("trimesh", "3D Surface Meshing & Solid Operations", "trimesh"),
        ("gmsh", "3D Finite Element Tetrahedral Meshing", "gmsh"),
        ("mapbox_earcut", "Fast Polygon Triangulation", "mapbox_earcut"),
        ("networkx", "Graph & Network Topologies", "networkx"),
        ("skrf", "RF Network Analysis & Touchstone Processing", "scikit-rf"),
        ("PySpice", "SPICE Simulation Interface", "PySpice"),
        ("atopile", "Declarative Circuit Design Compiler", "atopile"),
        ("pygerber", "Gerber Parsing & Rasterization", "pygerber"),
        ("gerber2ems", "Gerber to openEMS FDTD Bridge", "gerber2ems"),
        ("h5py", "HDF5 Binary Matrix Storage", "h5py"),
        ("cython", "C-Extension Compiler", "cython"),
        ("ansys.aedt.core", "Commercial EM / PyAEDT Interface", "pyaedt"),
    ]

    table = Table(title="Python Workspace Dependencies (.venv)", header_style="bold cyan")
    table.add_column("Library", style="bold white", width=18)
    table.add_column("Package Name", style="magenta", width=16)
    table.add_column("Purpose", style="dim", width=42)
    table.add_column("Status", justify="center", width=12)
    table.add_column("Version", style="green", width=14)

    all_passed = True
    for module_name, purpose, pkg_name in packages:
        try:
            mod = __import__(module_name, fromlist=["__version__"])
            ver = getattr(mod, "__version__", "Installed")
            table.add_row(module_name, pkg_name, purpose, "[green]PASSED[/green]", str(ver))
        except Exception as e:
            all_passed = False
            table.add_row(module_name, pkg_name, purpose, "[red]FAILED[/red]", str(e)[:14])

    console.print(table)
    return all_passed


def verify_external_tools(console: Console) -> None:
    """Discovers host external binaries and displays status without failing the script."""
    statuses = get_all_tool_statuses()

    table = Table(title="External Host System Binaries & Simulators", header_style="bold magenta")
    table.add_column("Tool", style="bold white", width=16)
    table.add_column("Command", style="cyan", width=14)
    table.add_column("Status", justify="center", width=14)
    table.add_column("Source", style="yellow", width=14)
    table.add_column("Resolved Path / Guidance", style="dim", width=60)

    for key, status in statuses.items():
        if status.found:
            stat_text = "[green]FOUND[/green]"
            src_text = status.detection_source or "SYSTEM"
            path_or_guide = status.resolved_path or ""
        else:
            stat_text = "[yellow]OPTIONAL[/yellow]"
            src_text = "MISSING"
            path_or_guide = f"Not detected. {status.install_guide}"

        table.add_row(key, status.command, stat_text, src_text, path_or_guide)

    console.print(table)


def main():
    console = Console()
    console.print(
        Panel.fit(
            "[bold green]Closed-Loop EDA, PCB & RF Engineering Workspace Smoke-Test[/bold green]\n"
            f"Python Interpreter: [cyan]{sys.executable}[/cyan]\n"
            f"Workspace Root: [yellow]{PROJECT_ROOT}[/yellow]",
            border_style="green",
        )
    )

    py_ok = verify_python_packages(console)
    console.print()
    verify_external_tools(console)
    console.print()

    if py_ok:
        console.print("[bold green]All Python EDA, RF, and meshing libraries verified 100% operational![/bold green]")
        sys.exit(0)
    else:
        console.print("[bold red]One or more Python libraries failed to import.[/bold red]")
        sys.exit(1)


if __name__ == "__main__":
    main()
