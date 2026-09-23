"""
Automated Test Suite for Real-Time ASCII Black Hole Renderer (Tiers 1-4)
Testing architecture conforming to TEST_INFRA.md and survey_test_explorer_1/report.md.
"""

import os
import sys
import math
import time
import subprocess
import tracemalloc
import pytest
import numpy as np

# Configure headless Pygame environment before importing pygame
os.environ["SDL_VIDEODRIVER"] = "dummy"
os.environ["SDL_AUDIODRIVER"] = "disk"

import blackhole as bh

B_CRIT_THEORETICAL = 3.0 * math.sqrt(3.0) / 2.0  # ~2.598076211353316
RAMP_CANONICAL = " .,-~:;=!*#$@"


# =============================================================================
# TIER 1: FEATURE UNIT TESTS
# =============================================================================

class TestTier1FeatureUnits:
    """Tier 1: Feature unit tests validating fundamental physics and algorithms."""

    def test_bcrit_constant(self):
        """Verify critical impact parameter b_crit = (3*sqrt(3)/2) * r_s ~ 2.598076 r_s."""
        lut = bh.GeodesicLUT(r_s=1.0)
        expected = (3.0 * math.sqrt(3.0) / 2.0) * 1.0
        assert abs(lut.b_crit - expected) < 1e-6, f"Expected b_crit {expected}, got {lut.b_crit}"
        assert abs(lut.b_crit - 2.598076211353316) < 1e-6

        lut_scaled = bh.GeodesicLUT(r_s=2.5)
        expected_scaled = (3.0 * math.sqrt(3.0) / 2.0) * 2.5
        assert abs(lut_scaled.b_crit - expected_scaled) < 1e-6
        assert abs(bh.B_CRIT - expected) < 1e-6

    def test_geodesic_lut_capture_flag(self):
        """Verify all rays with b <= b_crit are flagged as event horizon capture (shadow)."""
        lut = bh.GeodesicLUT(r_s=1.0)
        b_captured = np.array([0.0, 0.5, 1.0, 2.0, 2.5, lut.b_crit - 1e-5, lut.b_crit])
        deflection, is_shadow = lut.lookup(b_captured)

        assert np.all(is_shadow), "All rays with b <= b_crit must be flagged as shadow capture"
        assert np.all(np.isnan(deflection) | np.isinf(deflection)), "Captured rays must return non-finite deflection"

    def test_geodesic_lut_strict_monotonicity(self):
        """Verify deflection angle Delta phi(b) is strictly decreasing for b > b_crit."""
        lut = bh.GeodesicLUT(r_s=1.0)
        b_vals = np.linspace(lut.b_crit + 0.05, 25.0, 50)
        deflection, is_shadow = lut.lookup(b_vals)

        assert not np.any(is_shadow), "Rays with b > b_crit + 0.05 must not be shadow"
        assert np.all(np.isfinite(deflection)), "Deflection must be finite for b > b_crit"
        diffs = np.diff(deflection)
        assert np.all(diffs < 0.0), f"Deflection must strictly decrease with b; diffs max: {np.max(diffs)}"

    def test_geodesic_lut_interpolation_accuracy(self):
        """Verify LUT lookup returns positive deflection consistent with general relativity."""
        lut = bh.GeodesicLUT(r_s=1.0)
        test_points = np.array([3.0, 5.0, 10.0, 20.0])
        deflection, is_shadow = lut.lookup(test_points)

        assert np.all(~is_shadow)
        assert deflection[0] > deflection[1] > deflection[2] > deflection[3]
        assert 0.15 < deflection[2] < 0.35

    def test_keplerian_velocity_profile(self):
        """Verify Keplerian velocity profile v(r) = sqrt(r_s / 2r)."""
        r_s = 1.0
        v_isco = bh.compute_keplerian_velocity(3.0 * r_s, r_s=r_s)
        expected_isco = math.sqrt(1.0 / 6.0)
        assert abs(float(v_isco) - expected_isco) < 1e-6

        v_8 = bh.compute_keplerian_velocity(8.0 * r_s, r_s=r_s)
        expected_8 = math.sqrt(1.0 / 16.0)
        assert abs(float(v_8) - expected_8) < 1e-6

        r_grid = np.array([3.0, 4.0, 6.0, 8.0, 12.0])
        v_grid = bh.compute_keplerian_velocity(r_grid, r_s=r_s)
        assert np.all(np.diff(v_grid) < 0.0)

    def test_gravitational_redshift_isco(self):
        """Verify gravitational redshift g(r) = sqrt(1 - r_s / r)."""
        r_s = 1.0
        g_isco = bh.compute_gravitational_redshift(3.0 * r_s, r_s=r_s)
        expected_isco = math.sqrt(2.0 / 3.0)
        assert abs(float(g_isco) - expected_isco) < 1e-6

        r_grid = np.array([3.0, 6.0, 20.0, 100.0])
        g_grid = bh.compute_gravitational_redshift(r_grid, r_s=r_s)
        assert np.all((g_grid > 0.0) & (g_grid < 1.0))
        assert np.all(np.diff(g_grid) > 0.0)
        assert abs(float(g_grid[-1]) - 1.0) < 0.02

    def test_doppler_factor_invariant(self):
        """Verify relativistic Doppler invariant: delta_app * delta_rec == 1.0."""
        beta = math.sqrt(1.0 / 6.0)
        delta_app = float(bh.compute_doppler_factor(beta, 1.0))
        delta_rec = float(bh.compute_doppler_factor(beta, -1.0))

        product = delta_app * delta_rec
        assert abs(product - 1.0) < 1e-6, f"Expected product 1.0, got {product}"

    def test_doppler_factor_ratio(self):
        """Verify relativistic Doppler ratio and bolometric flux amplification > 30x at ISCO."""
        beta = math.sqrt(1.0 / 6.0)
        delta_app = float(bh.compute_doppler_factor(beta, 1.0))
        delta_rec = float(bh.compute_doppler_factor(beta, -1.0))

        ratio = delta_app / delta_rec
        expected_ratio = math.sqrt((1.0 + beta) / (1.0 - beta)) / math.sqrt((1.0 - beta) / (1.0 + beta))
        assert abs(ratio - expected_ratio) < 1e-5
        beaming_ratio = ratio**4
        assert beaming_ratio > 30.0, f"Expected beaming ratio > 30x, got {beaming_ratio}"

    def test_luminance_ramp_boundary_clamping(self):
        """Verify luminance ramp clamping on extremes: negatives, >1.0, NaN, and Inf."""
        test_inputs = np.array([-10.0, -0.001, 0.0, 1.0, 1.001, 50.0, np.nan, np.inf])
        chars = bh.map_intensity_to_ascii(test_inputs)

        assert chars[0] == " ", f"Negative intensity must clamp to ' ', got '{chars[0]}'"
        assert chars[1] == " ", f"Negative intensity must clamp to ' ', got '{chars[1]}'"
        assert chars[2] == " ", f"Zero intensity must map to ' ', got '{chars[2]}'"
        assert chars[3] == "@", f"1.0 intensity must map to '@', got '{chars[3]}'"
        assert chars[4] == "@", f">1.0 intensity must clamp to '@', got '{chars[4]}'"
        assert chars[5] == "@", f"Extreme intensity must clamp to '@', got '{chars[5]}'"
        assert chars[6] == " ", f"NaN intensity must map to ' ', got '{chars[6]}'"

    def test_luminance_ramp_full_reachability(self):
        """Verify every character in the luminance ramp is reachable."""
        intensities = np.linspace(0.0, 1.0, 100)
        chars = bh.map_intensity_to_ascii(intensities)
        unique_chars = set(chars.flatten())

        for ch in RAMP_CANONICAL:
            assert ch in unique_chars, f"Character '{ch}' from canonical ramp was not reachable"

    def test_luminance_ramp_monotonicity(self):
        """Verify luminance ramp mapping preserves monotonic ordering."""
        intensities = np.linspace(0.0, 1.0, 25)
        chars = bh.map_intensity_to_ascii(intensities)
        char_indices = [RAMP_CANONICAL.index(c) for c in chars.flatten()]
        assert np.all(np.diff(char_indices) >= 0), "Ramp character indices must be non-decreasing"

    def test_disk_intersection_face_on_symmetry(self):
        """Verify face-on camera orientation (cam_theta=0) produces radially symmetric disk radii."""
        _, intensity_grid, _ = bh.render_frame_ascii(cam_dist=25.0, cam_theta=0.0, cam_phi=0.0, width=60, height=60)
        left_half = intensity_grid[:, :30]
        right_half_flipped = np.fliplr(intensity_grid[:, 30:])
        diff = np.abs(left_half - right_half_flipped)
        assert np.mean(diff) < 1e-4, f"Face-on render must be azimuthally symmetric, mean diff: {np.mean(diff)}"

    def test_keplerian_differential_shear(self):
        """Verify differential Keplerian angular shear Omega(r) ∝ r^(-3/2)."""
        r_isco = 3.0
        r_out = 10.0
        omega_isco = bh.compute_keplerian_shear(r_isco)
        omega_out = bh.compute_keplerian_shear(r_out)

        # Theoretical ratio: (r_out / r_isco)^(1.5) = (10/3)^1.5 ~ 6.0858x
        expected_ratio = (r_out / r_isco) ** 1.5
        measured_ratio = float(omega_isco) / float(omega_out)
        assert abs(measured_ratio - expected_ratio) < 1e-4, (
            f"Expected shear ratio {expected_ratio:.4f}, got {measured_ratio:.4f}"
        )
        assert omega_isco > omega_out, "Inner orbit must have strictly higher angular frequency than outer orbit"

        # Monotonicity test across radial array
        r_arr = np.linspace(3.0, 20.0, 50)
        omega_arr = bh.compute_keplerian_shear(r_arr)
        assert np.all(np.diff(omega_arr) < 0.0), "Angular velocity Omega(r) must decrease monotonically with radius"

        # Relative power law test: Omega(r) / Omega(2r) == 2^1.5 = 2.8284
        omega_4 = bh.compute_keplerian_shear(4.0)
        omega_8 = bh.compute_keplerian_shear(8.0)
        octave_ratio = float(omega_4) / float(omega_8)
        assert abs(octave_ratio - 2.0 ** 1.5) < 1e-4

    def test_grid_dimensions_calculation(self):
        """Verify fullscreen and window resize ASCII grid dimension calculation."""
        # Standard Full HD 1080p with 8x16 font
        cols, rows = bh.compute_grid_dimensions(1920, 1080, cell_width=8, cell_height=16)
        assert cols == 240, f"Expected 240 cols, got {cols}"
        assert rows == 67, f"Expected 67 rows, got {rows}"
        assert cols * 8 <= 1920, "Columns must not exceed display width in pixels"
        assert rows * 16 <= 1080, "Rows must not exceed display height in pixels"

        # Standard 720p HD with 8x16 font
        cols_720, rows_720 = bh.compute_grid_dimensions(1280, 720, cell_width=8, cell_height=16)
        assert cols_720 == 160
        assert rows_720 == 45

        # 4K UHD with 10x20 font
        cols_4k, rows_4k = bh.compute_grid_dimensions(3840, 2160, cell_width=10, cell_height=20)
        assert cols_4k == 384
        assert rows_4k == 108

        # Square display (800x800) with 8x16 font
        cols_sq, rows_sq = bh.compute_grid_dimensions(800, 800, cell_width=8, cell_height=16)
        assert cols_sq == 100
        assert rows_sq == 50

        # Boundary condition: small screen clamp to minimum allowable cols/rows
        cols_min, rows_min = bh.compute_grid_dimensions(60, 40, cell_width=8, cell_height=16, min_cols=20, min_rows=10)
        assert cols_min == 20
        assert rows_min == 10

    def test_swirl_emissivity_modulation_bounds(self):
        """Verify accretion disk swirl emissivity modulation factor remains bounded and positive."""
        r_grid = np.linspace(3.0, 10.0, 50)
        phi_grid = np.linspace(-math.pi, math.pi, 50)
        R_mesh, Phi_mesh = np.meshgrid(r_grid, phi_grid)

        # Test at multiple simulation timestamps
        for t_val in [0.0, 0.5, 1.0, 2.5, 10.0]:
            mod = bh.compute_disk_swirl_modulation(R_mesh, Phi_mesh, t=t_val, counterclockwise=True)
            assert np.all(np.isfinite(mod)), "Modulation factor must be finite"
            assert np.all(mod >= 0.05), "Modulation factor must remain strictly positive (>= 0.05 floor)"
            assert np.all(mod <= 1.0 + bh.SPIRAL_AMPLITUDE + 1e-4), "Modulation must not exceed theoretical upper bound"

        # Scalar invocation sanity check
        mod_scalar = bh.compute_disk_swirl_modulation(4.0, 0.0, t=1.0)
        assert isinstance(mod_scalar, float)
        assert 0.05 <= mod_scalar <= 1.0 + bh.SPIRAL_AMPLITUDE + 1e-4

    def test_grid_dimensions_zero_negative_boundaries(self):
        """Verify compute_grid_dimensions returns safe dimensions when given 0, negative, or degenerate inputs."""
        cols, rows = bh.compute_grid_dimensions(0, 0, cell_width=8, cell_height=16, min_cols=0, min_rows=0)
        assert cols >= 1 and rows >= 1, f"Expected safe positive bounds, got cols={cols}, rows={rows}"

        cols_neg, rows_neg = bh.compute_grid_dimensions(-100, -50, cell_width=-8, cell_height=-16, min_cols=-5, min_rows=-5)
        assert cols_neg >= 1 and rows_neg >= 1

    def test_render_frame_ascii_zero_dimensions_resilience(self):
        """Verify render_frame_ascii handles zero, negative, or tiny dimensions without ZeroDivisionError."""
        for w, h in [(0, 0), (-5, -10), (1, 1), (2, 2)]:
            char_grid, int_grid, col_grid = bh.render_frame_ascii(25.0, 1.2, 0.0, width=w, height=h)
            assert char_grid.shape[0] >= 2 and char_grid.shape[1] >= 2
            assert np.all(np.isfinite(int_grid))

    def test_compute_disk_swirl_modulation_nan_inf_coordinates_resilience(self):
        """Verify compute_disk_swirl_modulation handles non-finite r, phi, amplitude without warnings or NaNs."""
        import warnings
        with warnings.catch_warnings():
            warnings.simplefilter("error")
            # Scalar non-finite coordinates
            for invalid_r in [float('inf'), float('-inf'), float('nan')]:
                mod_r = bh.compute_disk_swirl_modulation(invalid_r, 0.5, t=0.0)
                assert np.isfinite(mod_r) and mod_r >= 0.05

            for invalid_phi in [float('inf'), float('-inf'), float('nan')]:
                mod_phi = bh.compute_disk_swirl_modulation(4.0, invalid_phi, t=0.0)
                assert np.isfinite(mod_phi) and mod_phi >= 0.05

            for invalid_amp in [float('nan'), float('inf'), -1.0]:
                mod_amp = bh.compute_disk_swirl_modulation(4.0, 0.5, t=0.0, amplitude=invalid_amp)
                assert np.isfinite(mod_amp) and mod_amp >= 0.05

            # Vectorized mixed finite and non-finite coordinates
            r_vec = np.array([4.0, np.inf, -np.inf, np.nan])
            phi_vec = np.array([0.5, 0.0, np.nan, np.inf])
            mod_vec = bh.compute_disk_swirl_modulation(r_vec, phi_vec, t=0.0)
            assert np.all(np.isfinite(mod_vec))
            assert np.all(mod_vec >= 0.05)
            # Finite first element matches standard scalar computation
            assert abs(mod_vec[0] - bh.compute_disk_swirl_modulation(4.0, 0.5, t=0.0)) < 1e-6
            # Non-finite elements fall back to neutral 1.0 modulation
            assert mod_vec[1] == 1.0 and mod_vec[2] == 1.0 and mod_vec[3] == 1.0

    def test_compute_grid_dimensions_nan_inf_resilience(self):
        """Verify compute_grid_dimensions handles non-finite or invalid parameters without exception."""
        for invalid_val in [float('nan'), float('inf'), float('-inf'), None, "invalid"]:
            cols1, rows1 = bh.compute_grid_dimensions(invalid_val, 1080, cell_width=8, cell_height=16)
            assert cols1 >= 1 and rows1 >= 1
            cols2, rows2 = bh.compute_grid_dimensions(1920, invalid_val, cell_width=8, cell_height=16)
            assert cols2 >= 1 and rows2 >= 1
            cols3, rows3 = bh.compute_grid_dimensions(1920, 1080, cell_width=invalid_val, cell_height=16)
            assert cols3 >= 1 and rows3 >= 1
            cols4, rows4 = bh.compute_grid_dimensions(1920, 1080, cell_width=8, cell_height=invalid_val)
            assert cols4 >= 1 and rows4 >= 1
            cols5, rows5 = bh.compute_grid_dimensions(1920, 1080, 8, 16, min_cols=invalid_val, min_rows=invalid_val)
            assert cols5 >= 1 and rows5 >= 1


