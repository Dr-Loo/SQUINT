# Examples

This page gives you **copy‑paste** examples for SQUINT v0.1.  
Each example includes: a `.squint` snippet, how to run it, and what to expect.

> Tip: run with `--strict-overlays --log` for the best diagnostics and to enable the visualizer.

---

## 1) Basic — Calibrated EPR

**File:** `examples/basic.squint`

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

**Run**
```bash
python SQUINT.py examples/basic.squint --strict-overlays --log --simulate
```

**Expect**
- `basic.qua.txt`: `wait(80)` then `rx`, `wait(120)` then `cz`
- `basic.log.json`: overlay messages for `coherence_len` and `path_len`
- `basic.sim.*`: one (T_eff) sample and a short hysteresis trace

---

## 2) Floquet CZ — cycle expansion

**File:** `examples/floquet.squint`

```squint
workspace Q {
  qubits q[4];
  lattice L(2,2) attach q;
  semantic_field Phi : scalar on L;
  defect_field D     : defects on L { kinetics = "overdamped"; };
}

kernel FloquetCZ on Q {
  initialize Phi = constant(0.25);
  nucleate D at {(0,0)};

  // Floquet schedule: 8 cycles, 40% duty, 50 ns period
  ctrl cz q[0], q[1] with overlay {
    coherence_len >= 120ns,
    path_len <= 2,
    floquet_period = 50ns,
    cycles = 8,
    duty = 0.4,
    phase_step = 12deg
  };

  observe T_eff into Te;
  measure q[0], q[1] -> m0, m1;
  return { Te, parity = m0 ⊕ m1 };
}
```

**Run**
```bash
python SQUINT.py examples/floquet.squint --strict-overlays --log
python SQUINT_FloquetVisualizer.py examples/floquet
```

**Expect**
- QUA-like shows a `# floquet:` line and **8 gate emissions** with per-cycle `wait(...)`
- Timeline in `.log.json` contains entries like `{"op":"cz@floquet","cycle":1,...}`

---

## 3) Transport Echo — semantic transport & damping

**File:** `examples/semantic.squint`

```squint
workspace Q {
  qubits q[6];
  lattice L(3,2) attach q;
  semantic_field Phi : scalar on L;
  semantic_field S   : tensor[2] on L;
  defect_field D     : defects on L { kinetics = "overdamped"; };
}

kernel TransportEcho(iters n=3) on Q {
  initialize Phi = gaussian(center=(1,0), σ=0.5, amp=0.8);
  initialize S   = curl(grad(Phi)) ⊗ eye(2);
  nucleate D at {(0,0)}; pin D at anchors = {(2,1)};

  transport J_sem = div(Phi * grad(S));

  // Semantic damping links the ctrl to field Phi
  ctrl cx q[2], q[3] with overlay { coherence_len >= 140ns, damping=η(Φ=Phi) };
  ctrl cx q[3], q[4] with overlay { path_len <= 2 };

  relax S (rate = γ(Φ=Phi, D=D));
  observe T_eff into Te;
  return { Te };
}
```

**Run**
```bash
python SQUINT.py examples/semantic.squint --strict-overlays --log
```

**Expect**
- Overlay diagnostics for `damping=η(Φ=Phi)` and `path_len`
- QUA-like with inserted `wait(140)`
- `semantic` and `braid` ops emitted as structured comments (for host integration)

---

## 4) Bad Overlay — path length violation (expected failure)

**File:** `tests/test3_BadOverlay.squint`

```squint
workspace Chip {
  qubits q[4];
  lattice L(2,2) attach q;
  semantic_field Phi : scalar on L;
  defect_field D     : defects on L { kinetics = "overdamped"; };
}

kernel BadOverlay on Chip {
  initialize Phi = constant(0.1);

  // q[0] (0,0) to q[3] (1,1) → Manhattan distance = 2
  ctrl cz q[0], q[3] with overlay { coherence_len >= 50ns, path_len <= 0, braid = D, damping = η(Φ=Phi) };

  measure q[0] -> m0;
  return { m0 };
}
```

**Run (should fail in strict mode)**
```bash
python SQUINT.py tests/test3_BadOverlay.squint --strict-overlays
```

**Expect**
- Error: `path_len ≤ 0 violated (distance=2)`  
- No QUA output emitted (fail‑fast)

---

## 5) Guards & “unless” (compiles to a comment)

**Pattern**
```squint
ctrl rx q[0] angle = π/4 with overlay { coherence_len >= 40ns } unless m0 == 1;
```

**Note**: Guards are parsed and preserved in the IR but, in v0.1, only surfaced as comments in the QUA-like text. They’re intended for host scheduling/synthesis layers.

---

## 6) Reading the timeline

After compiling with `--log`, inspect `*.log.json`:

```json
{
  "timeline": [
    { "line": 6, "t": 0,  "op": "wait", "ns": 80 },
    { "line": 6, "t": 80, "op": "rx", "targets": ["q[0]"] },
    { "line": 7, "t": 80, "op": "wait", "ns": 120 },
    { "line": 7, "t": 200, "op": "cz", "targets": ["q[0]", "q[1]"] }
  ]
}
```

**Meaning**
- `t` is an accumulated time cursor (ns) in this pseudo-schedule
- `@floquet` ops include a `cycle` field and a following `wait` that fills the OFF window

---

## 7) Visualizer quick recipe

```bash
# Compile with log and (optionally) simulate
python SQUINT.py examples/floquet.squint --strict-overlays --log --simulate

# Animate Φ + plots
python SQUINT_FloquetVisualizer.py examples/floquet
```

**Tips**
- If Φ looks flat, ensure `.log.json` exists and try a Floquet overlay.
- In `SQUINT_FloquetVisualizer.py`, you can tweak modulation amplitude and `frames`.

---

## 8) Template to start a new program

```squint
workspace MyChip {
  qubits q[8];
  lattice L(4,2) attach q;
  semantic_field Phi : scalar on L;
  defect_field D     : defects on L { kinetics = "overdamped"; };
}

kernel MyKernel on MyChip {
  initialize Phi = constant(0.3);
  nucleate D at {(0,0)};
  evolve D with rule braid_exchange(rate=0.5);

  ctrl h  q[0];
  ctrl cx q[0], q[1] with overlay { coherence_len >= 100ns, path_len <= 2 };

  observe T_eff into Te;
  measure q[0], q[1] -> m0, m1;
  return { Te, parity = m0 ⊕ m1 };
}
```

**Run**
```bash
python SQUINT.py examples/myprog.squint --strict-overlays --log
```

---

## 9) CLI recap

```bash
python SQUINT.py [file.squint] [--out PATH] [--log] [--simulate] [--strict-overlays]
```

**Overlays (v0.1):**  
`coherence_len ≥ Nns`, `path_len ≤ k`, `damping = η(Φ=Phi)`, `braid = D`,  
Floquet: `floquet_period = Nns`, `cycles = int`, `duty = 0..1`, `phase_step = deg`.

---

That’s it—copy any of these into your repo’s `examples/` folder and run them verbatim.
