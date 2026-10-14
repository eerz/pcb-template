# 02 — Programmable CAD Guide: kiutils, gdsfactory & Gmsh

This document explains the programmatic layout interfaces, footprint generation, and 3D meshing tools in `src/cad/`.

---

## 1. KiCad S-Expression Manipulation (`kiutils`)

`src/cad/kicad_harness.py` provides high-level abstractions over `kiutils.board` and `kiutils.footprint`.

### Creating and Routing Boards Programmatically
```python
from src.cad.kicad_harness import BoardBuilder

# Create or load an existing board
board = BoardBuilder("hardware/kicad/flight_controller.kicad_pcb")

# Add nets
board.add_net(1, "GND")
board.add_net(2, "3V3")
board.add_net(3, "RF_2G4")

# Place footprints
board.place_footprint("hardware/rf_footprints/RF_Filter.kicad_mod", x_mm=25.0, y_mm=30.0, angle_deg=90.0)

# Route copper traces
board.route_segment(
    start_xy=(20.0, 30.0),
    end_xy=(25.0, 30.0),
    width_mm=0.38,  # 50-Ohm controlled width for 0.20mm FR4
    layer="F.Cu",
    net=3
)

# Synthesize ground stitch shielding fences
# Adds parallel ground vias on both sides of the RF trace
board.add_ground_stitch_fence(
    trace_points=[(20.0, 30.0), (25.0, 30.0)],
    offset_mm=0.8,
    pitch_mm=1.0,
    size_mm=0.45,
    drill_mm=0.20,
    net=1
)

# Save board AST
board.save()
```

### Running Headless DRC and Exports
```python
from src.cad.kicad_harness import KiCadHarness

kicad = KiCadHarness()
if kicad.is_available():
    # Run DRC
    drc = kicad.run_drc("hardware/kicad/flight_controller.kicad_pcb", "build/drc.json")
    print(f"Total Violations: {drc.total_violations}")
    for v in drc.violations:
        print(f"  [{v.severity}] {v.rule} at ({v.pos_x_mm}, {v.pos_y_mm}): {v.description}")

    # Export Gerbers & Drills
    kicad.export_gerbers("hardware/kicad/flight_controller.kicad_pcb", "build/fab/")

    # Export 3D STEP
    kicad.export_step("hardware/kicad/flight_controller.kicad_pcb", "build/3d/flight_controller.step")
```

---

## 2. Parametric RF Layouts ("OpenSCAD for RF")

`src/cad/rf_parametric.py` uses `gdsfactory` 9.x to generate parameterized copper geometries and convert them directly into KiCad `.kicad_mod` footprints.

### Generating Geometries
```python
from src.cad.rf_parametric import RFParametricGenerator

cad = RFParametricGenerator()

# 1. Microstrip
line = cad.generate_microstrip(width_mm=0.38, length_mm=12.0)

# 2. Coplanar Waveguide (CPW)
cpw = cad.generate_cpw(width_mm=0.35, gap_mm=0.20, length_mm=10.0)

# 3. Stepped-Impedance Low-Pass Filter
filter_comp = cad.generate_stepped_impedance_lpf(
    w_high_mm=0.359,
    l_high_mm=6.861,
    w_low_mm=0.600,
    l_low_mm=1.031,
    order=3
)

# 4. Inverted-F Antenna (IFA) for 2.4 GHz
antenna = cad.generate_ifa_antenna_24ghz(arm_length_mm=25.0, feed_offset_mm=3.5)
```

### Multi-Format Export Pipeline
From any `gdsfactory.Component`, export to 4 standardized formats:
```python
# 1. 2D IC / Photonic mask
cad.export_gds(filter_comp, "build/filter.gds")

# 2. Ready-to-place KiCad footprint with SMD launch pads
cad.export_kicad_footprint(filter_comp, "hardware/rf_footprints/Filter.kicad_mod")

# 3. 3D surface mesh (STL) for mechanical CAD inspection
cad.export_3d_stl(filter_comp, "build/filter.stl")

# 4. 3D volume tetrahedral mesh (MSH) for openEMS and 3D solvers
cad.export_3d_gmsh(filter_comp, "build/filter.msh")
```

---

## 3. Automated Specctra Autorouting

`src/cad/autoroute.py` handles unassisted trace routing via headless Freerouting:
```python
from src.cad.autoroute import SpecctraRouter

router = SpecctraRouter()
if router.is_available():
    # Executes: KiCad PCB -> Specctra DSN -> Freerouting CLI -> SES
    router.autoroute_pipeline(
        pcb_path="hardware/kicad/flight_controller.kicad_pcb",
        max_passes=25
    )
```
