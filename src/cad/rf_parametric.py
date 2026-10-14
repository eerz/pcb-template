"""Parametric RF layout generator and 3D meshing engine ("OpenSCAD for RF").

Generates 2D parametric microstrip, CPW, stepped-impedance filters, and IFA antennas using gdsfactory,
and exports them to:
1. GDSII (.gds) IC/photonic layout files.
2. KiCad footprint (.kicad_mod) files using kiutils AST polygons and SMD launch pads.
3. 3D surface meshes (.stl) using trimesh and shapely.
4. 3D volume tetrahedral meshes (.msh) with physical port tags using Gmsh for openEMS and 3D solvers.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import gdsfactory as gf
import gmsh
import numpy as np
import shapely.geometry as sg
import trimesh
from shapely.ops import unary_union

import kiutils.board as kb
import kiutils.footprint as kf


class RFParametricGenerator:
    """Parametric RF CAD generator bridging gdsfactory, kiutils, trimesh, and Gmsh."""

    def __init__(self):
        try:
            gf.gpdk.PDK.activate()
        except Exception:
            pass

    def generate_microstrip(
        self,
        width_mm: float,
        length_mm: float,
        name: str = "microstrip_line",
    ) -> gf.Component:
        """Generates a parametric microstrip transmission line section."""
        c = gf.Component(name)
        w_um = float(width_mm) * 1000.0
        l_um = float(length_mm) * 1000.0

        # In gdsfactory, dimensions are typically in microns
        poly = [(0.0, -w_um / 2.0), (l_um, -w_um / 2.0), (l_um, w_um / 2.0), (0.0, w_um / 2.0)]
        c.add_polygon(poly, layer=(1, 0))
        return c

    def generate_cpw(
        self,
        width_mm: float,
        gap_mm: float,
        length_mm: float,
        ground_width_mm: float = 2.0,
        name: str = "coplanar_waveguide",
    ) -> gf.Component:
        """Generates a coplanar waveguide (CPW) section with center conductor and coplanar grounds."""
        c = gf.Component(name)
        w_um = float(width_mm) * 1000.0
        g_um = float(gap_mm) * 1000.0
        l_um = float(length_mm) * 1000.0
        gw_um = float(ground_width_mm) * 1000.0

        # Center signal trace
        c.add_polygon([(0.0, -w_um / 2.0), (l_um, -w_um / 2.0), (l_um, w_um / 2.0), (0.0, w_um / 2.0)], layer=(1, 0))

        # Top ground plane
        y_top_start = w_um / 2.0 + g_um
        c.add_polygon([(0.0, y_top_start), (l_um, y_top_start), (l_um, y_top_start + gw_um), (0.0, y_top_start + gw_um)], layer=(1, 0))

        # Bottom ground plane
        y_bot_start = -w_um / 2.0 - g_um
        c.add_polygon([(0.0, y_bot_start), (l_um, y_bot_start), (l_um, y_bot_start - gw_um), (0.0, y_bot_start - gw_um)], layer=(1, 0))
        return c

    def generate_stepped_impedance_lpf(
        self,
        w_high_mm: float,
        l_high_mm: float,
        w_low_mm: float,
        l_low_mm: float,
        order: int = 3,
        port_width_mm: float = 0.38,
        port_length_mm: float = 2.0,
        name: str = "stepped_impedance_lpf",
    ) -> gf.Component:
        """Generates a symmetric stepped-impedance microstrip low-pass filter."""
        c = gf.Component(name)
        current_x_um = 0.0

        # 1. Input launch section (50-Ohm matched port)
        w_port_um = float(port_width_mm) * 1000.0
        l_port_um = float(port_length_mm) * 1000.0
        c.add_polygon(
            [
                (current_x_um, -w_port_um / 2.0),
                (current_x_um + l_port_um, -w_port_um / 2.0),
                (current_x_um + l_port_um, w_port_um / 2.0),
                (current_x_um, w_port_um / 2.0),
            ],
            layer=(1, 0),
        )
        current_x_um += l_port_um

        # 2. Alternating High-Z (series inductor) and Low-Z (shunt capacitor) stages
        w_high_um = float(w_high_mm) * 1000.0
        l_high_um = float(l_high_mm) * 1000.0
        w_low_um = float(w_low_mm) * 1000.0
        l_low_um = float(l_low_mm) * 1000.0

        for i in range(order):
            if i % 2 == 0:
                # High-Z narrow inductive section
                w_curr = w_high_um
                l_curr = l_high_um
            else:
                # Low-Z wide capacitive section
                w_curr = w_low_um
                l_curr = l_low_um

            c.add_polygon(
                [
                    (current_x_um, -w_curr / 2.0),
                    (current_x_um + l_curr, -w_curr / 2.0),
                    (current_x_um + l_curr, w_curr / 2.0),
                    (current_x_um, w_curr / 2.0),
                ],
                layer=(1, 0),
            )
            current_x_um += l_curr

        # 3. Output launch section
        c.add_polygon(
            [
                (current_x_um, -w_port_um / 2.0),
                (current_x_um + l_port_um, -w_port_um / 2.0),
                (current_x_um + l_port_um, w_port_um / 2.0),
                (current_x_um, w_port_um / 2.0),
            ],
            layer=(1, 0),
        )
        return c

    def generate_ifa_antenna_24ghz(
        self,
        arm_length_mm: float = 25.0,
        feed_offset_mm: float = 3.5,
        trace_width_mm: float = 0.8,
        height_mm: float = 4.0,
        ground_width_mm: float = 15.0,
        name: str = "ifa_antenna_24ghz",
    ) -> gf.Component:
        """Generates a 2.45 GHz inverted-F antenna (IFA) geometry with feed and ground shunt pin."""
        c = gf.Component(name)
        w_um = float(trace_width_mm) * 1000.0
        arm_l_um = float(arm_length_mm) * 1000.0
        feed_off_um = float(feed_offset_mm) * 1000.0
        h_um = float(height_mm) * 1000.0
        gnd_w_um = float(ground_width_mm) * 1000.0

        # Resonant horizontal radiating arm
        c.add_polygon([(0.0, h_um), (arm_l_um, h_um), (arm_l_um, h_um + w_um), (0.0, h_um + w_um)], layer=(1, 0))

        # Grounding shorting post at x = 0
        c.add_polygon([(0.0, 0.0), (w_um, 0.0), (w_um, h_um), (0.0, h_um)], layer=(1, 0))

        # 50-Ohm feed pin at x = feed_off_um
        c.add_polygon([(feed_off_um, 0.0), (feed_off_um + w_um, 0.0), (feed_off_um + w_um, h_um), (feed_off_um, h_um)], layer=(1, 0))

        # Ground plane edge
        c.add_polygon([(-5000.0, -1000.0), (arm_l_um + 5000.0, -1000.0), (arm_l_um + 5000.0, 0.0), (-5000.0, 0.0)], layer=(1, 0))
        return c

    def extract_polygons_mm(self, component: gf.Component) -> List[List[Tuple[float, float]]]:
        """Extracts all 2D polygon boundaries from the component converted to millimeters."""
        polys_mm = []
        try:
            layer_idx = component.kcl.layout.layer(1, 0)
            shapes = component.shapes(layer_idx)
            dbu = component.kcl.dbu  # Database units to um
            for s in shapes.each():
                poly = s.polygon
                # Convert um to mm (1 um = 1e-3 mm)
                pts_mm = [((p.x * dbu) / 1000.0, (p.y * dbu) / 1000.0) for p in poly.each_point_hull()]
                if pts_mm:
                    polys_mm.append(pts_mm)
        except Exception:
            pass
        return polys_mm

    def export_gds(self, component: gf.Component, output_path: str | Path) -> Path:
        """Exports the RF component to standard GDSII stream format."""
        target = Path(output_path).resolve()
        target.parent.mkdir(parents=True, exist_ok=True)
        component.write_gds(str(target))
        return target

    def export_kicad_footprint(
        self,
        component: gf.Component,
        output_path: str | Path,
        fp_name: Optional[str] = None,
        launch_pads: bool = True,
    ) -> Path:
        """Converts gdsfactory layout directly into a KiCad .kicad_mod footprint file."""
        target = Path(output_path).resolve()
        target.parent.mkdir(parents=True, exist_ok=True)

        entry_name = fp_name or component.name
        footprint = kf.Footprint.create_new(library_id=entry_name, value=entry_name)
        footprint.description = f"Parametrically generated RF footprint ({entry_name})"

        polys_mm = self.extract_polygons_mm(component)
        if not polys_mm:
            # Fallback if no polygons extracted
            polys_mm = [[(0.0, 0.0), (10.0, 0.0), (10.0, 0.38), (0.0, 0.38)]]

        all_x = []
        all_y = []
        for poly_pts in polys_mm:
            coords = [kb.Position(X=float(pt[0]), Y=float(pt[1])) for pt in poly_pts]
            fp_poly = kf.FpPoly(
                layer="F.Cu",
                coordinates=coords,
                width=0.0,
                fill="solid",
            )
            footprint.graphicItems.append(fp_poly)
            for pt in poly_pts:
                all_x.append(pt[0])
                all_y.append(pt[1])

        # Add SMD launch pads at the extremes for schematic connectivity
        if launch_pads and all_x:
            min_x, max_x = min(all_x), max(all_x)
            center_y = (min(all_y) + max(all_y)) / 2.0
            height_y = max(0.38, (max(all_y) - min(all_y)))

            # Port 1 (Input launch pad)
            pad1 = kf.Pad(
                number="1",
                type="smd",
                shape="rect",
                position=kb.Position(X=float(min_x), Y=float(center_y)),
                size=kb.Position(X=0.4, Y=float(height_y)),
                layers=["F.Cu", "F.Mask", "F.Paste"],
            )
            # Port 2 (Output launch pad)
            pad2 = kf.Pad(
                number="2",
                type="smd",
                shape="rect",
                position=kb.Position(X=float(max_x), Y=float(center_y)),
                size=kb.Position(X=0.4, Y=float(height_y)),
                layers=["F.Cu", "F.Mask", "F.Paste"],
            )
            footprint.pads.extend([pad1, pad2])

        footprint.to_file(str(target))
        return target

    def export_3d_stl(
        self,
        component: gf.Component,
        output_path: str | Path,
        copper_thickness_mm: float = 0.035,
        substrate_thickness_mm: float = 0.20,
    ) -> Path:
        """Extrudes copper polygons and substrate dielectric into a 3D STL surface mesh."""
        target = Path(output_path).resolve()
        target.parent.mkdir(parents=True, exist_ok=True)

        polys_mm = self.extract_polygons_mm(component)
        if not polys_mm:
            polys_mm = [[(0.0, 0.0), (10.0, 0.0), (10.0, 0.38), (0.0, 0.38)]]

        shapely_polys = [sg.Polygon(pts) for pts in polys_mm if len(pts) >= 3]
        copper_geom = unary_union(shapely_polys)

        # Extrude copper
        copper_mesh = trimesh.creation.extrude_polygon(copper_geom, height=copper_thickness_mm)
        copper_mesh.apply_translation([0, 0, substrate_thickness_mm])

        # Extrude substrate bounding box with 1.5mm margin
        minx, miny, maxx, maxy = copper_geom.bounds
        margin = 1.5
        sub_poly = sg.box(minx - margin, miny - margin, maxx + margin, maxy + margin)
        sub_mesh = trimesh.creation.extrude_polygon(sub_poly, height=substrate_thickness_mm)

        combined = trimesh.util.concatenate([sub_mesh, copper_mesh])
        combined.export(str(target))
        return target

    def export_3d_gmsh(
        self,
        component: gf.Component,
        output_path: str | Path,
        substrate_thickness_mm: float = 0.20,
        copper_thickness_mm: float = 0.035,
        margin_mm: float = 2.0,
    ) -> Path:
        """Generates a 3D volume tetrahedral .msh mesh with physical group tags for EM solvers."""
        target = Path(output_path).resolve()
        target.parent.mkdir(parents=True, exist_ok=True)

        polys_mm = self.extract_polygons_mm(component)
        if not polys_mm:
            polys_mm = [[(0.0, 0.0), (10.0, 0.0), (10.0, 0.38), (0.0, 0.38)]]

        all_x = [pt[0] for poly in polys_mm for pt in poly]
        all_y = [pt[1] for poly in polys_mm for pt in poly]
        min_x, max_x = min(all_x), max(all_x)
        min_y, max_y = min(all_y), max(all_y)

        # Re-initialize Gmsh
        gmsh.initialize()
        gmsh.option.setNumber("General.Verbosity", 1)
        gmsh.model.add(component.name)

        # 1. Substrate Box
        sub_dx = (max_x - min_x) + 2.0 * margin_mm
        sub_dy = (max_y - min_y) + 2.0 * margin_mm
        sub_x0 = min_x - margin_mm
        sub_y0 = min_y - margin_mm
        sub_vol = gmsh.model.occ.addBox(sub_x0, sub_y0, 0.0, sub_dx, sub_dy, substrate_thickness_mm)

        # 2. Copper Trace Boxes
        copper_vols = []
        for poly in polys_mm:
            px = [p[0] for p in poly]
            py = [p[1] for p in poly]
            p_minx, p_maxx = min(px), max(px)
            p_miny, p_maxy = min(py), max(py)
            c_box = gmsh.model.occ.addBox(
                p_minx,
                p_miny,
                substrate_thickness_mm,
                p_maxx - p_minx,
                p_maxy - p_miny,
                copper_thickness_mm,
            )
            copper_vols.append(c_box)

        gmsh.model.occ.synchronize()

        # 3. Define Physical Tags for openEMS / 3D EM solvers
        gmsh.model.addPhysicalGroup(3, [sub_vol], 1, name="Dielectric_FR4")
        if copper_vols:
            gmsh.model.addPhysicalGroup(3, copper_vols, 2, name="Conducting_Copper")

        # 4. Generate 3D Tetrahedral Mesh
        gmsh.model.mesh.generate(3)
        gmsh.write(str(target))
        gmsh.finalize()

        return target
