# 03 — SPICE & Electromagnetic Solvers Guide

This document details the analytical transmission-line modeling, SPICE power transient simulation, and full-wave 3D EM pipelines implemented in `src/sim/`.

---

## 1. Fast Analytical RF Modeling (`scikit-rf`)

`src/sim/rf_analytical.py` uses `skrf` to synthesize microstrip lines and cascade multi-stage matching networks in milliseconds.

### Synthesizing Analytical Networks
```python
from src.sim.rf_analytical import RFAnalyticalEngine

engine = RFAnalyticalEngine("config/stackup_4layer_rf.json")

# 1. Synthesize a 50-Ohm microstrip line
line_net = engine.synthesize_microstrip_line(
    w_mm=0.38,
    length_mm=10.0,
    f_start_ghz=1.0,
    f_stop_ghz=5.0
)

# 2. Synthesize a stepped-impedance filter
filter_net = engine.synthesize_stepped_impedance_filter(
    w_high_mm=0.359,
    l_high_mm=6.861,
    w_low_mm=0.600,
    l_low_mm=1.031,
    order=3
)

# 3. Evaluate S-parameters over target passband
metrics = engine.evaluate_network(
    filter_net,
    f_min_ghz=2.40,
    f_max_ghz=2.48,
    target_s11_db=-25.0
)
print(f"Max Return Loss: {metrics.max_s11_db:.2f} dB")
print(f"Min Insertion Loss: {metrics.min_s21_db:.2f} dB")
print(f"Max VSWR: {metrics.max_vswr:.2f}")

# 4. Export to Touchstone .s2p
engine.export_touchstone(filter_net, "build/filter.s2p")
```

---

## 2. Power SPICE Simulation (`PySpice` & `ngspice`)

`src/sim/spice_harness.py` provides transient and AC analysis of power converters, LC filters, and decoupling networks.

### Synchronous Buck Output Stage Transient Analysis
```python
from src.sim.spice_harness import SpiceHarness

spice = SpiceHarness()

# Simulates buck regulator switching transient
trans = spice.simulate_buck_filter_transient(
    v_in=12.0,
    v_out_target=3.3,
    f_sw_khz=500.0,
    l_inductance_uh=2.2,
    c_capacitance_uf=22.0,
    esr_mohm=5.0,
    r_load_ohm=3.3,
    sim_time_us=200.0
)

print(f"Steady-State Mean Voltage: {trans.v_mean:.3f} V")
print(f"Peak-to-Peak Switching Ripple: {trans.v_pp_ripple_mv:.2f} mV")
print(f"Startup Overshoot: {trans.v_overshoot_mv:.2f} mV")
print(f"Load Step Droop: {trans.v_droop_mv:.2f} mV")
```

### LC Filter AC Frequency Response
```python
ac = spice.simulate_lc_filter_ac(
    l_inductance_uh=1.0,
    c_capacitance_uf=10.0,
    r_load_ohm=50.0,
    f_start_hz=1e3,
    f_stop_hz=1e8
)
print(f"-3dB Cutoff Frequency: {ac.f_cutoff_3db_hz / 1e3:.1f} kHz")
```

---

## 3. 3D FDTD Electromagnetic Simulation (`openEMS` / `gerber2ems`)

`src/sim/em_openems.py` transforms PCB Gerbers into Yee-cell grids and executes FDTD full-wave simulations:

```python
from src.sim.em_openems import OpenEMSRunner

ems = OpenEMSRunner()

# Renders simulation.json, generates mesh, and runs openEMS
result = ems.run_simulation(
    gerber_dir="build/fab/",
    f_min_ghz=2.0,
    f_max_ghz=3.0,
    dry_run_fallback=True  # Provides high-fidelity surrogate if openEMS binary is not on host
)

if result.success:
    print(f"Touchstone file: {result.touchstone_path}")
    print(f"Simulated S11: {result.metrics.max_s11_db:.2f} dB")
```

---

## 4. Local 3D EM & Ansys Integration (`openEMS` & `pyaedt`)

Full 3D full-wave electromagnetic solving and parasitic extraction run on native Windows:

### Native openEMS FDTD
`openEMS.exe` simulates planar and multilayer PCB structures using Yee-cell finite-difference time-domain analysis.

### Local Ansys Electronics Desktop (`ansys.aedt.core`)
When Ansys HFSS or SIwave is present on the workstation, `ansys.aedt.core` provides programmatic Python bindings:
```python
import ansys.aedt.core as pyaedt

# Launches or connects to local desktop Ansys HFSS session
hfss = pyaedt.Hfss(specified_version="2024.1", non_graphical=True)
print(f"HFSS connected: {hfss.desktop_version}")
```