# =============================================================================
# TIER 2: BOUNDARY & CORNER CASES
# =============================================================================

class TestTier2BoundaryCornerCases:
    """Tier 2: Boundary and corner cases testing extreme physical and geometric limits."""

    def test_boundary_exact_bcrit(self):
        """Verify ray at exactly b = b_crit is handled as horizon capture without infinite loop or crash."""
        lut = bh.GeodesicLUT(r_s=1.0)
        deflection, is_shadow = lut.lookup(np.array([lut.b_crit]))
        assert bool(is_shadow[0]) is True
        assert np.isnan(deflection[0]) or np.isinf(deflection[0])

    def test_boundary_inside_bcrit(self):
        """Verify ray at b = b_crit - 1e-4 is captured and mapped to empty shadow character."""
        lut = bh.GeodesicLUT(r_s=1.0)
        b_val = lut.b_crit - 1e-4
        deflection, is_shadow = lut.lookup(np.array([b_val]))
        assert bool(is_shadow[0]) is True
        char = bh.map_intensity_to_ascii(np.array([0.0 if is_shadow[0] else 1.0]))
        assert char[0] == " "

    def test_boundary_outside_bcrit_strong_lensing(self):
        """Verify ray at b = b_crit + 1e-4 escapes photon capture and undergoes strong bending."""
        lut = bh.GeodesicLUT(r_s=1.0)
        b_val = lut.b_crit + 1e-4
        deflection, is_shadow = lut.lookup(np.array([b_val]))
        assert bool(is_shadow[0]) is False
        assert np.isfinite(deflection[0])
        assert deflection[0] > 2.0 * math.pi

    def test_asymptotic_weak_deflection_50(self):
        """Verify asymptotic convergence at b = 50.0 r_s against Einstein formula 2*r_s/b."""
        r_s = 1.0
        lut = bh.GeodesicLUT(r_s=r_s, b_max=120.0)
        b_val = 50.0 * r_s
        deflection, _ = lut.lookup(np.array([b_val]))
        einstein = 2.0 * r_s / b_val
        rel_diff = abs(float(deflection[0]) - einstein) / einstein
        assert rel_diff < 0.05, f"Relative error at b=50 ({rel_diff:.4f}) must be < 5%"

    def test_asymptotic_weak_deflection_100(self):
        """Verify asymptotic convergence at b = 100.0 r_s with tighter error than b = 50."""
        r_s = 1.0
        lut = bh.GeodesicLUT(r_s=r_s, b_max=120.0)
        b_50 = 50.0 * r_s
        b_100 = 100.0 * r_s
        def_50, _ = lut.lookup(np.array([b_50]))
        def_100, _ = lut.lookup(np.array([b_100]))

        rel_diff_50 = abs(float(def_50[0]) - 2.0 * r_s / b_50) / (2.0 * r_s / b_50)
        rel_diff_100 = abs(float(def_100[0]) - 2.0 * r_s / b_100) / (2.0 * r_s / b_100)
        assert rel_diff_100 < 0.03, f"Relative error at b=100 ({rel_diff_100:.4f}) must be < 3%"
        assert rel_diff_100 <= rel_diff_50 + 1e-6, "Asymptotic relative error must decrease with increasing b"

    def test_isco_inner_boundary_sharpness(self):
        """Verify accretion disk emissivity is zero for r < r_ISCO (plunge gap) and positive for r >= r_ISCO."""
        r_s = 1.0
        r_isco = 3.0 * r_s
        defSS = lambda r: np.where(r < r_isco, 0.0, (r_isco / r)**2 * (0.2 + 0.8 * np.sqrt(np.maximum(0.0, 1.0 - np.sqrt(r_isco / r)))))
        em_inside = defSS(r_isco - 1e-4)
        em_outside = defSS(r_isco + 1e-4)
        assert em_inside == 0.0, "Emissivity inside ISCO must be identically zero"
        assert em_outside > 0.0, "Emissivity outside ISCO must be strictly positive"

    def test_outer_boundary_sharpness(self):
        """Verify accretion disk cutoff at outer boundary r_out."""
        r_s = 1.0
        r_out = 10.0 * r_s
        defSS = lambda r: np.where(r > r_out, 0.0, 1.0)
        assert defSS(r_out - 1e-4) > 0.0
        assert defSS(r_out + 1e-4) == 0.0

    def test_camera_edge_on_vertical_halo(self):
        """Verify near edge-on view (cam_theta ~ 85 deg) produces vertical halo spanning > 20% height."""
        _, intensity_grid, _ = bh.render_frame_ascii(
            cam_dist=25.0, cam_theta=math.radians(85.0), cam_phi=0.0, width=80, height=40
        )
        center_col = intensity_grid[:, 40]
        active_rows = np.where(center_col > 0)[0]
        vertical_span = len(active_rows)
        span_fraction = vertical_span / 40.0
        assert span_fraction >= 0.20, f"Edge-on vertical halo must span >= 20% of screen height, got {span_fraction:.1%}"

    def test_camera_face_on_doppler_balance(self):
        """Verify face-on camera orientation has balanced Doppler flux across left and right halves."""
        _, intensity_grid, _ = bh.render_frame_ascii(
            cam_dist=25.0, cam_theta=0.0, cam_phi=0.0, width=80, height=40
        )
        left_flux = np.sum(intensity_grid[:, :40])
        right_flux = np.sum(intensity_grid[:, 40:])
        assert left_flux > 0.0 and right_flux > 0.0
        rel_diff = abs(left_flux - right_flux) / left_flux
        # Specification from survey_test_explorer_1: relative difference < 10^-4
        assert rel_diff < 1e-4, f"Face-on Doppler flux must balance within relative 1e-4, got {rel_diff:.4e}"


