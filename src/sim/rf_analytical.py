"""Analytical RF transmission line, filter, and S-parameter network evaluation engine.

Uses scikit-rf (skrf) to synthesize microstrip and CPW transmission lines, calculate
instantaneous characteristic impedances, cascade stepped-impedance filter topologies,
and parse Touchstone (.s1p, .s2p, .sNp) simulation results into scalar optimization metrics.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import skrf as rf
from skrf.media import MLine


@dataclass
class RFMetrics:
    """Standardized RF network performance metrics over a target frequency band."""
    max_s11_db: float
    min_s21_db: float
    mean_s11_db: float
    mean_s21_db: float
    max_vswr: float
    mean_z0_ohm: float
    scalar_objective_cost: float
    frequency_points: int
    passband_compliant: bool

    def to_dict(self) -> Dict[str, Any]:
        return {
            "max_s11_db": round(float(self.max_s11_db), 3),
            "min_s21_db": round(float(self.min_s21_db), 3),
            "mean_s11_db": round(float(self.mean_s11_db), 3),
            "mean_s21_db": round(float(self.mean_s21_db), 3),
            "max_vswr": round(float(self.max_vswr), 3),
            "mean_z0_ohm": round(float(self.mean_z0_ohm), 3),
            "scalar_objective_cost": round(float(self.scalar_objective_cost), 4),
            "frequency_points": int(self.frequency_points),
            "passband_compliant": bool(self.passband_compliant),
        }


class RFAnalyticalEngine:
    """Analytical synthesis and Touchstone processing using scikit-rf."""

    DEFAULT_STACKUP = Path(__file__).resolve().parent.parent.parent / "config" / "stackup_4layer_rf.json"

    def __init__(self, stackup_path: Optional[str | Path] = None):
        self.stackup_path = Path(stackup_path or self.DEFAULT_STACKUP)
        self.stackup = self._load_stackup()

    def _load_stackup(self) -> Dict[str, Any]:
        if self.stackup_path.exists():
            try:
                with open(self.stackup_path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                pass
        # Fallback to standard 4-layer FR4
        return {
            "rf_reference": {
                "substrate_height_mm": 0.20,
                "substrate_er": 4.4,
                "substrate_tand": 0.02,
                "copper_thickness_mm": 0.035,
            }
        }

    def get_rf_parameters(self) -> Tuple[float, float, float, float]:
        """Returns (h_m, er, tand, t_m) for the RF top layer."""
        rf_ref = self.stackup.get("rf_reference", {})
        h_m = float(rf_ref.get("substrate_height_mm", 0.20)) * 1e-3
        er = float(rf_ref.get("substrate_er", 4.4))
        tand = float(rf_ref.get("substrate_tand", 0.02))
        t_m = float(rf_ref.get("copper_thickness_mm", 0.035)) * 1e-3
        return h_m, er, tand, t_m

    def create_microstrip_media(
        self,
        w_mm: float,
        f_start_ghz: float = 1.0,
        f_stop_ghz: float = 5.0,
        num_pts: int = 101,
    ) -> MLine:
        """Constructs an analytical MLine media instance for a given trace width."""
        freq = rf.Frequency(f_start_ghz, f_stop_ghz, num_pts, "ghz")
        h_m, er, tand, t_m = self.get_rf_parameters()
        w_m = float(w_mm) * 1e-3

        media = MLine(
            frequency=freq,
            w=w_m,
            h=h_m,
            t=t_m,
            ep_r=er,
            tand=tand,
            disp="hammerstad",
        )
        return media

    def synthesize_microstrip_line(
        self,
        w_mm: float,
        length_mm: float,
        f_start_ghz: float = 1.0,
        f_stop_ghz: float = 5.0,
        num_pts: int = 101,
    ) -> rf.Network:
        """Synthesizes a 2-port microstrip transmission line section."""
        media = self.create_microstrip_media(w_mm, f_start_ghz, f_stop_ghz, num_pts)
        length_m = float(length_mm) * 1e-3
        net = media.line(length_m, "m")
        return net

    def synthesize_stepped_impedance_filter(
        self,
        w_high_mm: float,
        l_high_mm: float,
        w_low_mm: float,
        l_low_mm: float,
        order: int = 3,
        f_start_ghz: float = 1.0,
        f_stop_ghz: float = 5.0,
        num_pts: int = 101,
        port_z0_w_mm: float = 0.38,
        launch_len_mm: float = 2.0,
    ) -> rf.Network:
        """Synthesizes a stepped-impedance microstrip low-pass filter by cascading sections."""
        freq = rf.Frequency(f_start_ghz, f_stop_ghz, num_pts, "ghz")
        h_m, er, tand, t_m = self.get_rf_parameters()

        # 50-Ohm Launch lines
        m_port = MLine(freq, w=port_z0_w_mm * 1e-3, h=h_m, t=t_m, ep_r=er, tand=tand)
        m_high = MLine(freq, w=w_high_mm * 1e-3, h=h_m, t=t_m, ep_r=er, tand=tand)
        m_low = MLine(freq, w=w_low_mm * 1e-3, h=h_m, t=t_m, ep_r=er, tand=tand)

        launch = m_port.line(launch_len_mm * 1e-3, "m")
        high_sec = m_high.line(l_high_mm * 1e-3, "m")
        low_sec = m_low.line(l_low_mm * 1e-3, "m")

        # Cascade: Launch -> High-Z -> Low-Z -> High-Z ... -> Launch
        network = launch
        for i in range(order):
            if i % 2 == 0:
                network = network ** high_sec
            else:
                network = network ** low_sec

        network = network ** launch
        return network

    def load_touchstone(self, file_path: str | Path) -> rf.Network:
        """Loads a Touchstone file (.s1p, .s2p, .sNp) into an skrf Network."""
        path = Path(file_path).resolve()
        if not path.exists():
            raise FileNotFoundError(f"Touchstone file not found: {path}")
        return rf.Network(str(path))

    def export_touchstone(self, network: rf.Network, file_path: str | Path) -> Path:
        """Saves an skrf Network to a Touchstone (.s2p) file."""
        target = Path(file_path).resolve()
        target.parent.mkdir(parents=True, exist_ok=True)
        network.write_touchstone(str(target))
        return target

    def evaluate_network(
        self,
        network: rf.Network,
        f_min_ghz: float,
        f_max_ghz: float,
        target_s11_db: float = -20.0,
        target_s21_db: float = -1.0,
    ) -> RFMetrics:
        """Extracts band-limited performance metrics and computes scalar optimization cost.

        Cost function penalizes:
        1. S11 > target_s11_db in-band (quadratic penalty)
        2. S21 insertion loss degradation
        3. High VSWR (> 1.25)
        """
        # Interpolate or slice to target passband
        in_band_mask = (network.f >= (f_min_ghz * 1e9)) & (network.f <= (f_max_ghz * 1e9))
        if not np.any(in_band_mask):
            # Fallback to entire frequency range if out of bounds
            in_band_mask = np.ones(len(network.f), dtype=bool)

        s11_db = network.s11.s_db[in_band_mask].flatten()
        max_s11 = float(np.max(s11_db))
        mean_s11 = float(np.mean(s11_db))

        # Check 2-port transmission if available
        if network.nports >= 2:
            s21_db = network.s21.s_db[in_band_mask].flatten()
            min_s21 = float(np.min(s21_db))
            mean_s21 = float(np.mean(s21_db))
        else:
            min_s21 = 0.0
            mean_s21 = 0.0

        vswr_vals = network.s11.s_vswr[in_band_mask].flatten()
        max_vswr = float(np.max(vswr_vals))

        # Characteristic impedance reference
        z0_val = float(np.real(network.z0[0, 0]))

        # Scalar loss formulation for optimizers:
        # We want S11 as negative as possible (e.g. <= target_s11_db)
        # S11 penalty:
        s11_excess = np.maximum(0.0, s11_db - target_s11_db)
        loss_s11 = float(np.mean(s11_excess ** 2) * 10.0 + (max_s11 - target_s11_db) * 2.0)

        # S21 penalty (insertion loss should not drop below target):
        loss_s21 = float(np.maximum(0.0, target_s21_db - min_s21) * 5.0) if network.nports >= 2 else 0.0

        # VSWR penalty
        loss_vswr = float(np.maximum(0.0, max_vswr - 1.25) * 4.0)

        total_cost = float(loss_s11 + loss_s21 + loss_vswr)

        passband_ok = bool(max_s11 <= target_s11_db and min_s21 >= target_s21_db)

        return RFMetrics(
            max_s11_db=max_s11,
            min_s21_db=min_s21,
            mean_s11_db=mean_s11,
            mean_s21_db=mean_s21,
            max_vswr=max_vswr,
            mean_z0_ohm=z0_val,
            scalar_objective_cost=total_cost,
            frequency_points=int(np.sum(in_band_mask)),
            passband_compliant=passband_ok,
        )
