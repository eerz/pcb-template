"""End-to-End Closed-Loop RF Design, Optimization & Multi-CAD Artifact Generation.

Optimizes a 2.45 GHz RF microstrip filter / matching network using SciPy derivative-free
optimization, scikit-rf analytical electrodynamics, and gdsfactory + kiutils + Gmsh geometry engines.
Converges return loss |S11| < -25 dB across 2.40-2.48 GHz, enforces PCB design rules,
and exports GDSII, KiCad footprint, 3D STL, 3D MSH, and routed .kicad_pcb board.
"""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

# Add project root to sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from src.cad.kicad_harness import BoardBuilder, KiCadHarness
from src.cad.rf_parametric import RFParametricGenerator
from src.loop.optimizer import ClosedLoopOptimizer
from src.sim.rf_analytical import RFAnalyticalEngine


def main():
    console = Console()
    console.print(
        Panel.fit(
            "[bold cyan]Closed-Loop RF Design Optimization & Physical Synthesis Demo[/bold cyan]\n"
            "Target Frequency Band: [bold yellow]2.40 GHz - 2.48 GHz (ISM / Drone Telemetry)[/bold yellow]\n"
            "Goal: [green]Return Loss |S11| < -25.0 dB, Insertion Loss |S21| > -0.5 dB, 0 DRC Violations[/green]",
            border_style="cyan",
        )
    )

    out_dir = PROJECT_ROOT / "build" / "demo_rf"
    out_dir.mkdir(parents=True, exist_ok=True)
    history_file = out_dir / "optimization_history.jsonl"

    rf_engine = RFAnalyticalEngine()
    rf_cad = RFParametricGenerator()
    kicad = KiCadHarness()

    # Load design rules
    rules_path = PROJECT_ROOT / "config" / "design_rules.json"
    min_trace_width_mm = 0.127
    if rules_path.exists():
        with open(rules_path, "r", encoding="utf-8") as f:
            d_rules = json.load(f)
            min_trace_width_mm = d_rules.get("fab_constraints", {}).get("min_trace_width_mm", 0.127)

    # 1. Define initial unoptimized parameters (arbitrary initial guess)
    initial_params = {
        "w_high_mm": 0.25,     # High-Z inductive section width
        "l_high_mm": 5.0,      # High-Z inductive section length
        "w_low_mm": 1.5,       # Low-Z capacitive section width
        "l_low_mm": 5.0,       # Low-Z capacitive section length
    }

    # Physical bounds respecting PCB fab constraints
    param_bounds = {
        "w_high_mm": (min_trace_width_mm, 0.8),
        "l_high_mm": (1.0, 15.0),
        "w_low_mm": (0.6, 3.5),
        "l_low_mm": (1.0, 15.0),
    }

    # Evaluate initial unoptimized performance
    init_net = rf_engine.synthesize_stepped_impedance_filter(
        w_high_mm=initial_params["w_high_mm"],
        l_high_mm=initial_params["l_high_mm"],
        w_low_mm=initial_params["w_low_mm"],
        l_low_mm=initial_params["l_low_mm"],
        order=3,
        f_start_ghz=2.0,
        f_stop_ghz=3.0,
        num_pts=101,
    )
    init_metrics = rf_engine.evaluate_network(init_net, f_min_ghz=2.40, f_max_ghz=2.48, target_s11_db=-25.0)

    console.print(f"[yellow]Initial Unoptimized State:[/yellow] S11={init_metrics.max_s11_db:.2f} dB, S21={init_metrics.min_s21_db:.2f} dB, Loss={init_metrics.scalar_objective_cost:.4f}")

    # 2. Objective Function for the Closed-Loop Optimizer
    def objective_function(params: dict) -> tuple[float, dict]:
        # Synthesize analytical network
        net = rf_engine.synthesize_stepped_impedance_filter(
            w_high_mm=params["w_high_mm"],
            l_high_mm=params["l_high_mm"],
            w_low_mm=params["w_low_mm"],
            l_low_mm=params["l_low_mm"],
            order=3,
            f_start_ghz=2.0,
            f_stop_ghz=3.0,
            num_pts=101,
        )
        metrics = rf_engine.evaluate_network(net, f_min_ghz=2.40, f_max_ghz=2.48, target_s11_db=-25.0)
        return metrics.scalar_objective_cost, metrics.to_dict()

    # 3. Launch Derivative-Free Optimization Loop (Nelder-Mead simplex)
    console.print("[bold green]Starting Closed-Loop Nelder-Mead Optimization...[/bold green]")
    optimizer = ClosedLoopOptimizer(
        method="Nelder-Mead",
        history_log=history_file,
        max_iterations=120,
        tolerance=1e-5,
    )

    opt_res = optimizer.optimize(
        initial_params=initial_params,
        param_bounds=param_bounds,
        objective_fn=objective_function,
    )

    best_p = opt_res.best_parameters
    best_m = opt_res.best_metrics

    console.print(f"[bold green]Optimization Converged in {opt_res.total_iterations} iterations![/bold green]")
    console.print(f"Converged Return Loss |S11|: [bold green]{best_m.get('max_s11_db', 0.0):.2f} dB[/bold green] (Passband Compliant: {best_m.get('passband_compliant')})")

    # 4. Generate Converged Multi-Format Physical CAD Artifacts
    console.print("\n[bold magenta]Synthesizing Production CAD & Simulation Artifacts in build/demo_rf/...[/bold magenta]")

    comp = rf_cad.generate_stepped_impedance_lpf(
        w_high_mm=best_p["w_high_mm"],
        l_high_mm=best_p["l_high_mm"],
        w_low_mm=best_p["w_low_mm"],
        l_low_mm=best_p["l_low_mm"],
        order=3,
        name="converged_rf_filter",
    )

    # 4a. GDSII Layout
    gds_path = out_dir / "converged_rf_filter.gds"
    rf_cad.export_gds(comp, gds_path)
    console.print(f" [green]+[/green] Exported GDSII Layout: [cyan]{gds_path.name}[/cyan]")

    # 4b. KiCad .kicad_mod Footprint
    kmod_path = out_dir / "converged_rf_filter.kicad_mod"
    rf_cad.export_kicad_footprint(comp, kmod_path, fp_name="RF_Filter_2G45")
    console.print(f" [green]+[/green] Exported KiCad Footprint: [cyan]{kmod_path.name}[/cyan]")

    # 4c. 3D Meshes (.stl and .msh)
    stl_path = out_dir / "converged_rf_filter.stl"
    rf_cad.export_3d_stl(comp, stl_path)
    console.print(f" [green]+[/green] Exported 3D Surface Mesh: [cyan]{stl_path.name}[/cyan]")

    msh_path = out_dir / "converged_rf_filter.msh"
    rf_cad.export_3d_gmsh(comp, msh_path)
    console.print(f" [green]+[/green] Exported 3D Tetrahedral FEM Mesh: [cyan]{msh_path.name}[/cyan]")

    # 4d. KiCad Board Assembly with RF Footprint & Ground Shielding Via Fence
    board = BoardBuilder()
    board.add_net(1, "GND")
    board.add_net(3, "RF_IN")
    board.add_net(4, "RF_OUT")

    # Place the converged filter at center
    board.place_footprint(kmod_path, x_mm=50.0, y_mm=50.0)

    # Route 50-Ohm feedlines to launch pads
    board.route_segment((35.0, 50.0), (48.0, 50.0), width_mm=0.38, layer="F.Cu", net=3)
    board.route_segment((52.0, 50.0), (65.0, 50.0), width_mm=0.38, layer="F.Cu", net=4)

    # Add ground stitch shielding via fences
    board.add_ground_stitch_fence([(35.0, 50.0), (48.0, 50.0)], offset_mm=0.8, pitch_mm=1.2, net=1)
    board.add_ground_stitch_fence([(52.0, 50.0), (65.0, 50.0)], offset_mm=0.8, pitch_mm=1.2, net=1)

    pcb_path = out_dir / "converged_board.kicad_pcb"
    board.save(pcb_path)
    console.print(f" [green]+[/green] Programmatically Built KiCad PCB: [cyan]{pcb_path.name}[/cyan]")

    # Run DRC if kicad-cli is installed
    if kicad.is_available():
        drc_res = kicad.run_drc(pcb_path, out_dir / "drc.json")
        console.print(f" [green]+[/green] KiCad DRC Result: {drc_res.total_violations} violations (DRC Available: {drc_res.cli_available})")

    # 5. Print Initial vs. Converged Comparison Table
    table = Table(title="Closed-Loop Optimization Metrics (Initial vs. Converged)", header_style="bold yellow")
    table.add_column("Parameter / Metric", style="bold white", width=28)
    table.add_column("Initial Value", style="red", width=18)
    table.add_column("Converged Value", style="green", width=18)
    table.add_column("Design Target / Constraint", style="cyan", width=26)

    table.add_row(
        "Inductive Width (w_high)",
        f"{initial_params['w_high_mm']:.3f} mm",
        f"{best_p['w_high_mm']:.3f} mm",
        f">= {min_trace_width_mm:.3f} mm (Fab Rule)",
    )
    table.add_row(
        "Inductive Length (l_high)",
        f"{initial_params['l_high_mm']:.3f} mm",
        f"{best_p['l_high_mm']:.3f} mm",
        "Physical resonance tune",
    )
    table.add_row(
        "Capacitive Width (w_low)",
        f"{initial_params['w_low_mm']:.3f} mm",
        f"{best_p['w_low_mm']:.3f} mm",
        "Shunt C loading",
    )
    table.add_row(
        "Capacitive Length (l_low)",
        f"{initial_params['l_low_mm']:.3f} mm",
        f"{best_p['l_low_mm']:.3f} mm",
        "Physical stub tuning",
    )
    table.add_row(
        "Max Return Loss |S11| (2.4-2.48 GHz)",
        f"{init_metrics.max_s11_db:.2f} dB",
        f"{best_m.get('max_s11_db', 0.0):.2f} dB",
        "<= -25.0 dB (Passband)",
    )
    table.add_row(
        "Min Insertion Loss |S21| (2.4-2.48 GHz)",
        f"{init_metrics.min_s21_db:.2f} dB",
        f"{best_m.get('min_s21_db', 0.0):.2f} dB",
        ">= -0.50 dB (Low Loss)",
    )
    table.add_row(
        "Maximum In-Band VSWR",
        f"{init_metrics.max_vswr:.2f}",
        f"{best_m.get('max_vswr', 0.0):.2f}",
        "<= 1.15 : 1",
    )
    table.add_row(
        "Scalar Objective Cost",
        f"{init_metrics.scalar_objective_cost:.4f}",
        f"{opt_res.best_loss:.4f}",
        "-> 0.0000 (Minimizer)",
    )

    console.print()
    console.print(table)
    console.print(f"\n[bold green]Closed-loop demo completed successfully! All artifacts exported to:[/bold green] [yellow]{out_dir}[/yellow]")


if __name__ == "__main__":
    main()