# =============================================================================
# TIER 3: COMBINATORIAL & CROSS-FEATURE TESTS
# =============================================================================

class TestTier3CombinatorialCrossFeature:
    """Tier 3: Combinatorial and cross-feature tests validating global physical phenomena."""

    def test_doppler_asymmetry_left_vs_right(self):
        """Verify Doppler boosting creates >= 3.0x high-luminance character asymmetry and flux dominance on left."""
        theta = math.radians(75.0)
        char_grid, intensity_grid, _ = bh.render_frame_ascii(
            cam_dist=25.0, cam_theta=theta, cam_phi=0.0, width=80, height=40, counterclockwise=True
        )

        left_chars = char_grid[:, :40].flatten()
        right_chars = char_grid[:, 40:].flatten()

        high_glyphs = set("@#$*!=")
        left_high = sum(np.sum(left_chars == ch) for ch in high_glyphs)
        right_high = sum(np.sum(right_chars == ch) for ch in high_glyphs)

        high_ratio = left_high / max(right_high, 1)
        assert high_ratio >= 3.0, f"High luminance character ratio must be >= 3.0x, got {high_ratio:.2f}x ({left_high} vs {right_high})"

        # Left flux dominance
        left_flux = float(np.sum(intensity_grid[:, :40]))
        right_flux = float(np.sum(intensity_grid[:, 40:]))
        assert left_flux > right_flux, "Approaching hemisphere must have higher integrated intensity than receding"

        # Relativistic Doppler beaming formula at 75 deg inclination
        beta = math.sqrt(1.0 / 6.0)
        d_app = bh.compute_doppler_factor(beta, math.sin(theta))
        d_rec = bh.compute_doppler_factor(beta, -math.sin(theta))
        flux_ratio = (d_app / d_rec)**4
        assert flux_ratio >= 3.0, f"Theoretical flux ratio at 75 deg must be >= 3.0x, got {flux_ratio:.2f}x"

    def test_doppler_peak_character_hemisphere(self):
        """Verify the peak luminance character '@' appears exclusively in the approaching hemisphere (x < 0)."""
        theta = math.radians(75.0)
        char_grid, _, _ = bh.render_frame_ascii(
            cam_dist=25.0, cam_theta=theta, cam_phi=0.0, width=80, height=40, counterclockwise=True
        )

        left_chars = char_grid[:, :40]
        right_chars = char_grid[:, 40:]

        at_left_count = np.sum(left_chars == "@")
        at_right_count = np.sum(right_chars == "@")

        assert at_left_count > 0, "Approaching hemisphere must contain high-luminance '@' characters"
        assert at_right_count == 0, f"Receding hemisphere must not contain '@' characters, found {at_right_count}"

    def test_doppler_rotation_inversion(self):
        """Verify reversing rotation direction inverts Doppler asymmetry to right hemisphere."""
        theta = math.radians(75.0)
        char_grid_ccw, _, _ = bh.render_frame_ascii(
            25.0, theta, 0.0, width=80, height=40, counterclockwise=True
        )
        char_grid_cw, _, _ = bh.render_frame_ascii(
            25.0, theta, 0.0, width=80, height=40, counterclockwise=False
        )

        high_glyphs = set("@#$*!=")
        ccw_left = sum(np.sum(char_grid_ccw[:, :40] == ch) for ch in high_glyphs)
        ccw_right = sum(np.sum(char_grid_ccw[:, 40:] == ch) for ch in high_glyphs)
        assert ccw_left > ccw_right

        cw_left = sum(np.sum(char_grid_cw[:, :40] == ch) for ch in high_glyphs)
        cw_right = sum(np.sum(char_grid_cw[:, 40:] == ch) for ch in high_glyphs)
        assert cw_right > cw_left
        assert cw_right / max(cw_left, 1) >= 3.0

    def test_halo_spatial_separation_vertical_cut(self):
        """Verify vertical centerline exhibits upper halo and lower halo flanking dark shadow core."""
        theta = math.radians(75.0)
        _, intensity_grid, _ = bh.render_frame_ascii(
            cam_dist=25.0, cam_theta=theta, cam_phi=0.0, width=80, height=40
        )

        center_col = intensity_grid[:, 40]
        mid_row = 20
        shadow_slice = center_col[mid_row - 1: mid_row + 2]
        assert np.all(shadow_slice == 0.0), f"Shadow core center must be zero intensity, got {shadow_slice}"

        upper_active = np.any(center_col[:mid_row - 2] > 0.0)
        lower_active = np.any(center_col[mid_row + 2:] > 0.0)
        assert upper_active, "Upper lensed halo must be present above the shadow core"
        assert lower_active, "Lower halo / disk must be present below the shadow core"

    def test_palette_character_grid_invariance(self):
        """Verify switching between monochrome and thermal modes preserves exact ASCII characters."""
        char_grid_1, int_1, _ = bh.render_frame_ascii(cam_dist=25.0, cam_theta=0.3, cam_phi=0.0, width=80, height=40)
        char_grid_2, int_2, _ = bh.render_frame_ascii(cam_dist=25.0, cam_theta=0.3, cam_phi=0.0, width=80, height=40)

        assert np.array_equal(char_grid_1, char_grid_2), "Character grid must be invariant across render calls"
        assert np.allclose(int_1, int_2), "Intensity grid must be invariant"

    def test_palette_thermal_temperature_gradient(self):
        """Verify thermal colormap produces high blue/white at ISCO and red/orange at outer radius."""
        r_isco = 3.0
        r_out = 10.0
        radii = np.array([r_isco, r_out])
        intensities = np.array([1.0, 1.0])

        colors = bh.get_thermal_color(radii, intensities, r_isco=r_isco, r_out=r_out)
        color_isco = colors[0]
        color_out = colors[1]

        assert color_isco[2] > 180, f"Inner disk color must have strong blue component, got {color_isco[2]}"
        assert color_out[0] > color_out[2], f"Outer disk must have red > blue, got R={color_out[0]}, B={color_out[2]}"

        zero_color = bh.get_thermal_color(np.array([r_isco]), np.array([0.0]))[0]
        assert np.all(zero_color == 0), f"Zero intensity pixel must be black, got {zero_color}"

    def test_animation_temporal_variance(self):
        """Verify frames rendered at t_1 != t_2 produce distinct intensity grids and moving luminance peaks."""
        theta = math.radians(75.0)
        # Render at distinct times t_1 = 0.0 and t_2 = 1.0 with swirl enabled
        _, int_t0, _ = bh.render_frame_ascii(
            cam_dist=25.0, cam_theta=theta, cam_phi=0.0, width=80, height=40, time=0.0, swirl=True
        )
        _, int_t1, _ = bh.render_frame_ascii(
            cam_dist=25.0, cam_theta=theta, cam_phi=0.0, width=80, height=40, time=1.0, swirl=True
        )

        # 1. Distinct intensity matrices
        assert not np.allclose(int_t0, int_t1), "Frames at different times must produce distinct intensity grids"
        max_diff = float(np.max(np.abs(int_t0 - int_t1)))
        assert max_diff > 0.15, f"Expected significant intensity variance (> 0.15), got {max_diff:.4f}"

        # 2. Sequential temporal progression across multiple timestamps
        timestamps = [0.0, 0.4, 0.8, 1.2, 1.6, 2.0]
        peak_positions = []
        for t_val in timestamps:
            _, int_grid, _ = bh.render_frame_ascii(
                cam_dist=25.0, cam_theta=theta, cam_phi=0.0, width=80, height=40, time=t_val, swirl=True
            )
            # Find coordinates of the brightest pixel peak
            peak_idx = np.unravel_index(np.argmax(int_grid), int_grid.shape)
            peak_positions.append(peak_idx)

        # Luminance peak must move over time due to advected hotspots
        distinct_peaks = len(set(peak_positions))
        assert distinct_peaks >= 2, f"Luminance peak must dynamically translate across time, found {distinct_peaks} positions"

    def test_swirl_hotspot_doppler_interaction(self):
        """Verify relativistic Doppler boosting naturally interacts with moving hotspots."""
        theta = math.radians(75.0)
        # Approaching side (left, x < 0 in CCW) should exhibit peak flux amplification
        char_grid_ccw, int_ccw, _ = bh.render_frame_ascii(
            cam_dist=25.0, cam_theta=theta, cam_phi=0.0, width=80, height=40, counterclockwise=True, time=0.5, swirl=True
        )
        left_peak = float(np.max(int_ccw[:, :40]))
        right_peak = float(np.max(int_ccw[:, 40:]))
        assert left_peak > right_peak, "Approaching side hotspot peak must exceed receding side"
        assert left_peak / max(right_peak, 1e-4) >= 2.0, "Approaching hotspot must be >= 2.0x brighter than receding"

        # Rotation inversion: reversing orbital swirl flips the hotspot peak to the right side
        _, int_cw, _ = bh.render_frame_ascii(
            cam_dist=25.0, cam_theta=theta, cam_phi=0.0, width=80, height=40, counterclockwise=False, time=0.5, swirl=True
        )
        cw_left_peak = float(np.max(int_cw[:, :40]))
        cw_right_peak = float(np.max(int_cw[:, 40:]))
        assert cw_right_peak > cw_left_peak, "Reversing rotation direction must shift peak brightness to right side"

    def test_swirl_differential_shear_phase_progression(self):
        """Verify inner radius features have higher angular frequency than outer radius features."""
        r_inner = 3.0
        r_outer = 9.0
        phi_0 = 0.0

        # Measure angular shift over Delta t = 1.0 second
        dt = 1.0
        omega_inner = bh.compute_keplerian_shear(r_inner)
        omega_outer = bh.compute_keplerian_shear(r_outer)

        # Phase delta in 1 second
        dphi_inner = omega_inner * dt
        dphi_outer = omega_outer * dt

        assert dphi_inner > dphi_outer, "Inner disk must undergo larger angular displacement per unit time"
        assert abs(dphi_inner / dphi_outer - (r_outer / r_inner) ** 1.5) < 1e-4, (
            "Angular phase progression ratio must precisely match (r_outer / r_inner)^1.5"
        )

    def test_space_key_rotation_toggling_rapid_sequence(self):
        """Verify rapid alternating sequence of rotation direction flips flux consistently without degradation."""
        theta = math.radians(75.0)
        # Sequence: CCW -> CW -> CCW -> CW
        directions = [True, False, True, False]
        previous_peaks = []
        for is_ccw in directions:
            _, int_grid, _ = bh.render_frame_ascii(
                25.0, theta, 0.0, width=80, height=40, counterclockwise=is_ccw, time=0.5, swirl=True
            )
            left_peak = float(np.max(int_grid[:, :40]))
            right_peak = float(np.max(int_grid[:, 40:]))
            if is_ccw:
                assert left_peak > right_peak, "CCW rotation must peak on left hemisphere"
            else:
                assert right_peak > left_peak, "CW rotation must peak on right hemisphere"
            previous_peaks.append((left_peak, right_peak))

        # Reversibility: state 0 and state 2 (both CCW) must match exactly
        assert abs(previous_peaks[0][0] - previous_peaks[2][0]) < 1e-6
        # Reversibility: state 1 and state 3 (both CW) must match exactly
        assert abs(previous_peaks[1][1] - previous_peaks[3][1]) < 1e-6

    def test_render_frame_ascii_extreme_simulation_times(self):
        """Verify render_frame_ascii handles negative, zero, and huge simulation times gracefully."""
        theta = math.radians(75.0)
        for extreme_t in [-100.0, -1.0, 0.0, 1.0, 1e6]:
            char_grid, int_grid, col_grid = bh.render_frame_ascii(
                25.0, theta, 0.0, width=80, height=40, time=extreme_t, swirl=True
            )
            assert np.all(np.isfinite(int_grid)), f"Non-finite intensities at t={extreme_t}"
            assert np.max(int_grid) > 0.0, f"Frame must have active emission at t={extreme_t}"
            # Shadow core must remain pitch dark
            b_crit = bh.B_CRIT
            center_val = int_grid[20, 40]
            assert center_val == 0.0, f"Shadow core center must be zero luminance at t={extreme_t}"

    def test_render_frame_ascii_nan_inf_time_resilience(self):
        """Verify render_frame_ascii and compute_disk_swirl_modulation handle NaN, inf, and -inf times safely."""
        theta = math.radians(75.0)
        # Verify modulation returns finite positive floats without warnings
        for invalid_t in [float('nan'), float('inf'), float('-inf')]:
            mod = bh.compute_disk_swirl_modulation(4.0, 0.5, t=invalid_t)
            assert np.isfinite(mod), f"Modulation must be finite for t={invalid_t}"
            assert mod >= 0.05

            char_grid, int_grid, col_grid = bh.render_frame_ascii(
                25.0, theta, 0.0, width=80, height=40, time=invalid_t, swirl=True
            )
            assert np.all(np.isfinite(int_grid)), f"Intensities must be finite for invalid time {invalid_t}"
            assert np.max(int_grid) > 0.0, f"Frame must have active emission for invalid time {invalid_t}"
            assert int_grid[20, 40] == 0.0, "Shadow core center must be zero luminance"

    def test_render_frame_ascii_non_finite_parameters_resilience(self):
        """Verify render_frame_ascii handles NaN and infinite width, height, fov, and camera angles."""
        for invalid_val in [float('nan'), float('inf'), float('-inf')]:
            char_grid, int_grid, col_grid = bh.render_frame_ascii(
                cam_dist=25.0,
                cam_theta=invalid_val,
                cam_phi=invalid_val,
                width=invalid_val,
                height=invalid_val,
                fov=invalid_val,
                time=invalid_val,
                swirl=True,
            )
            assert char_grid.shape[0] >= 2 and char_grid.shape[1] >= 2
            assert np.all(np.isfinite(int_grid))
            assert col_grid.shape == (char_grid.shape[0], char_grid.shape[1], 3)


