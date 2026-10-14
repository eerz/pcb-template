# Master Agent Operational Manual: Closed-Loop EDA, PCB & RF Engineering Workspace (100% Native Windows)

> **MANDATORY INSTRUCTION FOR AI AGENTS**: Read this document first before designing schematics, modifying footprints, synthesizing RF structures, placing copper traces, or running simulations in this workspace.

---

## 1. Workspace Identity & Execution Constraints

This workspace is a **100% Native Windows Closed-Loop Physical EDA, PCB & RF Optimization Blueprint**. It runs on a single local Windows machine without any Linux, WSL2, or external cluster dependencies, enabling autonomous design, parametric synthesis, DRC verification, SPICE transient simulation, 3D electromagnetic (EM) field solving, and derivative-free parameter optimization.

### Execution Invariants:

1. **Always use the workspace virtual environment.**
   - Windows Python: `.venv\Scripts\python.exe`
   - Windows Pip: `.venv\Scripts\pip.exe`
2. **Never install system packages with OS package managers (`winget`, `scoop`, `choco`).** All external binaries are pre-installed or discovered via `src.env_discovery.resolve_tool("<tool_name>")` and configured in `config/tool_paths.json`.
3. **Never hardcode external binary paths.** Always call `src.env_discovery.resolve_tool("<tool_name>")` or `require_tool("<tool_name>")`.
4. **All transient and generated files belong in `build/`.** Never commit simulation outputs, raw meshes, or intermediate files to root.

---

## 2. Directory Hierarchy & Architectural Mapping

```text
.
├── AGENTS.md                   # You are here: Master instructions for AI agents
├── README.md                   # Human workspace overview
├── requirements.txt            # Frozen Python dependencies (138 packages)
├── config/
│   ├── tool_paths.json         # Auto-discovery & fallbacks for kicad-cli, ngspice, freerouting, openEMS, etc.
│   ├── stackup_4layer_rf.json  # 4-layer 1.6mm RF stackup (FR4, 50-Ohm controlled Z0)
│   ├── design_rules.json       # Physical fab constraints (trace, clearance, annular ring, return loss)
│   └── gerber2ems_template.json# Template for openEMS FDTD solver
├── docs/
│   ├── 01_CLOSED_LOOP_ARCHITECTURE.md       # 3-Tier closed loop & optimization math
│   ├── 02_PROGRAMMABLE_CAD_GUIDE.md         # kiutils AST manipulation, gdsfactory RF, and Gmsh meshing
│   ├── 03_SPICE_AND_EM_SOLVERS.md           # scikit-rf, PySpice, and openEMS simulation pipelines
│   └── 04_FULL_BOARD_3D_EM_INTEGRATION.md   # Native Windows 3D EM, openEMS FDTD, and PyAEDT
├── src/
│   ├── env_discovery.py        # Native Windows binary locator (PATH, Scoop, ENV, Program Files)
│   ├── cad/
│   │   ├── kicad_harness.py    # kiutils AST manipulation + kicad-cli DRC/Gerber/STEP runner
│   │   ├── rf_parametric.py    # gdsfactory + kiutils + Gmsh geometry engine (GDS, mod, STL, MSH)
│   │   └── autoroute.py        # Specctra .dsn -> Freerouting CLI -> .ses automated routing
│   ├── sim/
│   │   ├── rf_analytical.py    # scikit-rf media, stepped filters, Touchstone .sNp evaluation
│   │   ├── spice_harness.py    # PySpice + Ngspice CLI + analytical state-space ripple/droop
│   │   └── em_openems.py       # gerber2ems / openEMS FDTD runner & S-parameter pipeline
│   └── loop/
│       └── optimizer.py        # ClosedLoopOptimizer (Nelder-Mead, Powell, COBYLA) + JSONL log
├── hardware/
│   ├── elec/                   # Declarative atopile (.ato) schematic files
│   ├── kicad/                  # Target KiCad .kicad_pro, .kicad_sch, .kicad_pcb projects
│   ├── rf_footprints/          # Generated .kicad_mod footprints and simulation meshes
│   └── mechanical/             # Imported 3D enclosures (.scad / .step) for drone/robotics
├── scripts/
│   ├── verify_workspace.py     # Smoke-test script for all Python libraries and host CLI tools
│   └── run_example_rf_loop.py  # Fully verified 2.45 GHz closed-loop filter optimizer demo
└── build/                      # Ephemeral outputs (DRC JSON, Gerbers, Touchstone .s2p, meshes)
    └── .gitkeep
```

---

## 3. The Mandatory 3-Tier Hierarchical Closed-Loop Workflow (Single Machine)

Physical 3D EM simulation is computationally expensive. **Never dispatch a full 3D simulation before converging Tier 1 and Tier 2 on the local machine.**

