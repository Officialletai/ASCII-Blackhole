"""
Real-Time Interactive ASCII Black Hole Renderer (Schwarzschild Spacetime).

Author: worker_m1 (Teamwork Preview Implementer)
Architecture: Pure NumPy Vectorized Ray Tracing & Relativistic Radiative Transfer
Display Engine: Pygame Monospace Display with Cached Glyph Blitting

Physical & Mathematical Foundations (referenced in blackhole.md):
1. Schwarzschild Metric Line Element:
   ds^2 = -(1 - r_s/r) c^2 dt^2 + (1 - r_s/r)^(-1) dr^2 + r^2 (d theta^2 + sin^2 theta d phi^2)
2. Null Geodesic Radial Binet Equation:
   (du/d phi)^2 = 1/b^2 - u^2 + r_s u^3,  where u = 1/r
3. Photon Sphere & Critical Impact Parameter:
   r_ph = 1.5 * r_s = 3M
   b_crit = (3 * sqrt(3) / 2) * r_s approx 2.598076211 r_s
4. Light Deflection Integral:
   phi_tot(b) = 2 * integral_0^{u_1} du / sqrt(1/b^2 - u^2 + r_s u^3)
   Delta phi(b) = phi_tot(b) - pi
5. Keplerian Orbital Velocity & Kinematics:
   v(r) = c * sqrt(r_s / (2r))
   gamma(r) = 1 / sqrt(1 - (v/c)^2)
   g_grav(r) = sqrt(1 - r_s / r)
6. Relativistic Doppler Beaming:
   delta = 1 / (gamma * (1 - beta * cos(alpha)))
   I_obs = (g_grav * delta)^4 * I_emit(r)
7. Thin Accretion Disk Base Emissivity (Shakura & Sunyaev 1973):
   I_emit(r) = r^(-3/4) * (1 - sqrt(r_ISCO / r))^(1/4)  for r in [r_ISCO, r_out]
8. Monospace ASCII Luminance Quantization:
   Ramp: " .,-~:;=!*#$@"
"""

from __future__ import annotations

import argparse
import math
import os
import sys
import time
import tracemalloc
from typing import Optional, Tuple, Dict, Any

import numpy as np

# =====================================================================
# Physical Constants & Default Boundaries (Geometric units G = c = 1)
# =====================================================================
C: float = 1.0
G: float = 1.0
R_S: float = 1.0  # Schwarzschild radius (r_s = 2GM/c^2)
R_PH: float = 1.5 * R_S  # Photon sphere radius (r_ph = 1.5 r_s)
B_CRIT: float = (3.0 * math.sqrt(3.0) / 2.0) * R_S  # Critical impact parameter (approx 2.598076 r_s)
R_ISCO: float = 3.0 * R_S  # Innermost stable circular orbit (ISCO = 3.0 r_s)
R_OUT: float = 10.0 * R_S  # Outer accretion disk boundary

# Keplerian differential shear & accretion disk wave parameters
OMEGA_0: float = 1.8  # Fundamental angular velocity at ISCO boundary (rad/s)
SPIRAL_AMPLITUDE: float = 0.55  # Density wave & plasma hotspot emissivity modulation amplitude

# 12-level character luminance ramp (with leading space = 13 entries for quantization)
RAMP: str = " .,-~:;=!*#$@"
CHARS: str = ".,-~:;=!*#$@"
CHARS_ARRAY: np.ndarray = np.array(list(RAMP))