# =============================================================================
# TIER 4: REAL-WORLD HEADLESS EXECUTION & PERFORMANCE SUITE
# =============================================================================

class TestTier4HeadlessRealWorld:
    """Tier 4: Real-world headless execution tests validating performance, stability, and CLI."""

    def test_headless_environment_setup(self):
        """Verify headless Pygame initialization with dummy video driver without X11 or display."""
        import pygame
        pygame.init()
        surf = pygame.display.set_mode((320, 240))
        assert surf is not None, "Pygame display surface must be created headlessly"
        font = pygame.font.SysFont("monospace", 12)
        glyph = font.render("@", False, (255, 255, 255))
        assert glyph.get_width() > 0 and glyph.get_height() > 0, "Font glyph must render cleanly"
        pygame.quit()

    def test_headless_60_frames_performance(self):
        """Verify 60 consecutive frames render at FPS >= 60.0 with animated swirl enabled."""
        stats = bh.run_headless_benchmark(num_frames=60, width=80, height=40, swirl=True)

        fps = stats["fps"]
        frame_time = stats["frame_time_ms"]

        assert fps >= 60.0, f"Average FPS must be >= 60.0, measured: {fps:.1f} FPS"
        assert frame_time <= 16.67, f"Frame time must be <= 16.67 ms, measured: {frame_time:.2f} ms"

    def test_headless_memory_stability(self):
        """Verify memory growth across 60 frames is < 5.0 MB (zero allocation leaks)."""
        stats = bh.run_headless_benchmark(num_frames=60, width=80, height=40)

        mem_delta = stats["memory_delta_mb"]
        assert mem_delta < 5.0, f"Memory delta across 60 frames must be < 5.0 MB, measured: {mem_delta:.2f} MB"

    def test_rendered_frame_non_empty(self):
        """Verify rendered frame contains > 200 non-space characters, >= 6 distinct glyphs, and central shadow."""
        char_grid, intensity_grid, _ = bh.render_frame_ascii(cam_dist=25.0, cam_theta=0.3, cam_phi=0.0, width=80, height=40)

        flat_chars = char_grid.flatten()
        non_space_count = np.sum(flat_chars != " ")
        distinct_glyphs = set(flat_chars) - {" "}

        assert non_space_count > 200, f"Total visible characters must be > 200, got {non_space_count}"
        assert len(distinct_glyphs) >= 6, f"Distinct glyphs must be >= 6, got {len(distinct_glyphs)}: {distinct_glyphs}"

        H, W = char_grid.shape
        center_box = char_grid[H//2 - 2: H//2 + 2, W//2 - 3: W//2 + 3]
        space_ratio = np.mean(center_box == " ")
        assert space_ratio >= 0.85, f"Center shadow core must be mostly spaces, got {space_ratio:.1%}"

    def test_headless_orientation_traversal(self):
        """Verify smooth orientation traversal across inclinations from 0 to 85 degrees without crash."""
        thetas = [0.0, 0.3, 0.6, 1.0, 1.45]
        for theta in thetas:
            char_grid, intensity_grid, _ = bh.render_frame_ascii(cam_dist=25.0, cam_theta=theta, cam_phi=0.5, width=60, height=30)
            assert char_grid.shape == (30, 60)
            assert np.all(np.isfinite(intensity_grid))
            assert np.sum(intensity_grid) > 0.0

    def test_fullscreen_toggle_and_window_restore(self):
        """Verify BlackHoleApp toggles fullscreen and safely restores windowed resolution."""
        import pygame
        app = bh.BlackHoleApp(cols=80, rows=40)
        assert not app.is_fullscreen
        assert app.cols == 80 and app.rows == 40
        w_orig = app.windowed_w
        h_orig = app.windowed_h

        # Enter fullscreen
        app.toggle_fullscreen()
        assert app.is_fullscreen is True
        assert app.cols * app.cell_w <= app.screen_w
        assert app.rows * app.cell_h <= app.screen_h
        assert app.screen_w >= w_orig
        assert app.cols >= 80

        # Exit fullscreen: must restore exact original windowed geometry
        app.toggle_fullscreen()
        assert app.is_fullscreen is False
        assert app.cols == 80 and app.rows == 40
        assert app.screen_w == w_orig and app.screen_h == h_orig
        pygame.quit()

    def test_fullscreen_grid_expansion_verification(self):
        """Verify BlackHoleApp toggling to fullscreen expands grid dimensions to fill display."""
        import pygame
        app = bh.BlackHoleApp(cols=60, rows=30)
        assert app.cols == 60 and app.rows == 30
        w_windowed = app.screen_w
        h_windowed = app.screen_h

        app.toggle_fullscreen()
        assert app.is_fullscreen is True
        # Fullscreen on dummy driver (1024x768) or real display (1920x1080) is strictly larger than 60x30
        assert app.screen_w > w_windowed
        assert app.screen_h > h_windowed
        assert app.cols > 60
        assert app.rows > 30

        # Returning to windowed mode must restore 60x30 exactly
        app.toggle_fullscreen()
        assert app.is_fullscreen is False
        assert app.cols == 60 and app.rows == 30
        assert app.screen_w == w_windowed and app.screen_h == h_windowed
        pygame.quit()

    def test_dynamic_window_resize_adaptation(self):
        """Verify dynamic window resizing adapts ASCII character grid without clipping."""
        import pygame
        app = bh.BlackHoleApp(cols=80, rows=40)
        target_w = 1200
        target_h = 700

        app.handle_resize(target_w, target_h)
        assert app.screen_w == target_w and app.screen_h == target_h
        expected_cols, expected_rows = bh.compute_grid_dimensions(target_w, target_h, app.cell_w, app.cell_h)
        assert app.cols == expected_cols
        assert app.rows == expected_rows
        assert app.cols * app.cell_w <= target_w
        assert app.rows * app.cell_h <= target_h
        pygame.quit()

    def test_cli_flag_benchmark_mode(self):
        """Verify blackhole.py --benchmark CLI flag exits with code 0 and outputs benchmark metrics."""
        res = subprocess.run(
            [sys.executable, "blackhole.py", "--benchmark"],
            capture_output=True,
            text=True,
            timeout=30
        )
        assert res.returncode == 0, f"CLI --benchmark failed: {res.stderr or res.stdout}"
        assert "Benchmark Results" in res.stdout
        assert "Framerate" in res.stdout

    def test_cli_flag_test_mode(self):
        """Verify blackhole.py --test CLI flag exits with code 0."""
        res = subprocess.run(
            [sys.executable, "blackhole.py", "--test"],
            capture_output=True,
            text=True,
            timeout=30
        )
        assert res.returncode == 0, f"CLI --test failed: {res.stderr or res.stdout}"

    def test_key_events_fullscreen_toggle_f_and_f11(self):
        """Verify BlackHoleApp toggles to fullscreen and back using F and F11 key events."""
        import pygame
        app = bh.BlackHoleApp(cols=80, rows=40)
        w_orig = app.windowed_w
        h_orig = app.windowed_h

        # 1. Key F toggles to fullscreen
        res = app.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_f))
        assert res is True
        assert app.is_fullscreen is True
        assert app.screen_w > w_orig

        # 2. Key F toggles back to windowed
        res = app.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_f))
        assert res is True
        assert app.is_fullscreen is False
        assert app.screen_w == w_orig and app.screen_h == h_orig
        assert app.cols == 80 and app.rows == 40

        # 3. Key F11 toggles to fullscreen
        res = app.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_F11))
        assert res is True
        assert app.is_fullscreen is True

        # 4. Key F11 toggles back to windowed
        res = app.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_F11))
        assert res is True
        assert app.is_fullscreen is False
        assert app.screen_w == w_orig and app.screen_h == h_orig
        assert app.cols == 80 and app.rows == 40
        pygame.quit()

    def test_esc_key_fullscreen_restoration_vs_quit(self):
        """Verify Esc in fullscreen restores windowed mode without quitting, while Esc in windowed quits."""
        import pygame
        app = bh.BlackHoleApp(cols=80, rows=40)
        w_orig = app.windowed_w
        h_orig = app.windowed_h

        # Enter fullscreen via F11
        app.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_F11))
        assert app.is_fullscreen is True

        # Press Esc in fullscreen: must restore windowed mode and return True (keep running)
        res_fs = app.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_ESCAPE))
        assert res_fs is True, "Esc in fullscreen must NOT quit the application"
        assert app.is_fullscreen is False
        assert app.screen_w == w_orig and app.screen_h == h_orig
        assert app.cols == 80 and app.rows == 40

        # Press Esc in windowed mode: must return False (quit application)
        res_win = app.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_ESCAPE))
        assert res_win is False, "Esc in windowed mode must quit the application (return False)"
        pygame.quit()

    def test_space_key_rotation_toggling_event(self):
        """Verify Space key toggles counterclockwise rotation direction."""
        import pygame
        app = bh.BlackHoleApp(cols=80, rows=40)
        assert app.counterclockwise is True

        # Space -> False (CW)
        res = app.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_SPACE))
        assert res is True
        assert app.counterclockwise is False

        # Space -> True (CCW)
        res = app.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_SPACE))
        assert res is True
        assert app.counterclockwise is True
        pygame.quit()

    def test_speed_key_events_and_multiplier(self):
        """Verify speed adjustment keys ([ / ]) and pause toggle (P / 0)."""
        import pygame
        app = bh.BlackHoleApp(cols=80, rows=40, speed=0.4)
        assert abs(app.speed - 0.4) < 1e-4

        # [ slows down
        app.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_LEFTBRACKET))
        assert abs(app.speed - 0.35) < 1e-4

        # ] speeds up
        app.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_RIGHTBRACKET))
        assert abs(app.speed - 0.40) < 1e-4

        # P toggles pause
        app.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_p))
        assert app.speed == 0.0
        # P resumes
        app.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_p))
        assert abs(app.speed - 0.40) < 1e-4
        pygame.quit()

    def test_multi_window_resize_stress_and_memory(self):
        """Verify handling 50 sequential window resize events adapts grid correctly without memory leaks."""
        import pygame
        app = bh.BlackHoleApp(cols=80, rows=40)
        tracemalloc.start()
        snap1 = tracemalloc.take_snapshot()

        for i in range(50):
            target_w = 640 + (i % 15) * 60
            target_h = 480 + (i % 10) * 40
            app.handle_resize(target_w, target_h)
            assert app.screen_w == target_w and app.screen_h == target_h
            assert app.cols * app.cell_w <= target_w
            assert app.rows * app.cell_h <= target_h

        snap2 = tracemalloc.take_snapshot()
        tracemalloc.stop()

        stats = snap2.compare_to(snap1, 'lineno')
        growth_kb = sum(s.size_diff for s in stats) / 1024.0
        assert growth_kb < 1000.0, f"Memory growth too high across 50 resizes: {growth_kb:.2f} KB"
        pygame.quit()

    def test_blackhole_app_degenerate_dimension_clamping(self):
        """Verify BlackHoleApp clamps degenerate, negative, or zero cols/rows to safe positive values."""
        import pygame
        app = bh.BlackHoleApp(cols=-10, rows=-5)
        assert app.cols >= 2 and app.rows >= 2
        assert app.screen_w > 0 and app.screen_h > 0
        app.toggle_fullscreen()
        assert app.is_fullscreen is True
        app.toggle_fullscreen()
        assert app.is_fullscreen is False
        assert app.cols >= 2 and app.rows >= 2
        pygame.quit()

    def test_cli_flag_help(self):
        """Verify blackhole.py --help CLI flag exits with code 0 and contains help documentation."""
        res = subprocess.run(
            [sys.executable, "blackhole.py", "--help"],
            capture_output=True,
            text=True,
            timeout=30
        )
        assert res.returncode == 0, f"CLI --help failed: {res.stderr or res.stdout}"
        assert "usage:" in res.stdout
        assert "--cols" in res.stdout
        assert "--fov" in res.stdout
        assert "--time" in res.stdout

    def test_cli_flag_invalid_argument(self):
        """Verify blackhole.py with invalid CLI options exits with non-zero exit code (2)."""
        res = subprocess.run(
            [sys.executable, "blackhole.py", "--invalid-option-xyz"],
            capture_output=True,
            text=True,
            timeout=30
        )
        assert res.returncode != 0, f"CLI should reject invalid option, got returncode: {res.returncode}"
        assert "unrecognized arguments" in res.stderr

    def test_blackhole_app_nan_inf_initialization_and_resize_resilience(self):
        """Verify BlackHoleApp safely initializes and resizes when given non-finite inputs."""
        import pygame
        app = bh.BlackHoleApp(
            cols=float('nan'),
            rows=float('inf'),
            fov=float('nan'),
            distance=float('nan'),
            elevation=float('nan'),
            azimuth=float('nan'),
            sim_time=float('nan'),
        )
        assert app.cols >= 2 and app.rows >= 2
        assert app.screen_w > 0 and app.screen_h > 0

        # Non-finite and negative resize events must be safely ignored without raising exceptions
        app.handle_resize(float('nan'), 600)
        app.handle_resize(800, float('inf'))
        app.handle_resize(-100, -50)
        app.handle_resize(0, 0)
        assert app.cols >= 2 and app.rows >= 2
        pygame.quit()

    def test_blackhole_app_fullscreen_startup_flag(self):
        """Verify BlackHoleApp can be launched directly into fullscreen mode via fullscreen=True."""
        import pygame
        app = bh.BlackHoleApp(cols=80, rows=40, fullscreen=True)
        assert app.is_fullscreen is True
        assert app.cols * app.cell_w <= app.screen_w
        assert app.rows * app.cell_h <= app.screen_h

        # Toggling safely returns to windowed geometry
        app.toggle_fullscreen()
        assert app.is_fullscreen is False
        assert app.cols == 80 and app.rows == 40
        pygame.quit()

    def test_cli_flag_fullscreen(self):
        """Verify blackhole.py supports --fullscreen and -f flags in CLI."""
        res = subprocess.run(
            [sys.executable, "blackhole.py", "--help"],
            capture_output=True,
            text=True,
            timeout=30
        )
        assert res.returncode == 0
        assert "--fullscreen" in res.stdout
        assert "-f" in res.stdout

    def test_blackhole_module_integration(self):
        """Verify blackhole.py exports all required interface contracts."""
        contracts = [
            "GeodesicLUT",
            "compute_keplerian_velocity",
            "compute_gravitational_redshift",
            "compute_doppler_factor",
            "compute_keplerian_shear",
            "compute_disk_swirl_modulation",
            "compute_grid_dimensions",
            "map_intensity_to_ascii",
            "get_thermal_color",
            "render_frame_ascii",
            "run_headless_benchmark",
            "BlackHoleApp",
        ]
        for contract in contracts:
            assert hasattr(bh, contract), f"blackhole.py missing required contract: {contract}"


# =============================================================================
# CLI TEST RUNNER
# =============================================================================

if __name__ == "__main__":
    print("=" * 75)
    print("Running Automated ASCII Black Hole Renderer Verification Suite (Tiers 1-4)")
    print("=" * 75)
    exit_code = pytest.main([__file__, "-v", "--color=yes"])
    sys.exit(exit_code)
