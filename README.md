# ASCII Black Hole: Real-Time Relativistic Schwarzschild Renderer

[![Python 3.8+](https://img.shields.io/badge/python-3.8+-blue.svg)](https://www.python.org/)
[![Tests](https://img.shields.io/badge/tests-63%20passed-brightgreen.svg)]()
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

A real-time, interactive ASCII black hole renderer written in Python and Pygame. It captures the iconic *Interstellar* / Jean-Pierre Luminet silhouette—central black hole shadow, gravitational lensing with double-lensed rear accretion disk halos, Keplerian differential shear, and relativistic Doppler beaming—running at **300+ FPS** in pure Python using general relativity mathematical shortcuts.

Inspired by [Andy Sloane's Donut Math](https://www.a1k0n.net/2011/07/20/donut-math.html) and [Tai Le's Spinning Donut](donut.html).

```text
                           .-'""*#$@*""'-.
                        .-'               '-.
                       /     . - ~ - .       \
        @@@@####****= :     /         \       : -;;;;====****
       @@@@####****== |    (  SHADOW   )      | -;;;====****
        @@@@####****= :     \         /       : -;;;;====****
                       \     ` - ~ - '       /
                        '-.               .-'
                           '-._______.-'
```

---

## Features

- **General Relativity "Cheats" (1D Geodesic LUT)**: Exploits spherical symmetry in Schwarzschild spacetime by precomputing deflection angles $\Delta \phi(b)$ into a 1D radial look-up table, reducing curved ray-tracing from numerical differential equation integration to an instant $O(1)$ table lookup per pixel.
- **Accurate Shadow Boundary**: Correctly culls rays inside the critical impact parameter $b_{\text{crit}} = \frac{3\sqrt{3}}{2} r_s \approx 2.598 r_s$ (the photon sphere capture threshold).
- **Warped Accretion Disk**: Analytically solves ray-plane intersections to render both the direct front disk and the gravitationally lensed rear disk curled over the top and under the bottom of the shadow.
- **Animated Keplerian Swirl**: Gas differentially rotates according to Kepler's third law in curved spacetime:
  $$\Omega(r) \propto r^{-3/2}$$
  Inner gas near $r_{\text{ISCO}} = 3 r_s$ orbits over $6\times$ faster than the outer rim at $r = 10 r_s$, carrying multi-arm spiral density waves ($m=1, 2, 3, 5$) and turbulent plasma hotspots.
- **Relativistic Doppler Beaming**: Relativistic orbital velocities ($\sim 0.41c$) boost approaching plasma by $g^4$, causing the left side to surge into brilliant `@`, `#`, and `$` characters while the receding right side dims to faint red embers.
- **True Fullscreen & Responsive Resizing**: Press `F` or `F11` to toggle borderless fullscreen; the monospace character grid automatically recalculates to fill any display resolution without distortion.
- **Live Speed Controls**: Fine-tune the swirl speed dynamically on the fly (`[` and `]`).
- **Dual Display Modes**: Toggle between classic monochrome ASCII and glowing Planckian thermal heat colors with `C`.

---

## Mathematical Guide

For a complete first-principles walkthrough starting from **Pythagoras' Theorem** ($a^2 + b^2 = c^2$) and building step-by-step through spherical coordinates, 4D Minkowski spacetime, gravitational time dilation, the exact Schwarzschild metric, and null geodesics ($ds^2 = 0$), see:

👉 **[blackhole.md](blackhole.md)** — *The Complete Mathematical Guide*

---

## Installation & Quick Start

### 1. Clone the repository
```bash
git clone https://github.com/Officialletai/ASCII-Blackhole.git
cd ASCII-Blackhole
```

### 2. Install dependencies
```bash
pip install -r requirements.txt
```

### 3. Run the interactive renderer
```bash
# Standard windowed mode
python blackhole.py

# Launch directly in fullscreen
python blackhole.py --fullscreen

# Custom animation speed (e.g. 0.35x)
python blackhole.py --speed 0.35
```

---

## Interactive Controls

| Input | Action |
| :--- | :--- |
| **`[` / `,`** | Slow down animation speed |
| **`]` / `.`** | Speed up animation speed |
| **`P` / `0`** | Pause / unpause swirl animation |
| **`F` / `F11`** | Toggle True Fullscreen on / off |
| **`Space`** | Reverse Keplerian accretion swirl direction |
| **`C`** | Toggle monochrome ASCII (`.,-~:;=!*#$@`) vs thermal heat colors |
| **Mouse Drag** | Interactive 3D camera orbit (inclination & azimuth) |
| **Scroll Wheel** / `+` / `-` | Zoom camera in and out |
| **`R`** | Reset camera view |
| **`H` / `Tab`** | Toggle HUD telemetry overlay |
| **`Esc`** | Exit fullscreen (or quit if already windowed) |

---

## Verification & Testing

The repository includes a comprehensive 4-tier automated test suite covering analytical constants, boundary conditions, cross-feature invariants, and headless execution:

```bash
# Run all 63 unit and integration tests
python test_blackhole.py

# Run built-in self-tests
python blackhole.py --test

# Run headless performance benchmark
python blackhole.py --benchmark
```

---

## Project Structure

```text
├── blackhole.py        # Core real-time ASCII engine and Pygame application
├── blackhole.md        # Comprehensive first-principles mathematical guide
├── test_blackhole.py   # 4-tier automated test suite (63 tests)
├── donut.html          # Original inspiration article by Tai Le
├── requirements.txt    # Python dependencies (pygame, numpy, pytest)
└── README.md           # Project overview and instructions
```

---

## License

This project is licensed under the MIT License - see the LICENSE file for details.