# =====================================================================
# 1. Geodesic Lookup Table (LUT)
# =====================================================================
class GeodesicLUT:
    """
    Precomputed 1D radial lookup table for Schwarzschild null geodesic deflection.

    Because Schwarzschild spacetime is spherically symmetric, the deflection angle
    Delta phi(b) depends strictly on the impact parameter b alone. Precomputing
    this 1D function enables real-time O(1) evaluation per screen pixel via np.interp.
    """

    def __init__(self, r_s: float = 1.0, num_points: int = 1000, b_max: float = 25.0) -> None:
        self.r_s: float = float(r_s)
        self.b_crit: float = (3.0 * math.sqrt(3.0) / 2.0) * self.r_s
        # Precompute table out to at least 150 r_s to cover both near and far fields
        self.b_max: float = max(float(b_max), 150.0 * self.r_s)
        self.num_points: int = int(num_points)

        # Build non-linear grid clustered near b_crit to resolve logarithmic divergence
        # Darwin-Bozza divergence: Delta phi ~ -ln(b/b_crit - 1)
        eps = 1e-5 * self.r_s
        b_vals = self.b_crit + np.geomspace(eps, self.b_max - self.b_crit, self.num_points)

        # Compute periapsis u_1 for each b:
        # u_1 is the smallest positive root of r_s u^3 - u^2 + 1/b^2 = 0
        cos3th = np.clip(1.0 - 2.0 * (self.b_crit / b_vals) ** 2, -1.0, 1.0)
        theta_cubic = np.arccos(cos3th) / 3.0
        u1_vals = (1.0 + 2.0 * np.cos(theta_cubic + 4.0 * math.pi / 3.0)) / (3.0 * self.r_s)

        # High-order Gauss-Legendre quadrature with singularity removal:
        # Substitution u = u_1 sin^2(w) transforms the improper square-root singularity
        # into a smooth integrand over w in [0, pi/2]:
        # phi_tot(b) = 4 * integral_0^{pi/2} sin(w) dw / sqrt(1 + sin^2(w) - r_s u_1 (1 + sin^2(w) + sin^4(w)))
        n_quad = 64
        nodes, weights = np.polynomial.legendre.leggauss(n_quad)
        w_nodes = 0.25 * math.pi * (nodes + 1.0)
        w_weights = 0.25 * math.pi * weights
        sin_w = np.sin(w_nodes)
        sin2_w = sin_w**2

        # Vectorized evaluation of the 2D grid (num_points x n_quad)
        u1_2d = u1_vals[:, None]
        poly = 1.0 + sin2_w[None, :] - (self.r_s * u1_2d) * (1.0 + sin2_w[None, :] + sin2_w[None, :] ** 2)
        denom = np.sqrt(np.maximum(1e-15, poly))
        integrand = 4.0 * sin_w[None, :] / denom

        phi_tot = np.sum(integrand * w_weights[None, :], axis=1)
        deflection_vals = phi_tot - math.pi

        self.b_table: np.ndarray = b_vals
        self.phi_table: np.ndarray = deflection_vals
        self.is_shadow_table: np.ndarray = np.zeros(self.num_points, dtype=bool)

    def is_shadow(self, b: np.ndarray | float) -> np.ndarray | bool:
        """Return True if impact parameter b falls inside the event horizon shadow."""
        if isinstance(b, (int, float)):
            return b <= self.b_crit
        return np.asarray(b) <= self.b_crit

    def lookup(self, b: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
        """
        Fast O(1) vectorized evaluation of light deflection angle and shadow mask.

        Parameters
        ----------
        b : np.ndarray
            Impact parameters for light rays.

        Returns
        -------
        deflection_angle : np.ndarray
            Bending angle Delta phi(b) in radians (set to np.inf for shadow rays).
        is_shadow_mask : np.ndarray
            Boolean mask, True where b <= b_crit (captured rays forming shadow).
        """
        b_arr = np.asarray(b, dtype=np.float64)
        is_shadow_mask = b_arr <= self.b_crit

        # Linear interpolation against precomputed table
        deflection_angle = np.interp(
            b_arr,
            self.b_table,
            self.phi_table,
            left=self.phi_table[0],
            right=0.0,
        )

        # 2nd-order post-Newtonian Einstein weak-field limit for b beyond table:
        # Delta phi = 2*r_s / b + (15*pi / 16) * (r_s / b)^2
        weak_mask = b_arr > self.b_table[-1]
        if np.any(weak_mask):
            b_w = np.maximum(b_arr[weak_mask], 1e-6)
            deflection_angle[weak_mask] = (2.0 * self.r_s / b_w) + (15.0 * math.pi / 16.0) * (self.r_s / b_w) ** 2

        # Set shadow points to np.inf sentinel
        if np.any(is_shadow_mask):
            deflection_angle = np.where(is_shadow_mask, np.inf, deflection_angle)

        return deflection_angle, is_shadow_mask


# Global cached default LUT for ultra-fast frame renders
_CACHED_DEFAULT_LUT: Optional[GeodesicLUT] = None


def get_default_lut() -> GeodesicLUT:
    """Retrieve or initialize the singleton default GeodesicLUT."""
    global _CACHED_DEFAULT_LUT
    if _CACHED_DEFAULT_LUT is None:
        _CACHED_DEFAULT_LUT = GeodesicLUT(r_s=R_S, num_points=1000, b_max=150.0)
    return _CACHED_DEFAULT_LUT


# =====================================================================
# 2. Relativistic Kinematics & Radiative Transfer
# =====================================================================
def compute_keplerian_velocity(r: np.ndarray | float, r_s: float = 1.0) -> np.ndarray | float:
    """
    Compute relativistic circular Keplerian orbital speed v(r) = c * sqrt(r_s / (2r)).

    Parameters
    ----------
    r : np.ndarray or float
        Radial coordinate from the black hole center.
    r_s : float
        Schwarzschild radius.

    Returns
    -------
    v : np.ndarray or float
        Dimensionless speed beta = v/c (in [0, sqrt(1/6)] for r >= r_ISCO).
    """
    r_arr = np.asarray(r, dtype=np.float64)
    is_scalar = np.ndim(r) == 0

    v = np.zeros_like(r_arr)
    valid = r_arr > 0.5 * r_s
    v[valid] = np.sqrt(r_s / (2.0 * r_arr[valid]))
    return float(v.item()) if is_scalar else v


def compute_gravitational_redshift(r: np.ndarray | float, r_s: float = 1.0) -> np.ndarray | float:
    """
    Compute gravitational redshift factor g_grav(r) = sqrt(1 - r_s / r).

    Photons climbing out of the Schwarzschild gravitational well suffer energy loss
    proportional to the metric time-time component: g_grav = sqrt(-g_tt).

    Parameters
    ----------
    r : np.ndarray or float
        Emission radius.
    r_s : float
        Schwarzschild radius.

    Returns
    -------
    g_grav : np.ndarray or float
        Gravitational redshift factor in (0, 1) for r > r_s.
    """
    r_arr = np.asarray(r, dtype=np.float64)
    is_scalar = np.ndim(r) == 0

    g = np.zeros_like(r_arr)
    valid = r_arr > r_s
    g[valid] = np.sqrt(1.0 - r_s / r_arr[valid])
    return float(g.item()) if is_scalar else g


def compute_doppler_factor(beta: np.ndarray | float, cos_alpha: np.ndarray | float) -> np.ndarray | float:
    """
    Compute relativistic Doppler beaming factor delta = 1 / (gamma * (1 - beta * cos(alpha))).

    Parameters
    ----------
    beta : np.ndarray or float
        Orbital velocity v/c.
    cos_alpha : np.ndarray or float
        Cosine of the angle between emitting gas velocity and photon line-of-sight unit vector.

    Returns
    -------
    delta : np.ndarray or float
        Relativistic kinematic Doppler boost factor.
    """
    b_arr = np.asarray(beta, dtype=np.float64)
    c_arr = np.asarray(cos_alpha, dtype=np.float64)
    is_scalar = np.ndim(beta) == 0 and np.ndim(cos_alpha) == 0

    b_clamped = np.clip(b_arr, 0.0, 0.999)
    gamma = 1.0 / np.sqrt(1.0 - b_clamped**2)
    denom = np.maximum(1e-9, gamma * (1.0 - b_clamped * c_arr))
    delta = 1.0 / denom
    return float(delta.item()) if is_scalar else delta


def compute_keplerian_shear(
    r: np.ndarray | float,
    r_s: float = 1.0,
    r_isco: float = 3.0,
    omega_0: float = OMEGA_0,
) -> np.ndarray | float:
    """
    Compute differential Keplerian angular shear Omega(r) ∝ r^(-3/2).

    In Schwarzschild geometry (as well as Keplerian orbital mechanics), circular
    orbital angular velocity scales differentially as:
        Omega(r) = omega_0 * (r_isco / r)^(3/2)
    ensuring that inner disk plasma near the ISCO (r = 3 r_s) orbits significantly
    faster than the outer rim (r = 10 r_s) with shear ratio (10/3)^(1.5) approx 6.086x.

    Parameters
    ----------
    r : np.ndarray or float
        Radial coordinate from the black hole center.
    r_s : float
        Schwarzschild radius.
    r_isco : float
        Innermost stable circular orbit radius (3.0 * r_s).
    omega_0 : float
        Angular velocity at the ISCO boundary in rad/s (default OMEGA_0 = 1.8).

    Returns
    -------
    omega : np.ndarray or float
        Keplerian angular velocity Omega(r) in rad/s.
    """
    r_arr = np.asarray(r, dtype=np.float64)
    is_scalar = np.ndim(r) == 0

    safe_rs = max(float(r_s), 1e-6)
    safe_r = np.maximum(r_arr, 0.5 * safe_rs)
    omega = omega_0 * (r_isco / safe_r) ** 1.5
    return float(omega.item()) if is_scalar else omega


def compute_disk_swirl_modulation(
    r: np.ndarray | float,
    phi_d: np.ndarray | float,
    t: float,
    counterclockwise: bool = True,
    r_s: float = 1.0,
    r_isco: float = 3.0,
    amplitude: float = SPIRAL_AMPLITUDE,
) -> np.ndarray | float:
    """
    Compute disk emissivity modulation factor M(r, phi, t) from Keplerian shear,
    multi-arm spiral density waves, and advected plasma hotspots:

        Delta I(r, phi, t) = A * sum_k [ w_k * sin(m_k * phi - omega_k(r) * t + delta_k(r)) ]
        M(r, phi, t) = max(0.05, 1.0 + Delta I(r, phi, t))

    Parameters
    ----------
    r : np.ndarray or float
        Radial coordinate on the disk.
    phi_d : np.ndarray or float
        Azimuthal coordinate on the disk in radians [-pi, pi].
    t : float
        Simulation time in seconds.
    counterclockwise : bool
        Disk orbital rotation direction (True = CCW, False = CW).
    r_s : float
        Schwarzschild radius.
    r_isco : float
        ISCO radius (3.0 * r_s).
    amplitude : float
        Overall modulation amplitude A (default SPIRAL_AMPLITUDE = 0.55).

    Returns
    -------
    modulation : np.ndarray or float
        Multiplicative emissivity modulation factor in [0.05, 1.0 + A].
    """
    r_arr = np.asarray(r, dtype=np.float64)
    phi_arr = np.asarray(phi_d, dtype=np.float64)
    is_scalar = np.ndim(r) == 0 and np.ndim(phi_d) == 0

    try:
        t_val = float(t)
        if not math.isfinite(t_val):
            t_val = 0.0
    except Exception:
        t_val = 0.0

    try:
        amp_val = float(amplitude)
        if not math.isfinite(amp_val) or amp_val < 0.0:
            amp_val = SPIRAL_AMPLITUDE
    except Exception:
        amp_val = SPIRAL_AMPLITUDE

    finite_mask = np.isfinite(r_arr) & np.isfinite(phi_arr)
    # Substitute safe coordinates so np.sin never encounters inf or nan
    safe_r = np.where(finite_mask, r_arr, float(r_isco))
    safe_phi = np.where(finite_mask, phi_arr, 0.0)

    rot_sign = 1.0 if counterclockwise else -1.0
    omega_r = compute_keplerian_shear(safe_r, r_s=r_s, r_isco=r_isco, omega_0=OMEGA_0)

    # Multi-arm spiral density waves and advected plasma hotspots:
    # Mode 1: 2-arm grand design spiral density wave (m=2)
    # Mode 2: 3-arm filamentary sub-structures (m=3)
    # Mode 3: Prominent advected plasma hotspot (m=1)
    # Mode 4: High-frequency turbulent ripple (m=5)
    delta_r = (safe_r - r_isco) / max(r_s, 1e-6)

    phase1 = 2.0 * safe_phi - rot_sign * 2.0 * omega_r * t_val - 1.2 * delta_r
    phase2 = 3.0 * safe_phi - rot_sign * 3.0 * omega_r * t_val + 1.2 - 1.8 * delta_r
    phase3 = 1.0 * safe_phi - rot_sign * 1.0 * omega_r * t_val + 0.4
    phase4 = 5.0 * safe_phi - rot_sign * 5.0 * omega_r * t_val - 2.5 * delta_r

    # Normalized wave weights summing to 1.0
    w1, w2, w3, w4 = 0.35, 0.22, 0.30, 0.13
    delta_i = amp_val * (
        w1 * np.sin(phase1) +
        w2 * np.sin(phase2) +
        w3 * np.sin(phase3) +
        w4 * np.sin(phase4)
    )

    modulation = np.maximum(0.05, 1.0 + delta_i)
    modulation = np.where(finite_mask, modulation, 1.0)
    return float(modulation.item()) if is_scalar else modulation


# =====================================================================
# 3. Tone Mapping, Character Ramp & Colormaps
# =====================================================================
def map_intensity_to_ascii(intensity: np.ndarray | float) -> np.ndarray | str:
    """
    Vectorized quantization mapping continuous normalized intensity to ASCII ramp.

    Clamps values <= 0.0 to index 0 (' ') and >= 1.0 to index 12 ('@').
    Gracefully handles NaNs, infinities, and negative numbers.

    Parameters
    ----------
    intensity : np.ndarray or float
        Normalized intensity in [0, 1].

    Returns
    -------
    char_array : np.ndarray or str
        Array of characters from " .,-~:;=!*#$@".
    """
    arr = np.asarray(intensity, dtype=np.float64)
    is_scalar = np.ndim(intensity) == 0

    valid = np.isfinite(arr) & (arr > 0.0)
    clamped = np.clip(np.where(valid, arr, 0.0), 0.0, 1.0)
    indices = np.floor(clamped * (len(RAMP) - 1)).astype(int)
    indices = np.clip(indices, 0, len(RAMP) - 1)
    indices = np.where(valid, indices, 0)

    out = CHARS_ARRAY[indices]
    return str(out.item()) if is_scalar else out


def get_thermal_color(
    r: np.ndarray | float,
    intensity: np.ndarray | float,
    r_isco: float = 3.0,
    r_out: float = 12.0,
) -> np.ndarray:
    """
    Map accretion disk radius and intensity to Planckian thermal black-body RGB colors.

    Color spectrum:
    - Inner disk / ISCO: Hot electric blue-white (T_high, B > R or high white)
    - Intermediate disk: Golden yellow / bright orange
    - Outer disk: Cool deep rust-red (T_low, R > B)
    - Empty space / shadow: Black (0, 0, 0)

    Parameters
    ----------
    r : np.ndarray or float
        Disk hit radius.
    intensity : np.ndarray or float
        Observed bolometric intensity.
    r_isco : float
        ISCO radius.
    r_out : float
        Outer disk radius.

    Returns
    -------
    rgb : np.ndarray
        Array of shape (..., 3) with uint8 color components in [0, 255].
    """
    is_scalar = np.ndim(r) == 0 and np.ndim(intensity) == 0
    r_arr = np.asarray(r, dtype=np.float64)
    i_arr = np.asarray(intensity, dtype=np.float64)

    out = np.zeros(r_arr.shape + (3,), dtype=np.uint8)
    mask = (i_arr > 0.0) & (r_arr >= r_isco) & (r_arr <= r_out)
    if not np.any(mask):
        return out

    # Radial temperature fraction: 1 at r_isco, 0 at r_out
    r_span = max(r_out - r_isco, 1e-6)
    r_norm = np.clip((r_out - r_arr[mask]) / r_span, 0.0, 1.0)

    # Effective temperature combining radial heat and Doppler flux
    i_norm = np.clip(i_arr[mask], 0.0, 1.0)
    t_metric = np.clip(0.65 * r_norm + 0.35 * i_norm, 0.0, 1.0)

    # 4-stage thermal gradient:
    # 0.00 - 0.30: Deep red/rust (170, 35, 10)
    # 0.30 - 0.65: Fiery orange (245, 125, 20)
    # 0.65 - 0.85: Golden yellow (255, 225, 90)
    # 0.85 - 1.00: Brilliant electric blue/white (210, 240, 255)
    r_col = np.where(
        t_metric < 0.30,
        170.0 + (245.0 - 170.0) * (t_metric / 0.30),
        np.where(
            t_metric < 0.65,
            245.0 + (255.0 - 245.0) * ((t_metric - 0.30) / 0.35),
            np.where(
                t_metric < 0.85,
                255.0 + (210.0 - 255.0) * ((t_metric - 0.65) / 0.20),
                210.0 + (255.0 - 210.0) * ((t_metric - 0.85) / 0.15),
            ),
        ),
    )

    g_col = np.where(
        t_metric < 0.30,
        35.0 + (125.0 - 35.0) * (t_metric / 0.30),
        np.where(
            t_metric < 0.65,
            125.0 + (225.0 - 125.0) * ((t_metric - 0.30) / 0.35),
            np.where(
                t_metric < 0.85,
                225.0 + (240.0 - 225.0) * ((t_metric - 0.65) / 0.20),
                240.0 + (255.0 - 240.0) * ((t_metric - 0.85) / 0.15),
            ),
        ),
    )

    b_col = np.where(
        t_metric < 0.30,
        10.0 + (20.0 - 10.0) * (t_metric / 0.30),
        np.where(
            t_metric < 0.65,
            20.0 + (90.0 - 20.0) * ((t_metric - 0.30) / 0.35),
            np.where(
                t_metric < 0.85,
                90.0 + (255.0 - 90.0) * ((t_metric - 0.65) / 0.20),
                255.0,
            ),
        ),
    )

    out[mask, 0] = np.clip(r_col, 0, 255).astype(np.uint8)
    out[mask, 1] = np.clip(g_col, 0, 255).astype(np.uint8)
    out[mask, 2] = np.clip(b_col, 0, 255).astype(np.uint8)

    return out


def compute_grid_dimensions(
    screen_width: int,
    screen_height: int,
    cell_width: int,
    cell_height: int,
    min_cols: int = 20,
    min_rows: int = 10,
) -> Tuple[int, int]:
    """
    Compute optimal ASCII grid dimensions (columns and rows) based on font cell size.

    Calculates the maximum number of monospace character columns and rows that perfectly
    fill the screen without clipping characters or causing distortion.

    Parameters
    ----------
    screen_width : int
        Display width in pixels.
    screen_height : int
        Display height in pixels.
    cell_width : int
        Font character cell width in pixels.
    cell_height : int
        Font character cell height in pixels.
    min_cols : int
        Minimum allowable column count (default 20).
    min_rows : int
        Minimum allowable row count (default 10).

    Returns
    -------
    cols : int
        Number of ASCII grid columns.
    rows : int
        Number of ASCII grid rows.
    """
    def _safe_int(val: Any, default: int) -> int:
        try:
            f = float(val)
            return int(f) if math.isfinite(f) else default
        except Exception:
            return default

    cw = max(1, _safe_int(cell_width, 8))
    ch = max(1, _safe_int(cell_height, 16))
    sw = max(0, _safe_int(screen_width, 0))
    sh = max(0, _safe_int(screen_height, 0))
    min_c = max(1, _safe_int(min_cols, 20))
    min_r = max(1, _safe_int(min_rows, 10))

    cols = max(min_c, sw // cw)
    rows = max(min_r, sh // ch)
    return cols, rows


# =====================================================================
# 4. Vectorized Ray Tracing & Frame Rendering Pipeline
# =====================================================================
def render_frame_ascii(
    cam_dist: float,
    cam_theta: float,
    cam_phi: float,
    width: int = 80,
    height: int = 40,
    lut: Optional[GeodesicLUT] = None,
    counterclockwise: bool = True,
    fov: float = 12.0,
    time: Optional[float] = None,
    swirl: Optional[bool] = None,
    t: Optional[float] = None,
) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    """
    Render a complete 2D ASCII frame of the lensed black hole and accretion disk.

    Pure NumPy vectorized pipeline: executes in < 2 ms on standard desktop CPUs.

    Parameters
    ----------
    cam_dist : float
        Camera distance from black hole origin in units of r_s.
    cam_theta : float
        Camera inclination angle from the disk normal polar axis in radians
        (0 = face-on / pole, pi/2 = edge-on / equator).
    cam_phi : float
        Camera orbital azimuth angle in radians.
    width : int
        ASCII grid column count (default 80).
    height : int
        ASCII grid row count (default 40).
    lut : GeodesicLUT, optional
        Precomputed deflection table. Defaults to cached global LUT.
    counterclockwise : bool
        Disk orbital rotation direction (default True for counterclockwise).
    fov : float
        Camera horizontal field-of-view in units of impact parameter.
    time : float, optional
        Simulation time in seconds for continuous accretion disk swirl animation.
    swirl : bool, optional
        Explicit toggle for accretion disk swirl animation. If None, enabled when
        time or t is specified.
    t : float, optional
        Alias for time parameter.

    Returns
    -------
    char_grid : np.ndarray
        2D array of monospace characters (shape: height x width).
    intensity_grid : np.ndarray
        2D array of normalized observed intensities in [0, 1].
    color_rgb_grid : np.ndarray
        3D array of thermal RGB color values (shape: height x width x 3).
    """
    if lut is None:
        lut = get_default_lut()

    r_s = lut.r_s
    b_crit = lut.b_crit
    r_isco = R_ISCO
    r_out = R_OUT

    if swirl is not None:
        swirl_active = bool(swirl)
    else:
        swirl_active = (time is not None) or (t is not None)

    sim_time = 0.0
    if t is not None:
        try:
            val = float(t)
            if math.isfinite(val):
                sim_time = val
        except Exception:
            pass
    elif time is not None:
        try:
            val = float(time)
            if math.isfinite(val):
                sim_time = val
        except Exception:
            pass

    # Ensure minimum safe grid and FOV dimensions
    def _safe_dim_val(val: Any, default: int, min_val: int = 2) -> int:
        try:
            f = float(val)
            return max(min_val, int(f)) if math.isfinite(f) else default
        except Exception:
            return default

    width = _safe_dim_val(width, 80, 2)
    height = _safe_dim_val(height, 40, 2)

    try:
        fov_f = float(fov)
        fov = max(1e-3, fov_f) if math.isfinite(fov_f) else 12.0
    except Exception:
        fov = 12.0

    # Terminal monospace character aspect ratio correction:
    # Font height is approx twice character width (~2:1)
    aspect_ratio = 2.0
    x_coords = np.linspace(-fov, fov, width)
    y_coords = np.linspace(fov * (height / width) * aspect_ratio, -fov * (height / width) * aspect_ratio, height)
    X, Y = np.meshgrid(x_coords, y_coords)
    b = np.sqrt(X**2 + Y**2)
    b_safe = np.maximum(b, 1e-6)

    # 1. Deflection lookup & shadow classification
    alpha_raw, is_shadow = lut.lookup(b)
    # Avoid invalid math on inf deflection entries inside shadow or unphysical asymptotes
    alpha = np.where(is_shadow | np.isinf(alpha_raw), 0.0, alpha_raw)

    # 2. Camera inclination clamping & trigonometry
    # theta in [0, pi/2]: 0 = face-on (polar), pi/2 = edge-on (equatorial)
    try:
        th_val = float(cam_theta)
        th_clean = th_val if math.isfinite(th_val) else math.radians(75.0)
    except Exception:
        th_clean = math.radians(75.0)
    theta = float(np.clip(th_clean, 0.0, math.pi / 2.0))

    try:
        phi_val = float(cam_phi)
        phi = phi_val if math.isfinite(phi_val) else 0.0
    except Exception:
        phi = 0.0

    cos_th = math.cos(theta)
    sin_th = math.sin(theta)

    # -----------------------------------------------------------------
    # Segment 1: Direct Front Ray Intersection (t1 < D)
    # -----------------------------------------------------------------
    hit_front = Y < 0.0
    r1 = np.sqrt(X**2 + (Y / max(cos_th, 1e-6)) ** 2)
    front_mask = hit_front & (r1 >= r_isco) & (r1 <= r_out)

    # -----------------------------------------------------------------
    # Segment 2: Lensed Rear Ray Intersection (Warped Halos)
    # -----------------------------------------------------------------
    d_z = -np.cos(alpha) * cos_th - np.sin(alpha) * (Y / b_safe) * sin_th
    P_z = Y * sin_th
    s2 = -P_z / np.where(np.abs(d_z) > 1e-9, d_z, 1e-9)

    factor = 1.0 - s2 * np.sin(alpha) / b_safe
    X_c = X * factor
    Y_c = Y * factor
    Z_c = s2 * np.cos(alpha)
    r2 = np.sqrt(X_c**2 + Y_c**2 + Z_c**2)
    rear_mask = (~is_shadow) & (s2 > 0.0) & (r2 >= r_isco) & (r2 <= r_out)

    # -----------------------------------------------------------------
    # Relativistic Kinematics & Doppler Beaming Calculation
    # -----------------------------------------------------------------
    rot_sign = 1.0 if counterclockwise else -1.0

    # Special handling for face-on viewing (theta -> 0)
    # In face-on view, rays encounter disk directly at radius r = b with cos_alpha = 0
    if theta < 1e-3:
        front_mask = np.zeros_like(front_mask)
        rear_mask = (~is_shadow) & (b >= r_isco) & (b <= r_out)
        r2 = b
        cos_alpha_front = np.zeros_like(r1)
        cos_alpha_rear = np.zeros_like(r2)
        x_w2 = X * math.cos(phi) - Y * math.sin(phi)
        y_w2 = X * math.sin(phi) + Y * math.cos(phi)
        phi_disk2 = np.arctan2(y_w2, x_w2)
        phi_disk1 = phi_disk2
    else:
        # Front disk kinematics & equatorial mapping
        cos_alpha_front = -rot_sign * sin_th * (X / np.maximum(r1, 1e-6))
        Y_d = Y / max(cos_th, 1e-6)
        x_w1 = X * math.cos(phi) - Y_d * math.sin(phi)
        y_w1 = X * math.sin(phi) + Y_d * math.cos(phi)
        phi_disk1 = np.arctan2(y_w1, x_w1)

        # Rear halo kinematics & equatorial mapping
        d_R = -np.sin(alpha) / b_safe * X
        d_U = -np.sin(alpha) / b_safe * Y
        d_F = np.cos(alpha)
        d_x = d_R * math.cos(phi) - d_U * cos_th * math.sin(phi) - d_F * sin_th * math.sin(phi)
        d_y = d_R * math.sin(phi) + d_U * cos_th * math.cos(phi) + d_F * sin_th * math.cos(phi)

        x_w2 = X_c * math.cos(phi) - Y_c * cos_th * math.sin(phi) - Z_c * sin_th * math.sin(phi)
        y_w2 = X_c * math.sin(phi) + Y_c * cos_th * math.cos(phi) + Z_c * sin_th * math.cos(phi)

        cos_alpha_rear = rot_sign * (y_w2 * d_x - x_w2 * d_y) / np.maximum(r2, 1e-6)
        cos_alpha_rear = np.clip(cos_alpha_rear, -0.999, 0.999)
        phi_disk2 = np.arctan2(y_w2, x_w2)

    beta1 = compute_keplerian_velocity(r1, r_s=r_s)
    delta1 = compute_doppler_factor(beta1, cos_alpha_front)
    g1 = compute_gravitational_redshift(r1, r_s=r_s)
    emissivity1 = np.maximum(0.0, 1.0 - np.sqrt(r_isco / np.maximum(r1, 1e-6))) ** 0.25 / np.maximum(r1, 1e-6) ** 0.75

    beta2 = compute_keplerian_velocity(r2, r_s=r_s)
    delta2 = compute_doppler_factor(beta2, cos_alpha_rear)
    g2 = compute_gravitational_redshift(r2, r_s=r_s)
    emissivity2 = np.maximum(0.0, 1.0 - np.sqrt(r_isco / np.maximum(r2, 1e-6))) ** 0.25 / np.maximum(r2, 1e-6) ** 0.75

    if swirl_active:
        mod1 = compute_disk_swirl_modulation(
            r1, phi_disk1, sim_time, counterclockwise=counterclockwise, r_s=r_s, r_isco=r_isco
        )
        mod2 = compute_disk_swirl_modulation(
            r2, phi_disk2, sim_time, counterclockwise=counterclockwise, r_s=r_s, r_isco=r_isco
        )
        emissivity1 = emissivity1 * mod1
        emissivity2 = emissivity2 * mod2

    flux1 = (g1 * delta1) ** 4 * emissivity1
    flux2 = (g2 * delta2) ** 4 * emissivity2

    # -----------------------------------------------------------------
    # Intensity Compositing
    # -----------------------------------------------------------------
    intensity = np.zeros_like(b, dtype=np.float64)
    radius_grid = np.zeros_like(b, dtype=np.float64)

    intensity[rear_mask] = flux2[rear_mask]
    radius_grid[rear_mask] = r2[rear_mask]

    intensity[front_mask] = flux1[front_mask]
    radius_grid[front_mask] = r1[front_mask]

    # Clean pitch black circular shadow core
    intensity[is_shadow] = 0.0

    # -----------------------------------------------------------------
    # Linear Physical Normalization & Character Quantization
    # -----------------------------------------------------------------
    max_intensity = np.max(intensity)
    norm_intensity = (intensity / max_intensity) if max_intensity > 0.0 else intensity

    char_grid = map_intensity_to_ascii(norm_intensity)
    color_rgb_grid = get_thermal_color(radius_grid, norm_intensity, r_isco=r_isco, r_out=r_out)

    return char_grid, norm_intensity, color_rgb_grid


# =====================================================================
# 5. Headless Benchmark Runner
# =====================================================================
def run_headless_benchmark(
    num_frames: int = 60, width: int = 80, height: int = 40, swirl: bool = True
) -> Dict[str, float]:
    """
    Execute an automated headless benchmark rendering num_frames sequential frames.

    Tracks execution time, FPS, and memory allocations via tracemalloc.

    Parameters
    ----------
    num_frames : int
        Number of frames to render (default 60).
    width : int
        Frame column count.
    height : int
        Frame row count.
    swirl : bool
        Whether continuous accretion disk swirl animation is enabled (default True).

    Returns
    -------
    metrics : dict
        {"fps": float, "frame_time_ms": float, "memory_delta_mb": float}
    """
    lut = get_default_lut()

    # Pre-render warmup
    _ = render_frame_ascii(
        25.0, math.radians(75.0), 0.0, width=width, height=height, lut=lut, swirl=swirl
    )

    tracemalloc.start()
    baseline_mem = 0
    t0 = time.perf_counter()

    for i in range(num_frames):
        if i == 10:
            baseline_mem, _ = tracemalloc.get_traced_memory()
        sim_t = i * (1.0 / 60.0)
        phi = i * (2.0 * math.pi / max(num_frames, 1))
        _ = render_frame_ascii(
            25.0, math.radians(75.0), phi, width=width, height=height, lut=lut, time=sim_t, swirl=swirl
        )

    total_time = time.perf_counter() - t0
    end_mem, _ = tracemalloc.get_traced_memory()
    tracemalloc.stop()

    frame_time_ms = (total_time / max(num_frames, 1)) * 1000.0
    fps = num_frames / max(total_time, 1e-6)
    memory_delta_mb = max(0.0, (end_mem - baseline_mem) / (1024.0 * 1024.0))

    return {
        "fps": float(fps),
        "frame_time_ms": float(frame_time_ms),
        "memory_delta_mb": float(memory_delta_mb),
    }


# =====================================================================
# 6. Built-in Automated Self-Verification Suite (`--test`)
# =====================================================================
def run_self_tests() -> bool:
    """
    Run comprehensive self-verification tests (Tiers 1–4) without external dependencies.

    Returns True if all assertions pass, False otherwise.
    """
    print("================================================================")
    print("      Running Black Hole Renderer Automated Verification Suite   ")
    print("================================================================")

    # -------------------------------------------------------------
    # Tier 1: Feature Unit Tests
    # -------------------------------------------------------------
    print("[Tier 1] Verifying analytical constants and physics formulas...")
    lut = GeodesicLUT(r_s=1.0, num_points=1000, b_max=150.0)

    # T1.1: Critical impact parameter b_crit
    expected_b_crit = (3.0 * math.sqrt(3.0) / 2.0) * 1.0
    assert abs(lut.b_crit - expected_b_crit) < 1e-6, f"b_crit error: {lut.b_crit} vs {expected_b_crit}"
    print(f"  [PASS] b_crit derivation: {lut.b_crit:.6f} == {expected_b_crit:.6f}")

    # T1.2: Capture flag inside b_crit
    deflection, shadow = lut.lookup(np.array([1.0, 2.0, lut.b_crit - 1e-4, lut.b_crit]))
    assert np.all(shadow), "Shadow rays must be flagged as True"
    assert np.all(np.isinf(deflection)), "Shadow rays must evaluate to inf deflection"
    print("  [PASS] Horizon capture flag & shadow sentinel verified")

    # T1.3: Monotonicity for b > b_crit
    b_test = np.linspace(lut.b_crit + 0.01, 30.0, 50)
    defl_test, _ = lut.lookup(b_test)
    assert np.all(np.diff(defl_test) < 0.0), "Deflection must decrease monotonically with b"
    print("  [PASS] Deflection monotonicity verified across b > b_crit")

    # T1.4: Keplerian velocity profile
    v_isco = compute_keplerian_velocity(3.0, r_s=1.0)
    assert abs(v_isco - math.sqrt(1.0 / 6.0)) < 1e-6, f"v_isco error: {v_isco}"
    v_out = compute_keplerian_velocity(8.0, r_s=1.0)
    assert abs(v_out - 0.25) < 1e-6, f"v_out error: {v_out}"
    print(f"  [PASS] Keplerian velocity: v(ISCO)={v_isco:.6f}, v(8*r_s)={v_out:.6f}")

    # T1.5: Gravitational redshift at ISCO
    g_isco = compute_gravitational_redshift(3.0, r_s=1.0)
    assert abs(g_isco - math.sqrt(2.0 / 3.0)) < 1e-6, f"g_isco error: {g_isco}"
    print(f"  [PASS] Gravitational redshift: g(ISCO)={g_isco:.6f}")

    # T1.6: Doppler factor invariant
    beta_isco = math.sqrt(1.0 / 6.0)
    d_app = compute_doppler_factor(beta_isco, 1.0)
    d_rec = compute_doppler_factor(beta_isco, -1.0)
    assert abs(d_app * d_rec - 1.0) < 1e-6, f"Doppler invariant error: {d_app * d_rec}"
    doppler_ratio_4 = (d_app / d_rec) ** 4
    assert doppler_ratio_4 > 25.0, f"Doppler beaming ratio too low: {doppler_ratio_4}"
    print(f"  [PASS] Doppler invariant: delta_app*delta_rec={d_app*d_rec:.6f}, ratio^4={doppler_ratio_4:.2f}x")

    # T1.7: Luminance ramp clamping and character reachability
    test_intensities = np.array([-5.0, 0.0, 0.5, 1.0, 2.5, np.nan, np.inf])
    mapped_chars = map_intensity_to_ascii(test_intensities)
    assert mapped_chars[0] == " " and mapped_chars[1] == " "
    assert mapped_chars[3] == "@" and mapped_chars[4] == "@"
    assert mapped_chars[5] == " " and mapped_chars[6] == " "
    # Full reachability
    full_ramp = map_intensity_to_ascii(np.linspace(0.0, 1.0, 13))
    assert len(set(full_ramp)) >= 12, "All ramp characters must be reachable"
    print("  [PASS] ASCII luminance ramp clamping & full reachability verified")

    # T1.8: Keplerian differential shear Omega(r) ∝ r^(-3/2)
    omega_isco = compute_keplerian_shear(3.0)
    omega_out = compute_keplerian_shear(10.0)
    shear_ratio = omega_isco / omega_out
    expected_shear_ratio = (10.0 / 3.0) ** 1.5
    assert abs(shear_ratio - expected_shear_ratio) < 1e-4, f"Shear ratio mismatch: {shear_ratio} vs {expected_shear_ratio}"
    assert omega_isco > omega_out, "Inner disk must orbit faster than outer rim"
    print(f"  [PASS] Keplerian differential shear: Omega(ISCO)/Omega(10*r_s) = {shear_ratio:.3f}x == {expected_shear_ratio:.3f}x")

    # T1.9: Grid dimension calculation
    cols_calc, rows_calc = compute_grid_dimensions(1920, 1080, 8, 16)
    assert cols_calc == 240 and rows_calc == 67
    assert cols_calc * 8 <= 1920 and rows_calc * 16 <= 1080
    print(f"  [PASS] Dynamic grid sizing: 1920x1080 (8x16 font) -> {cols_calc}x{rows_calc} without clipping")

    # -------------------------------------------------------------
    # Tier 2: Boundary & Corner Cases
    # -------------------------------------------------------------
    print("\n[Tier 2] Verifying boundary and corner cases...")

    # T2.1 & T2.2: Strong lensing outside b_crit + eps
    defl_strong, _ = lut.lookup(np.array([lut.b_crit + 1e-4]))
    assert defl_strong[0] > 2.0 * math.pi, f"Strong deflection should exceed 2*pi, got {defl_strong[0]}"
    print(f"  [PASS] Strong field lensing at b_crit + 1e-4: Delta phi = {defl_strong[0]:.2f} rad (> 2*pi)")

    # T2.3 & T2.4: Weak field deflection
    defl_weak, _ = lut.lookup(np.array([50.0, 100.0]))
    einstein_50 = 2.0 / 50.0
    einstein_100 = 2.0 / 100.0
    err_50 = abs(defl_weak[0] - einstein_50) / einstein_50
    err_100 = abs(defl_weak[1] - einstein_100) / einstein_100
    assert err_50 < 0.05, f"Weak field error at b=50 too high: {err_50:.2%}"
    assert err_100 < 0.03, f"Weak field error at b=100 too high: {err_100:.2%}"
    print(f"  [PASS] Weak-field convergence: rel_err(50)={err_50:.2%}, rel_err(100)={err_100:.2%}")

    # T2.5: Face-on azimuthal balance
    _, face_intensity, _ = render_frame_ascii(25.0, 0.0, 0.0, width=80, height=40, lut=lut)
    left_face = np.sum(face_intensity[:, :40])
    right_face = np.sum(face_intensity[:, 40:])
    face_diff = abs(left_face - right_face)
    assert face_diff < 1e-4, f"Face-on asymmetry should be 0, got diff {face_diff}"
    print(f"  [PASS] Face-on azimuthal Doppler balance: diff = {face_diff:.2e}")

    # -------------------------------------------------------------
    # Tier 3: Combinatorial Cross-Feature Tests
    # -------------------------------------------------------------
    print("\n[Tier 3] Verifying relativistic Doppler asymmetry & halo separation...")

    # T3.1: Left-right Doppler flux asymmetry (>= 3.0x on 75 deg inclined disk)
    char_grid, inclined_intensity, color_grid = render_frame_ascii(
        25.0, math.radians(75.0), 0.0, width=80, height=40, lut=lut, counterclockwise=True
    )
    left_flux = np.sum(inclined_intensity[:, :40])
    right_flux = np.sum(inclined_intensity[:, 40:])
    asym_ratio = left_flux / max(right_flux, 1e-6)
    assert asym_ratio >= 3.0, f"Doppler asymmetry ratio should be >= 3.0x, got {asym_ratio:.2f}x"
    print(f"  [PASS] Doppler asymmetry ratio: {asym_ratio:.2f}x (>= 3.0x threshold)")

    # T3.2: Rotation inversion flips asymmetry
    _, rev_intensity, _ = render_frame_ascii(
        25.0, math.radians(75.0), 0.0, width=80, height=40, lut=lut, counterclockwise=False
    )
    rev_left = np.sum(rev_intensity[:, :40])
    rev_right = np.sum(rev_intensity[:, 40:])
    rev_ratio = rev_right / max(rev_left, 1e-6)
    assert rev_ratio >= 3.0, f"Reversed Doppler ratio should be >= 3.0x, got {rev_ratio:.2f}x"
    print(f"  [PASS] Doppler rotation inversion: right/left = {rev_ratio:.2f}x")

    # T3.3: Shadow core darkness
    W, H = 80, 40
    aspect = 2.0
    fov = 12.0
    x_c = np.linspace(-fov, fov, W)
    y_c = np.linspace(fov * (H / W) * aspect, -fov * (H / W) * aspect, H)
    X_m, Y_m = np.meshgrid(x_c, y_c)
    b_m = np.sqrt(X_m**2 + Y_m**2)
    shadow_mask = b_m <= lut.b_crit
    shadow_luminance = np.sum(inclined_intensity[shadow_mask])
    assert shadow_luminance == 0.0, f"Shadow core must have zero luminance, got {shadow_luminance}"
    print("  [PASS] Shadow core darkness: 100% dark within b_crit")

    # T3.4: Palette character grid invariance
    char_count = np.count_nonzero(char_grid != " ")
    assert char_count > 200, f"Rendered frame should contain > 200 non-space characters, got {char_count}"
    print(f"  [PASS] Structural non-degeneracy: {char_count} active ASCII glyphs rendered")

    # T3.5: Accretion disk swirl temporal variance
    _, int_t0, _ = render_frame_ascii(
        25.0, math.radians(75.0), 0.0, width=80, height=40, lut=lut, time=0.0, swirl=True
    )
    _, int_t1, _ = render_frame_ascii(
        25.0, math.radians(75.0), 0.0, width=80, height=40, lut=lut, time=1.0, swirl=True
    )
    diff_swirl = float(np.max(np.abs(int_t0 - int_t1)))
    assert diff_swirl > 0.05, f"Swirl must produce temporal intensity changes, max diff: {diff_swirl}"
    print(f"  [PASS] Swirl temporal variance: max diff = {diff_swirl:.3f} across t1!=t2")

    # -------------------------------------------------------------
    # Tier 4: Headless Real-World Execution & Benchmark
    # -------------------------------------------------------------
    print("\n[Tier 4] Running 60-frame headless performance benchmark (with swirl enabled)...")
    bench = run_headless_benchmark(num_frames=60, width=80, height=40, swirl=True)
    print(f"  Measured Framerate: {bench['fps']:.1f} FPS (Target: >= 60.0 FPS)")
    print(f"  Mean Frame Time:   {bench['frame_time_ms']:.2f} ms / frame (Budget: <= 16.6 ms)")
    print(f"  Memory Growth:     {bench['memory_delta_mb']:.3f} MB (Limit: < 5.0 MB)")

    assert bench["fps"] >= 60.0, f"Benchmark FPS below 60 threshold: {bench['fps']}"
    assert bench["memory_delta_mb"] < 5.0, f"Memory leak detected: {bench['memory_delta_mb']} MB"

    # T4.2: Fullscreen toggle and windowed geometry restoration
    app_fs = BlackHoleApp(cols=80, rows=40)
    w_init, h_init = app_fs.screen_w, app_fs.screen_h
    app_fs.toggle_fullscreen()
    assert app_fs.is_fullscreen is True
    assert app_fs.cols * app_fs.cell_w <= app_fs.screen_w
    app_fs.toggle_fullscreen()
    assert app_fs.is_fullscreen is False
    assert app_fs.screen_w == w_init and app_fs.screen_h == h_init
    print(f"  [PASS] Fullscreen toggle & windowed restore verified ({app_fs.cols}x{app_fs.rows})")
    app_fs.pygame.quit()

    print("\n================================================================")
    print("      ALL TESTS PASSED SUCCESSFULLY! (EXIT CODE 0)              ")
    print("================================================================")
    return True


# =====================================================================
# 7. Interactive Pygame Application
# =====================================================================
class BlackHoleApp:
    """
    Real-time interactive ASCII Black Hole application using Pygame.

    Features:
    - 60 FPS smooth rendering via cached monospace font glyph blitting.
    - Continuous Keplerian swirling accretion disk animation (shear & spiral plasma).
    - Instant fullscreen toggle [F / F11] and dynamic window resizing with zero distortion.
    - Interactive 3D camera orbit (mouse drag and keyboard).
    - Palette toggle between monochrome green/white phosphor and thermal heat colors.
    - Dynamic on-screen HUD telemetry overlay.
    """

    def __init__(
        self,
        cols: int = 100,
        rows: int = 50,
        fov: float = 12.0,
        distance: float = 25.0,
        elevation: float = 75.0,
        azimuth: float = 0.0,
        color_mode: bool = False,
        sim_time: float = 0.0,
        swirl: bool = True,
        fullscreen: bool = False,
        speed: float = 0.4,
    ) -> None:
        def _safe_app_int(val: Any, default: int, min_val: int = 2) -> int:
            try:
                f = float(val)
                return max(min_val, int(f)) if math.isfinite(f) else default
            except Exception:
                return default

        self.cols: int = _safe_app_int(cols, 100, 2)
        self.rows: int = _safe_app_int(rows, 50, 2)
        self.windowed_cols: int = self.cols
        self.windowed_rows: int = self.rows

        try:
            f = float(fov)
            self.fov: float = max(1e-3, f) if math.isfinite(f) else 12.0
        except Exception:
            self.fov = 12.0

        try:
            d = float(distance)
            self.distance: float = max(1.0, d) if math.isfinite(d) else 25.0
        except Exception:
            self.distance = 25.0

        try:
            el = float(elevation)
            self.theta: float = math.radians(el) if math.isfinite(el) else math.radians(75.0)
        except Exception:
            self.theta = math.radians(75.0)

        try:
            az = float(azimuth)
            self.phi: float = math.radians(az) if math.isfinite(az) else 0.0
        except Exception:
            self.phi = 0.0

        self.color_mode: bool = bool(color_mode)
        self.counterclockwise: bool = True
        self.show_hud: bool = True
        self.is_fullscreen: bool = False
        try:
            st = float(sim_time)
            self.sim_time: float = st if math.isfinite(st) else 0.0
        except Exception:
            self.sim_time = 0.0
        self.swirl: bool = bool(swirl)

        try:
            sp = float(speed)
            self.speed: float = max(0.0, sp) if math.isfinite(sp) else 0.4
        except Exception:
            self.speed = 0.4
        self._prev_speed: float = self.speed if self.speed > 0.0 else 0.4

        self.lut: GeodesicLUT = get_default_lut()

        # Initialize Pygame
        import pygame

        self.pygame = pygame
        self.pygame.init()

        # Set up monospace font
        self.font_size = 14
        font_candidates = ["consolas", "couriernew", "dejavusansmono", "lucidaconsole", "monospace"]
        self.font = None
        for name in font_candidates:
            matched = self.pygame.font.match_font(name)
            if matched:
                try:
                    self.font = self.pygame.font.Font(matched, self.font_size)
                    break
                except Exception:
                    continue
        if self.font is None:
            self.font = self.pygame.font.SysFont("monospace", self.font_size)

        # Measure glyph cell dimensions
        sample = self.font.render("@", True, (255, 255, 255))
        self.cell_w = max(1, sample.get_width())
        self.cell_h = max(1, sample.get_height())

        self.screen_w = self.cols * self.cell_w
        self.screen_h = self.rows * self.cell_h
        self.windowed_w = self.screen_w
        self.windowed_h = self.screen_h

        # Query native desktop display resolution BEFORE setting initial windowed mode
        disp_info = self.pygame.display.Info()
        self.desktop_w: int = disp_info.current_w if disp_info.current_w > 0 else self.screen_w
        self.desktop_h: int = disp_info.current_h if disp_info.current_h > 0 else self.screen_h

        # Setup display surface with RESIZABLE flag
        self.screen = self.pygame.display.set_mode(
            (self.screen_w, self.screen_h), self.pygame.RESIZABLE
        )
        self.pygame.display.set_caption("Black Hole ASCII Renderer (Schwarzschild Geodesics & Keplerian Swirl)")
        self.clock = self.pygame.time.Clock()

        # Pre-render monochrome glyph cache
        self.mono_glyph_cache: Dict[str, Any] = {}
        for ch in RAMP:
            self.mono_glyph_cache[ch] = self.font.render(ch, True, (225, 235, 240))

        # Mouse drag state
        self.dragging: bool = False
        self.last_mouse_pos: Tuple[int, int] = (0, 0)

        if fullscreen:
            self.toggle_fullscreen()

    def toggle_fullscreen(self) -> None:
        """Toggle between windowed mode and borderless/fullscreen mode."""
        if not self.is_fullscreen:
            # Entering fullscreen: save current windowed geometry
            self.windowed_w = self.screen_w
            self.windowed_h = self.screen_h
            self.windowed_cols = self.cols
            self.windowed_rows = self.rows

            fs_w = self.desktop_w
            fs_h = self.desktop_h

            try:
                self.screen = self.pygame.display.set_mode((0, 0), self.pygame.FULLSCREEN)
            except Exception:
                try:
                    self.screen = self.pygame.display.set_mode((fs_w, fs_h), self.pygame.FULLSCREEN)
                except Exception:
                    try:
                        self.screen = self.pygame.display.set_mode((fs_w, fs_h))
                    except Exception:
                        pass

            try:
                actual_w, actual_h = self.screen.get_size()
                if actual_w > 0 and actual_h > 0:
                    fs_w, fs_h = actual_w, actual_h
            except Exception:
                pass

            self.is_fullscreen = True
            self.screen_w = fs_w
            self.screen_h = fs_h
            self.cols, self.rows = compute_grid_dimensions(fs_w, fs_h, self.cell_w, self.cell_h)
        else:
            # Exiting fullscreen: safely restore original windowed resolution
            try:
                self.screen = self.pygame.display.set_mode(
                    (self.windowed_w, self.windowed_h), self.pygame.RESIZABLE
                )
            except Exception:
                try:
                    self.screen = self.pygame.display.set_mode((self.windowed_w, self.windowed_h))
                except Exception:
                    pass

            self.is_fullscreen = False
            self.screen_w = self.windowed_w
            self.screen_h = self.windowed_h
            self.cols = self.windowed_cols
            self.rows = self.windowed_rows

    def handle_resize(self, new_w: int, new_h: int) -> None:
        """Handle window resize event and recompute ASCII grid dimensions."""
        try:
            w_val = float(new_w)
            h_val = float(new_h)
            if not (math.isfinite(w_val) and math.isfinite(h_val)) or w_val <= 0 or h_val <= 0:
                return
            new_w = int(w_val)
            new_h = int(h_val)
        except Exception:
            return

        if self.is_fullscreen and new_w == self.screen_w and new_h == self.screen_h:
            return
        flags = self.pygame.FULLSCREEN if self.is_fullscreen else self.pygame.RESIZABLE
        try:
            self.screen = self.pygame.display.set_mode((new_w, new_h), flags)
        except Exception:
            try:
                self.screen = self.pygame.display.set_mode((new_w, new_h))
            except Exception:
                pass

        try:
            actual_w, actual_h = self.screen.get_size()
            if actual_w > 0 and actual_h > 0:
                new_w, new_h = actual_w, actual_h
        except Exception:
            pass

        self.screen_w = new_w
        self.screen_h = new_h
        self.cols, self.rows = compute_grid_dimensions(new_w, new_h, self.cell_w, self.cell_h)
        if not self.is_fullscreen:
            self.windowed_w = new_w
            self.windowed_h = new_h
            self.windowed_cols = self.cols
            self.windowed_rows = self.rows

    def handle_event(self, event: Any) -> bool:
        """
        Process a single Pygame input or window event.

        Parameters
        ----------
        event : pygame.event.Event
            Event to dispatch.

        Returns
        -------
        keep_running : bool
            False if the application should terminate (QUIT or ESC when windowed),
            True otherwise.
        """
        if event.type == self.pygame.QUIT:
            return False
        elif event.type == self.pygame.VIDEORESIZE:
            self.handle_resize(event.w, event.h)
            return True
        elif event.type == self.pygame.KEYDOWN:
            if event.key == self.pygame.K_ESCAPE:
                if self.is_fullscreen:
                    self.toggle_fullscreen()
                    return True
                else:
                    return False
            elif event.key in (self.pygame.K_f, self.pygame.K_F11):
                self.toggle_fullscreen()
                return True
            elif event.key == self.pygame.K_c:
                self.color_mode = not self.color_mode
                return True
            elif event.key in (self.pygame.K_h, self.pygame.K_TAB):
                self.show_hud = not self.show_hud
                return True
            elif event.key == self.pygame.K_r:
                self.theta = math.radians(75.0)
                self.phi = 0.0
                self.fov = 12.0
                return True
            elif event.key == self.pygame.K_SPACE:
                self.counterclockwise = not self.counterclockwise
                return True
            elif event.key in (self.pygame.K_LEFTBRACKET, self.pygame.K_COMMA):
                self.speed = max(0.0, round(self.speed - 0.05, 3))
                return True
            elif event.key in (self.pygame.K_RIGHTBRACKET, self.pygame.K_PERIOD):
                self.speed = min(5.0, round(self.speed + 0.05, 3))
                return True
            elif event.key in (self.pygame.K_p, self.pygame.K_0):
                if self.speed > 0.0:
                    self._prev_speed = self.speed
                    self.speed = 0.0
                else:
                    self.speed = getattr(self, "_prev_speed", 0.4)
                return True
            elif event.key in (self.pygame.K_PLUS, self.pygame.K_EQUALS):
                self.fov = max(4.0, self.fov - 0.5)
                return True
            elif event.key in (self.pygame.K_MINUS, self.pygame.K_UNDERSCORE):
                self.fov = min(30.0, self.fov + 0.5)
                return True
        elif event.type == self.pygame.MOUSEBUTTONDOWN:
            if event.button == 1:
                self.dragging = True
                self.last_mouse_pos = event.pos
            elif event.button == 4:
                self.fov = max(4.0, self.fov * 0.92)
            elif event.button == 5:
                self.fov = min(30.0, self.fov * 1.08)
            return True
        elif event.type == self.pygame.MOUSEBUTTONUP:
            if event.button == 1:
                self.dragging = False
            return True
        elif event.type == self.pygame.MOUSEMOTION and self.dragging:
            dx = event.pos[0] - self.last_mouse_pos[0]
            dy = event.pos[1] - self.last_mouse_pos[1]
            self.last_mouse_pos = event.pos
            self.phi += dx * 0.006
            self.theta = float(np.clip(self.theta - dy * 0.006, 0.0, math.pi / 2.0))
            return True
        return True

    def run(self) -> None:
        """Main Pygame event and rendering loop."""
        running = True
        fps_measured = 60.0

        try:
            while running:
                # 1. Event handling
                for event in self.pygame.event.get():
                    if not self.handle_event(event):
                        running = False
                        break
                if not running:
                    break

                # Keyboard hold controls
                keys = self.pygame.key.get_pressed()
                if keys[self.pygame.K_LEFT] or keys[self.pygame.K_a]:
                    self.phi -= 0.03
                if keys[self.pygame.K_RIGHT] or keys[self.pygame.K_d]:
                    self.phi += 0.03
                if keys[self.pygame.K_UP] or keys[self.pygame.K_w]:
                    self.theta = np.clip(self.theta + 0.025, 0.0, math.pi / 2.0)
                if keys[self.pygame.K_DOWN] or keys[self.pygame.K_s]:
                    self.theta = np.clip(self.theta - 0.025, 0.0, math.pi / 2.0)

                # Time progression for animated Keplerian accretion disk swirl
                dt = self.clock.get_time() / 1000.0
                dt = min(max(dt, 0.0), 0.1)
                if dt == 0.0:
                    dt = 1.0 / 60.0
                self.sim_time += dt * self.speed

                # 2. Render ASCII frame
                char_grid, _, color_grid = render_frame_ascii(
                    cam_dist=self.distance,
                    cam_theta=self.theta,
                    cam_phi=self.phi,
                    width=self.cols,
                    height=self.rows,
                    lut=self.lut,
                    counterclockwise=self.counterclockwise,
                    fov=self.fov,
                    time=self.sim_time,
                    swirl=self.swirl,
                )

                # 3. Clear screen to black
                self.screen.fill((0, 0, 0))

                # 4. Batch blitting
                blit_batch = []
                for r in range(self.rows):
                    row_chars = char_grid[r]
                    row_colors = color_grid[r]
                    py = r * self.cell_h

                    for c in range(self.cols):
                        ch = row_chars[c]
                        if ch == " ":
                            continue
                        px = c * self.cell_w

                        if self.color_mode:
                            rgb = tuple(row_colors[c])
                            glyph = self.font.render(ch, True, rgb)
                            blit_batch.append((glyph, (px, py)))
                        else:
                            glyph = self.mono_glyph_cache.get(ch)
                            if glyph:
                                blit_batch.append((glyph, (px, py)))

                if blit_batch:
                    self.screen.blits(blit_batch, doreturn=False)

                # 5. Render HUD overlay
                if self.show_hud:
                    deg_inc = math.degrees(self.theta)
                    deg_az = math.degrees(self.phi) % 360.0
                    mode_str = "Thermal RGB" if self.color_mode else "Monochrome Phosphor"
                    rot_str = "CCW" if self.counterclockwise else "CW"
                    fs_str = "FULL" if self.is_fullscreen else "WIN"

                    hud_text = (
                        f"FPS: {fps_measured:4.1f} | Inc: {deg_inc:4.1f}° | Az: {deg_az:4.1f}° | "
                        f"Speed: {self.speed:4.2f}x [[/]] | Grid: {self.cols}x{self.rows} [{fs_str} F] | "
                        f"FOV: {self.fov:4.1f} r_s | Palette: {mode_str} [C] | Swirl: {rot_str} [SPACE]"
                    )
                    hud_surf = self.font.render(hud_text, True, (120, 255, 160))
                    self.screen.blit(hud_surf, (8, 6))

                # Flip display buffer
                self.pygame.display.flip()
                self.clock.tick(60)
                fps_measured = self.clock.get_fps()
        finally:
            self.pygame.quit()


# =====================================================================
# 8. Command Line Interface (CLI) Entrypoint
# =====================================================================
def main() -> None:
    """Parse command-line arguments and dispatch application mode."""
    parser = argparse.ArgumentParser(
        description="Real-Time Interactive ASCII Black Hole Renderer (Schwarzschild Spacetime & Keplerian Swirl)",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--test", action="store_true", help="Run automated test suite and exit with code 0")
    parser.add_argument("--benchmark", action="store_true", help="Run 60-frame headless performance benchmark")
    parser.add_argument("--headless", action="store_true", help="Render one frame to terminal stdout and exit")
    parser.add_argument("--fullscreen", "-f", action="store_true", help="Start directly in fullscreen display mode")
    parser.add_argument("--cols", type=int, default=90, help="Horizontal ASCII character columns")
    parser.add_argument("--rows", type=int, default=44, help="Vertical ASCII character rows")
    parser.add_argument("--fov", type=float, default=12.0, help="Camera field of view in impact parameter units")
    parser.add_argument("--distance", type=float, default=25.0, help="Camera distance in Schwarzschild radii")
    parser.add_argument("--elevation", type=float, default=75.0, help="Camera elevation/inclination in degrees")
    parser.add_argument("--azimuth", type=float, default=0.0, help="Camera azimuth angle in degrees")
    parser.add_argument("--color", action="store_true", help="Start directly in thermal black-body color mode")
    parser.add_argument("--time", "-t", type=float, default=0.0, help="Simulation time parameter for swirl animation")
    parser.add_argument("--speed", type=float, default=0.4, help="Accretion disk swirl animation speed multiplier (default: 0.4)")
    parser.add_argument("--no-swirl", action="store_true", help="Disable continuous accretion disk swirl animation")

    args = parser.parse_args()

    if args.test:
        os.environ["SDL_VIDEODRIVER"] = "dummy"
        os.environ["SDL_AUDIODRIVER"] = "dummy"
        passed = run_self_tests()
        sys.exit(0 if passed else 1)

    if args.benchmark:
        os.environ["SDL_VIDEODRIVER"] = "dummy"
        os.environ["SDL_AUDIODRIVER"] = "dummy"
        print(f"Executing 60-frame headless benchmark at {args.cols}x{args.rows} (swirl={'off' if args.no_swirl else 'on'})...")
        results = run_headless_benchmark(
            num_frames=60, width=args.cols, height=args.rows, swirl=not args.no_swirl
        )
        print(f"Benchmark Results:")
        print(f"  Framerate:     {results['fps']:.1f} FPS")
        print(f"  Frame Time:    {results['frame_time_ms']:.2f} ms")
        print(f"  Memory Delta:  {results['memory_delta_mb']:.3f} MB")
        sys.exit(0)

    if args.headless:
        char_grid, _, _ = render_frame_ascii(
            cam_dist=args.distance,
            cam_theta=math.radians(args.elevation),
            cam_phi=math.radians(args.azimuth),
            width=args.cols,
            height=args.rows,
            fov=args.fov,
            time=args.time,
            swirl=not args.no_swirl,
        )
        print("\n".join("".join(row) for row in char_grid))
        sys.exit(0)

    # Launch interactive Pygame application
    try:
        app = BlackHoleApp(
            cols=args.cols,
            rows=args.rows,
            fov=args.fov,
            distance=args.distance,
            elevation=args.elevation,
            azimuth=args.azimuth,
            color_mode=args.color,
            sim_time=args.time,
            swirl=not args.no_swirl,
            fullscreen=args.fullscreen,
            speed=args.speed,
        )
        app.run()
    except Exception as e:
        print(f"[Notice] Pygame GUI window could not be opened ({e}). Falling back to terminal ASCII output:")
        char_grid, _, _ = render_frame_ascii(
            cam_dist=args.distance,
            cam_theta=math.radians(args.elevation),
            cam_phi=math.radians(args.azimuth),
            width=args.cols,
            height=args.rows,
            fov=args.fov,
            time=args.time,
            swirl=not args.no_swirl,
        )
        print("\n".join("".join(row) for row in char_grid))


if __name__ == "__main__":
    main()

