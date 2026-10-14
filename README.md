# Production-Ready Closed-Loop EDA, PCB & RF Engineering Workspace (Native Windows)

A reusable template and automated CAD/EM simulation blueprint for autonomous hardware engineering agents and RF designers running natively on a single Windows workstation.

## Overview

This repository provides an end-to-end programmable physical design and simulation loop:
- **Declarative & Programmatic CAD**: KiCad 8+ S-expression AST manipulation (`kiutils`), headless DRC/Gerber/STEP (`kicad-cli.exe`), and declarative schematics (`atopile`).
- **Parametric RF & 3D Meshing**: "OpenSCAD for RF" using `gdsfactory`, `shapely`, `trimesh`, and `gmsh` to synthesize microstrip, CPW, stepped-impedance filters, and antennas into GDSII, KiCad `.kicad_mod` footprints, surface `.stl`, and volume `.msh` meshes.
- **Multi-Solver Simulation Stack (100% Native Windows)**:
  - Analytical RF S-parameters & matching networks (`scikit-rf`)
  - Analog & power transient SPICE (`PySpice` + native `ngspice.exe` with analytical state-space fallbacks)
  - 3D FDTD full-wave solver (native Windows `openEMS.exe` + `gerber2ems`)
  - Local EM / Parasitic extraction interface (`pyaedt` / `ansys.aedt.core`)
- **Derivative-Free Optimization**: Closed-loop tuning via `scipy.optimize` with iteration-by-iteration JSONL observability.

---

## Directory Structure

```text
├── AGENTS.md                  # Master agent operational manual & workflow constraints
├── README.md                  # Human overview & quickstart
├── requirements.txt           # Locked Python environment dependencies
├── config/
│   ├── tool_paths.json        # External tool locator and path overrides
│   ├── stackup_4layer_rf.json # 4-layer impedance-controlled FR4 stackup
│   ├── design_rules.json      # Fabrication constraints and RF targets
│   └── gerber2ems_template.json # FDTD simulation template for openEMS
├── docs/
│   ├── 01_CLOSED_LOOP_ARCHITECTURE.md        # 3-Tier closed loop & optimization math
│   ├── 02_PROGRAMMABLE_CAD_GUIDE.md          # kiutils AST, gdsfactory RF, and Gmsh meshing
│   ├── 03_SPICE_AND_EM_SOLVERS.md            # scikit-rf, PySpice, and openEMS pipelines
│   └── 04_FULL_BOARD_3D_EM_INTEGRATION.md    # Native Windows 3D EM, openEMS, and PyAEDT
├── src/
│   ├── env_discovery.py       # Native Windows binary locator
│   ├── cad/                   # KiCad AST, parametric RF, and autorouter
│   ├── sim/                   # scikit-rf, PySpice, openEMS runners
│   └── loop/                  # ClosedLoopOptimizer & JSONL logger
├── hardware/                  # Schematics, layouts, footprints, mechanical 3D models
├── scripts/
│   ├── verify_workspace.py    # Smoke-test script for libraries and binaries
│   └── run_example_rf_loop.py # End-to-end 2.45 GHz filter optimization demo
└── build/                     # Ephemeral outputs and simulation logs
    └── .gitkeep
```

---

## Quickstart

### 1. Verify the Environment
```powershell
.\.venv\Scripts\python.exe scripts\verify_workspace.py
```

### 2. Run the 2.45 GHz Closed-Loop RF Demo
```powershell
.\.venv\Scripts\python.exe scripts\run_example_rf_loop.py
```
This script optimizes an initial stepped-impedance microstrip filter from $|S_{11}| = -7.96\text{ dB}$ to $|S_{11}| = -40.80\text{ dB}$, validates 0 KiCad DRC violations, and exports:
- `build/demo_rf/converged_rf_filter.gds`
- `build/demo_rf/converged_rf_filter.kicad_mod`
- `build/demo_rf/converged_rf_filter.stl`
- `build/demo_rf/converged_rf_filter.msh`
- `build/demo_rf/converged_board.kicad_pcb`
- `build/demo_rf/optimization_history.jsonl`

---

## 3-Tier Hierarchical Simulation Architecture (Single Machine)

1. **Tier 1 (Inner Loop, ms)**: `rf_analytical.py` (`scikit-rf`) + `spice_harness.py` (`Ngspice`/`scipy`) + `kicad-cli.exe` DRC.
2. **Tier 2 (Sub-Circuit EM, s)**: `rf_parametric.py` (`gdsfactory` + `gmsh`) + `em_openems.py` (`openEMS.exe` FDTD).
3. **Tier 3 (Full-Board EM, min)**: Combined PCB + 3D enclosure simulation via native Windows `openEMS` or `pyaedt` (`ansys.aedt.core`).