```
+--------------------------------------------------------------------------------+
| TIER 1: Fast Inner Loop (Pure Python + CPU, ~5ms - 50ms)                       |
|   - Synthesize geometry via src/cad/rf_parametric.py                           |
|   - Evaluate RF S-parameters via src/sim/rf_analytical.py (scikit-rf)          |
|   - Simulate power transients via src/sim/spice_harness.py (Ngspice.exe)       |
|   - Check KiCad board rules via src/cad/kicad_harness.py (kicad-cli.exe DRC)   |
|   ==> Must achieve Analytical |S11| < -25 dB and 0 DRC violations here first!  |
+---------------------------------------+----------------------------------------+
                                        | Converged
                                        v
+--------------------------------------------------------------------------------+
| TIER 2: Medium Sub-Circuit EM Loop (Local Machine, ~5s - 45s)                  |
|   - Isolate critical RF launches, filters, or antennas via Gmsh 3D extrusion  |
|   - Run native Windows openEMS.exe FDTD (src/sim/em_openems.py)                |
|   - Verify S-parameters match analytical Tier 1 predictions within 10%         |
+---------------------------------------+----------------------------------------+
                                        | Verified
                                        v
+--------------------------------------------------------------------------------+
| TIER 3: Heavy Full-Board Loop (Local Machine, ~2m - 10m)                       |
|   - Combine multi-layer PCB layout with 3D mechanical enclosure in hardware/  |
|   - Run full-board openEMS FDTD or PyAEDT (Ansys HFSS/SIwave)                  |
|   - Validate full-wave return loss, coupling, and enclosure clearance          |
+---------------------------------------+----------------------------------------+
```

---

## 4. Copy-Pasteable Agent Implementation Templates

### Pattern A: Closed-Loop RF Geometry Optimization

```python
import sys
from pathlib import Path

# Always ensure project root is on sys.path
PROJECT_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.cad.kicad_harness import BoardBuilder
from src.cad.rf_parametric import RFParametricGenerator
from src.loop.optimizer import ClosedLoopOptimizer
from src.sim.rf_analytical import RFAnalyticalEngine

rf_engine = RFAnalyticalEngine()
rf_cad = RFParametricGenerator()

# 1. Define initial parameters & bounds
initial_params = {"w_high_mm": 0.35, "l_high_mm": 5.0, "w_low_mm": 1.2, "l_low_mm": 3.0}
bounds = {
    "w_high_mm": (0.127, 0.8),  # 0.127mm min trace width from design_rules.json
    "l_high_mm": (1.0, 15.0),
    "w_low_mm": (0.5, 4.0),
    "l_low_mm": (1.0, 15.0),
}

# 2. Objective function
def cost_function(params: dict) -> tuple[float, dict]:
    net = rf_engine.synthesize_stepped_impedance_filter(
        w_high_mm=params["w_high_mm"],
        l_high_mm=params["l_high_mm"],
        w_low_mm=params["w_low_mm"],
        l_low_mm=params["l_low_mm"],
        order=3,
    )
    # Evaluate over 2.40-2.48 GHz
    metrics = rf_engine.evaluate_network(net, f_min_ghz=2.40, f_max_ghz=2.48, target_s11_db=-25.0)
    return metrics.scalar_objective_cost, metrics.to_dict()

# 3. Run optimizer
opt = ClosedLoopOptimizer(method="Nelder-Mead", max_iterations=100)
result = opt.optimize(initial_params=initial_params, param_bounds=bounds, objective_fn=cost_function)

# 4. Generate converged CAD footprint & KiCad PCB
best_p = result.best_parameters
comp = rf_cad.generate_stepped_impedance_lpf(
    w_high_mm=best_p["w_high_mm"],
    l_high_mm=best_p["l_high_mm"],
    w_low_mm=best_p["w_low_mm"],
    l_low_mm=best_p["l_low_mm"],
    order=3,
)
kmod = rf_cad.export_kicad_footprint(comp, "build/converged_filter.kicad_mod")

board = BoardBuilder()
board.place_footprint(kmod, x_mm=50.0, y_mm=50.0)
board.route_segment((35.0, 50.0), (48.0, 50.0), width_mm=0.38, net=3)
board.add_ground_stitch_fence([(35.0, 50.0), (48.0, 50.0)], offset_mm=0.8, pitch_mm=1.2, net=1)
board.save("build/converged_board.kicad_pcb")
```

### Pattern B: SPICE Buck Converter Transient Verification

```python
from src.sim.spice_harness import SpiceHarness

spice = SpiceHarness()
# Simulates synchronous buck output LC stage (12V -> 3.3V @ 500kHz)
metrics = spice.simulate_buck_filter_transient(
    v_in=12.0,
    v_out_target=3.3,
    f_sw_khz=500.0,
    l_inductance_uh=2.2,
    c_capacitance_uf=22.0,
    esr_mohm=5.0,
    r_load_ohm=3.3,
)
print(f"Mean Output: {metrics.v_mean:.3f} V")
print(f"Peak-to-Peak Ripple: {metrics.v_pp_ripple_mv:.2f} mV (Target: < 25 mV)")
print(f"Overshoot: {metrics.v_overshoot_mv:.2f} mV")
```

### Pattern C: Inspecting Optimization History

After any optimization run, inspect `build/optimization_history.jsonl`:

```powershell
Get-Content build/optimization_history.jsonl | Select-Object -Last 5
```

Each JSON line contains:

```json
{
  "iteration": 105,
  "parameters": {
    "w_high_mm": 0.359,
    "l_high_mm": 6.861,
    "w_low_mm": 0.6,
    "l_low_mm": 1.031
  },
  "scalar_loss": -31.5994,
  "metrics": {
    "max_s11_db": -40.8,
    "min_s21_db": -0.22,
    "max_vswr": 1.02,
    "passband_compliant": true
  },
  "drc_violations": 0,
  "is_valid": true,
  "timestamp": "2026-10-14T11:28:15.123456"
}
```

---

## 5. Verification Command

Before handing over designs to the user or closing any task, run:

```powershell
.\.venv\Scripts\python.exe scripts\verify_workspace.py
```

This guarantees all 24 dependencies and 7 native Windows tool bindings remain intact and operational.
