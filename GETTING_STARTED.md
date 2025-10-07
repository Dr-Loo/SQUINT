# Getting Started

SQUINT is a tiny, “triple-aware” compiler that bridges **quantum control**, **semantic fields (Φ)**, and **topological defects (D)**. It parses a simple `.squint` language, validates **overlays** (physical constraints), and emits **QUA-like** control text plus timelines and optional simulation data.

## Prerequisites

- **Python 3.10+**
- Optional (for visualization & tests):
  ```bash
  pip install numpy matplotlib
  ```

## Repository layout

```
SQUINT/
  SQUINT.py                      # compiler & CLI
  SQUINT_FloquetVisualizer.py    # animation & plots (optional)
  examples/
    basic.squint
    floquet.squint
    semantic.squint
  tests/
    run_tests.py
    test1_CalibratedEPR.squint
    test2_TransportEcho.squint
    test3_BadOverlay.squint
  web/
    index.html docs.html demo.html
  README.md
  GETTING_STARTED.md   ← (this file)
  requirements.txt     # optional (numpy, matplotlib)
```

---

## 1) Compile your first program

Try the **Calibrated EPR** example:

```bash
# from repo root
python SQUINT.py examples/basic.squint --strict-overlays --log --simulate
```

Outputs (next to the input file):

- `basic.qua.txt` – QUA-like text (with `wait(...)` inserted by overlays)
- `basic.log.json` – parse events + **timeline** (for tooling/visuals)
- `basic.sim.json` / `basic.sim.txt` – semantic/defect toy simulation

### Minimal `.squint` example

```squint
workspace Chip {
  qubits q[4];
  lattice L(2,2) attach q;
  semantic_field Phi : scalar on L;
  defect_field D     : defects on L { kinetics = "overdamped"; };
}

kernel CalibratedEPR on Chip {
  initialize Phi = constant(0.4);
  nucleate D at {(0,0),(1,1)}; 
  evolve D with rule braid_exchange(rate=0.7, conserve_Qtop=true);

  ctrl rx q[0] angle = π/2 with overlay { coherence_len >= 80ns };
  ctrl cz q[0], q[1] with overlay { coherence_len >= 120ns, path_len <= 2 };

  quench δQ_top = inject(D, amount=0.02);
  observe T_eff into Te with corrections { defects=D, field=Phi };
  hysteresis_trace(D, window=3);

  measure q[0] -> m0;
  measure q[1] -> m1;
  return { Te, corr = m0 ⊕ m1 };
}
```

---

## 2) Add Floquet driving (optional)

SQUINT can expand a single `ctrl` into a **Floquet cycle train**. Add these overlay keys:

```squint
ctrl cz q[0], q[1] with overlay {
  coherence_len >= 120ns,
  path_len <= 2,
  floquet_period = 50ns,
  cycles = 8,
  duty = 0.4,
  phase_step = 12deg
};
```

Re-compile; the QUA-like output will include a per-cycle expansion and the timeline will contain `@floquet` entries.

---

## 3) Visualize the field & observables

```bash
# after compiling with --log (and optionally --simulate)
python SQUINT_FloquetVisualizer.py examples/basic
# or pass explicit files:
# python SQUINT_FloquetVisualizer.py examples/basic.log.json examples/basic.sim.json
```

The visualizer shows:

- Φ field “breathing” (with optional Floquet modulation)
- Defect markers
- Traces: \(T_{	ext{eff}}\), phantom heat proxy, hysteresis/defect density

> Tip: If the Φ panel looks flat, ensure you compiled with `--log`, and consider using a Floquet overlay so the visualizer detects cycles.

---

## 4) Run the test suite

```bash
python tests/run_tests.py
```

What it checks:

- **T1** Calibrated EPR: compiles, logs, simulates under strict overlays  
- **T2** Transport Echo: overlay validation & path length enforcement  
- **T3** Bad Overlay: intentionally violates `path_len ≤ 0` → strict mode fails

---

## 5) CLI reference

```bash
python SQUINT.py [file.squint] [--out PATH] [--log] [--simulate] [--strict-overlays]
```

- `--out PATH` – choose output file for QUA-like text  
- `--log` – write `*.log.json` (events + timeline)  
- `--simulate` – produce `*.sim.json` and a human summary `*.sim.txt`  
- `--strict-overlays` – make overlay failures hard errors (recommended)

**Supported overlays (v0.1):**

- `coherence_len ≥ Nns` → inserts `wait(N)` before the op  
- `path_len ≤ k` → Manhattan distance between two qubits must be ≤ k  
- `damping = η(Φ=Phi)` / `eta(Phi=Phi)` → field must exist  
- `braid = D` → defect handle must exist  
- **Floquet:** `floquet_period = Nns`, `cycles = int`, `duty = 0..1`, `phase_step = deg`  
- Recognized (not enforced yet): `span`, `coherence_budget`

---

## 6) Troubleshooting

- **`Parse error: ...`**  
  Check semicolons `;` and that the file has one `workspace {…}` and one `kernel … on Workspace {…}`.

- **`Overlay unsatisfied ...` (strict mode)**  
  The timeline won’t emit; fix the constraint (e.g., increase `path_len` or adjust qubit pair).

- **Windows path quirks**  
  Use quotes for paths with spaces:  
  `python SQUINT.py "C:\path with spaces\program.squint" --log`

- **Visualizer shows a flat Φ**  
  Compile with `--log`; add a Floquet overlay, or increase animation amplitude (see comments in `SQUINT_FloquetVisualizer.py`).

---

## 7) Next steps (optional)

- Wire the **web demo** in `web/` to a small backend endpoint that runs `SQUINT.py` and returns `{ qua_text, timeline, diagnostics[] }`.  
- Export a runnable QUA (OPX) stub.  
- Enforce `coherence_budget` and add routing cost hints.

---

**That’s it.** You can now: write `.squint` → compile → inspect QUA-like output → visualize → test.
