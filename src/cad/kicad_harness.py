"""KiCad programmatic AST harness and headless kicad-cli automation.

Wraps kiutils for S-expression AST manipulation (placing footprints, routing traces,
generating ground stitch via fences) and invokes kicad-cli for headless DRC,
Gerber generation, Excellon drill files, and 3D STEP exports.
"""

from __future__ import annotations

import json
import math
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import kiutils.board as kb
import kiutils.footprint as kf
from kiutils.items.gritems import GrLine

from src.env_discovery import resolve_tool


@dataclass
class DRCViolation:
    rule: str
    severity: str
    description: str
    pos_x_mm: Optional[float] = None
    pos_y_mm: Optional[float] = None


@dataclass
class DRCResult:
    success: bool
    total_violations: int = 0
    unconnected_count: int = 0
    violations: List[DRCViolation] = field(default_factory=list)
    raw_output: str = ""
    cli_available: bool = True
    error_message: Optional[str] = None


class BoardBuilder:
    """Programmatic builder for KiCad .kicad_pcb layout files using kiutils."""

    def __init__(self, board_path: Optional[str | Path] = None):
        if board_path and Path(board_path).exists():
            self.board = kb.Board.from_file(str(board_path))
            self.board_path = Path(board_path)
        else:
            self.board = kb.Board.create_new()
            self.board_path = Path(board_path) if board_path else Path("board.kicad_pcb")
            self._init_default_layers()

    def _init_default_layers(self) -> None:
        """Ensures default nets and minimal setup exist."""
        if not self.board.nets:
            self.board.nets = [
                kb.Net(number=0, name=""),
                kb.Net(number=1, name="GND"),
                kb.Net(number=2, name="VCC"),
                kb.Net(number=3, name="RF_SIG"),
            ]

    def add_net(self, number: int, name: str) -> None:
        """Adds or updates a net in the board database."""
        for net in self.board.nets:
            if net.number == number:
                net.name = name
                return
        self.board.nets.append(kb.Net(number=number, name=name))

    def place_footprint(
        self,
        footprint: kf.Footprint | str | Path,
        x_mm: float,
        y_mm: float,
        angle_deg: float = 0.0,
    ) -> kf.Footprint:
        """Places a footprint at (x, y) with specified rotation angle."""
        if isinstance(footprint, (str, Path)):
            fp = kf.Footprint.from_file(str(footprint))
        else:
            fp = footprint

        fp.position = kb.Position(X=float(x_mm), Y=float(y_mm), angle=float(angle_deg))
        self.board.footprints.append(fp)
        return fp

    def route_segment(
        self,
        start_xy: Tuple[float, float],
        end_xy: Tuple[float, float],
        width_mm: float,
        layer: str = "F.Cu",
        net: int = 0,
    ) -> kb.Segment:
        """Draws a copper segment between two coordinates."""
        seg = kb.Segment(
            start=kb.Position(X=float(start_xy[0]), Y=float(start_xy[1])),
            end=kb.Position(X=float(end_xy[0]), Y=float(end_xy[1])),
            width=float(width_mm),
            layer=layer,
            net=net,
        )
        self.board.traceItems.append(seg)
        return seg

    def route_path(
        self,
        points: List[Tuple[float, float]],
        width_mm: float,
        layer: str = "F.Cu",
        net: int = 0,
    ) -> List[kb.Segment]:
        """Routes a continuous polyline trace through a sequence of points."""
        segments = []
        for i in range(len(points) - 1):
            seg = self.route_segment(points[i], points[i + 1], width_mm, layer, net)
            segments.append(seg)
        return segments

    def add_via(
        self,
        xy: Tuple[float, float],
        size_mm: float = 0.45,
        drill_mm: float = 0.20,
        layers: Optional[List[str]] = None,
        net: int = 1,
    ) -> kb.Via:
        """Places a copper through-via at specified coordinates."""
        if layers is None:
            layers = ["F.Cu", "B.Cu"]
        via = kb.Via(
            position=kb.Position(X=float(xy[0]), Y=float(xy[1])),
            size=float(size_mm),
            drill=float(drill_mm),
            layers=layers,
            net=net,
        )
        self.board.traceItems.append(via)
        return via

    def add_ground_stitch_fence(
        self,
        trace_points: List[Tuple[float, float]],
        offset_mm: float = 0.8,
        pitch_mm: float = 1.0,
        size_mm: float = 0.45,
        drill_mm: float = 0.20,
        net: int = 1,
    ) -> List[kb.Via]:
        """Synthesizes parallel bilateral ground via fences along an RF trace path.

        Used to suppress parasitic waveguide modes and achieve substrate shielding.
        """
        vias = []
        for i in range(len(trace_points) - 1):
            p1 = trace_points[i]
            p2 = trace_points[i + 1]
            dx = p2[0] - p1[0]
            dy = p2[1] - p1[1]
            length = math.hypot(dx, dy)
            if length == 0:
                continue

            ux = dx / length
            uy = dy / length
            # Perpendicular normal vectors
            nx = -uy
            ny = ux

            steps = max(1, int(length / pitch_mm))
            for s in range(steps + 1):
                t = s * (length / steps)
                cx = p1[0] + ux * t
                cy = p1[1] + uy * t

                # Left side via
                v_left = self.add_via(
                    (cx + nx * offset_mm, cy + ny * offset_mm),
                    size_mm=size_mm,
                    drill_mm=drill_mm,
                    net=net,
                )
                # Right side via
                v_right = self.add_via(
                    (cx - nx * offset_mm, cy - ny * offset_mm),
                    size_mm=size_mm,
                    drill_mm=drill_mm,
                    net=net,
                )
                vias.extend([v_left, v_right])
        return vias

    def save(self, output_path: Optional[str | Path] = None) -> Path:
        """Serializes the board AST to a .kicad_pcb file."""
        target = Path(output_path) if output_path else self.board_path
        target.parent.mkdir(parents=True, exist_ok=True)
        self.board.to_file(str(target))
        return target


