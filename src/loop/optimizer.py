"""Closed-loop derivative-free physical optimization engine.

Wraps scipy.optimize.minimize (Nelder-Mead, Powell, COBYLA) for tuning physical EDA geometries,
filter stubs, and power component values with automated iteration-by-iteration logging to JSONL.
"""

from __future__ import annotations

import datetime
import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

import numpy as np
import scipy.optimize as opt


@dataclass
class OptimizationIteration:
    iteration: int
    parameters: Dict[str, float]
    scalar_loss: float
    metrics: Dict[str, Any]
    drc_violations: int = 0
    is_valid: bool = True
    timestamp: str = field(default_factory=lambda: datetime.datetime.now().isoformat())


@dataclass
class OptimizationResult:
    success: bool
    best_parameters: Dict[str, float]
    best_loss: float
    best_metrics: Dict[str, Any]
    total_iterations: int
    history_file: Path
    message: str


class ClosedLoopOptimizer:
    """Manages closed-loop physical design optimization loops and convergence logging."""

    DEFAULT_LOG = Path(__file__).resolve().parent.parent.parent / "build" / "optimization_history.jsonl"

    def __init__(
        self,
        method: str = "Nelder-Mead",
        history_log: Optional[str | Path] = None,
        max_iterations: int = 100,
        tolerance: float = 1e-4,
    ):
        self.method = method
        self.history_file = Path(history_log or self.DEFAULT_LOG).resolve()
        self.max_iterations = max_iterations
        self.tolerance = tolerance
        self.iteration_count = 0
        self.history: List[OptimizationIteration] = []
        self.best_loss = float("inf")
        self.best_iteration: Optional[OptimizationIteration] = None

    def _init_history_file(self) -> None:
        self.history_file.parent.mkdir(parents=True, exist_ok=True)
        if self.history_file.exists():
            try:
                self.history_file.unlink()
            except Exception:
                pass

    def _log_iteration(self, iter_record: OptimizationIteration) -> None:
        self.history.append(iter_record)
        with open(self.history_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(asdict(iter_record)) + "\n")

    def optimize(
        self,
        initial_params: Dict[str, float],
        param_bounds: Optional[Dict[str, Tuple[float, float]]] = None,
        objective_fn: Optional[Callable[[Dict[str, float]], Tuple[float, Dict[str, Any]]]] = None,
    ) -> OptimizationResult:
        """Runs the optimization loop.

        Args:
            initial_params: Dictionary of parameter names and initial numeric values.
            param_bounds: Optional dictionary mapping parameter names to (min_val, max_val).
            objective_fn: Callable returning (scalar_loss, metrics_dict).
        """
        if objective_fn is None:
            raise ValueError("objective_fn must be provided.")

        self._init_history_file()
        self.iteration_count = 0
        self.history.clear()
        self.best_loss = float("inf")
        self.best_iteration = None

        param_names = list(initial_params.keys())
        x0 = np.array([initial_params[k] for k in param_names], dtype=float)

        bounds_list = None
        if param_bounds:
            bounds_list = [param_bounds.get(k, (None, None)) for k in param_names]

        def cost_wrapper(x: np.ndarray) -> float:
            self.iteration_count += 1
            curr_params = {name: float(val) for name, val in zip(param_names, x)}

            # Enforce bounds via penalty if method does not support strict bounds
            penalty = 0.0
            if param_bounds:
                for name, val in curr_params.items():
                    b_min, b_max = param_bounds[name]
                    if b_min is not None and val < b_min:
                        penalty += (b_min - val) * 1000.0
                    if b_max is not None and val > b_max:
                        penalty += (val - b_max) * 1000.0

            try:
                raw_loss, metrics = objective_fn(curr_params)
            except Exception as e:
                raw_loss = 1e6
                metrics = {"error": str(e)}

            total_loss = float(raw_loss + penalty)
            drc_viol = int(metrics.get("drc_violations", 0))

            rec = OptimizationIteration(
                iteration=self.iteration_count,
                parameters=curr_params,
                scalar_loss=total_loss,
                metrics=metrics,
                drc_violations=drc_viol,
                is_valid=(penalty == 0.0 and drc_viol == 0),
            )
            self._log_iteration(rec)

            if total_loss < self.best_loss:
                self.best_loss = total_loss
                self.best_iteration = rec

            return total_loss

        # Select supported optimizer
        options = {"maxiter": self.max_iterations, "disp": False}
        res = opt.minimize(
            cost_wrapper,
            x0,
            method=self.method,
            bounds=bounds_list if self.method in ["Powell", "L-BFGS-B", "COBYLA"] else None,
            options=options,
            tol=self.tolerance,
        )

        best_p = self.best_iteration.parameters if self.best_iteration else initial_params
        best_m = self.best_iteration.metrics if self.best_iteration else {}

        return OptimizationResult(
            success=bool(res.success or (self.best_loss < 100.0)),
            best_parameters=best_p,
            best_loss=self.best_loss,
            best_metrics=best_m,
            total_iterations=self.iteration_count,
            history_file=self.history_file,
            message=str(res.message),
        )