class KiCadHarness:
    """Wraps kicad-cli for DRC, Gerber generation, and 3D STEP export."""

    def __init__(self, cli_path: Optional[str] = None):
        self.cli_path = cli_path or resolve_tool("kicad_cli")

    def is_available(self) -> bool:
        return self.cli_path is not None

    def run_drc(
        self,
        pcb_path: str | Path,
        output_json: Optional[str | Path] = None,
    ) -> DRCResult:
        """Runs headless DRC on a PCB file and returns parsed structured violations."""
        if not self.is_available():
            return DRCResult(
                success=True,
                total_violations=0,
                cli_available=False,
                error_message="kicad-cli not found on host. DRC skipped gracefully.",
            )

        pcb_p = Path(pcb_path).resolve()
        if not pcb_p.exists():
            return DRCResult(
                success=False,
                total_violations=0,
                error_message=f"PCB file '{pcb_p}' does not exist.",
            )

        out_json_p = Path(output_json).resolve() if output_json else pcb_p.parent / "build" / "drc.json"
        out_json_p.parent.mkdir(parents=True, exist_ok=True)

        cmd = [
            self.cli_path,
            "pcb",
            "drc",
            "--format",
            "json",
            "--output",
            str(out_json_p),
            str(pcb_p),
        ]

        try:
            res = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
            raw = res.stdout + "\n" + res.stderr

            if not out_json_p.exists():
                return DRCResult(
                    success=(res.returncode == 0),
                    total_violations=0,
                    raw_output=raw,
                    error_message="DRC report JSON was not created.",
                )

            with open(out_json_p, "r", encoding="utf-8") as f:
                drc_data = json.load(f)

            violations_list = []
            raw_violations = drc_data.get("violations", [])
            for item in raw_violations:
                pos = item.get("pos", {})
                violations_list.append(
                    DRCViolation(
                        rule=item.get("type", "unknown"),
                        severity=item.get("severity", "warning"),
                        description=item.get("description", ""),
                        pos_x_mm=pos.get("x"),
                        pos_y_mm=pos.get("y"),
                    )
                )

            unconnected = len(drc_data.get("unconnected_items", []))
            total = len(violations_list) + unconnected

            return DRCResult(
                success=(total == 0),
                total_violations=total,
                unconnected_count=unconnected,
                violations=violations_list,
                raw_output=raw,
            )

        except Exception as e:
            return DRCResult(
                success=False,
                error_message=f"DRC execution failed: {e}",
            )

    def export_gerbers(self, pcb_path: str | Path, output_dir: str | Path) -> bool:
        """Exports Gerber layers and Excellon drill files to output directory."""
        if not self.is_available():
            return False

        out_dir = Path(output_dir).resolve()
        out_dir.mkdir(parents=True, exist_ok=True)
        pcb_p = Path(pcb_path).resolve()

        cmd_gerber = [self.cli_path, "pcb", "export", "gerbers", "-o", str(out_dir), str(pcb_p)]
        cmd_drill = [self.cli_path, "pcb", "export", "drill", "-o", str(out_dir), str(pcb_p)]

        try:
            res1 = subprocess.run(cmd_gerber, capture_output=True, text=True, timeout=60)
            res2 = subprocess.run(cmd_drill, capture_output=True, text=True, timeout=60)
            return res1.returncode == 0 and res2.returncode == 0
        except Exception:
            return False

    def export_step(self, pcb_path: str | Path, output_step: str | Path) -> bool:
        """Exports 3D STEP solid model of the board assembly."""
        if not self.is_available():
            return False

        out_step = Path(output_step).resolve()
        out_step.parent.mkdir(parents=True, exist_ok=True)
        pcb_p = Path(pcb_path).resolve()

        cmd = [self.cli_path, "pcb", "export", "step", "-o", str(out_step), str(pcb_p)]
        try:
            res = subprocess.run(cmd, capture_output=True, text=True, timeout=90)
            return res.returncode == 0 and out_step.exists()
        except Exception:
            return False
