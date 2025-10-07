# SQUINT v0.1 — API Reference

This document defines the **interfaces** exposed by SQUINT v0.1: the CLI, language grammar, overlays, IR objects, logs/timeline, and simulator outputs. It is **stable for v0.1** and may change in v0.2.

---

## 0. Versioning

- Compiler: `SQUINT.py` (v0.1)
- Visualizer: `SQUINT_FloquetVisualizer.py` (optional tool, not part of core API)
- Semantic version: breaking changes will bump minor (v0.2).

---

## 1. CLI

```
python SQUINT.py [FILE.squint] [--out PATH] [--log] [--simulate] [--strict-overlays]
```

**Arguments**
- `FILE.squint` (optional): path to a SQUINT source file. If omitted, defaults to `CalibratedEPR.squint` (or exits with an error if missing).
- `--out PATH`: write QUA-like output to `PATH` instead of `FILE.qua.txt`.
- `--log`: emit `FILE.log.json` (parse events + **timeline**).
- `--simulate`: run toy semantic/defect simulator, emit `FILE.sim.json` and human-readable `FILE.sim.txt`.
- `--strict-overlays`: treat overlay violations as hard errors (non-zero exit).

**Exit codes**
- `0` success
- `1` parse error
- `2` overlay error (strict mode)
- `3` IO error / missing file

> Note: Exact integers may differ in v0.1 reference implementation; treat any nonzero as failure and inspect stdout/stderr text for diagnostics.

---

## 2. Language (EBNF-lite)

```
program        := workspace_block kernel_block

workspace_block:= "workspace" IDENT "{" ws_stmt* "}"
ws_stmt        := qubits_stmt | lattice_stmt | sfield_stmt | dfield_stmt
qubits_stmt    := "qubits" IDENT "[" INT "]" ";"
lattice_stmt   := "lattice" IDENT "(" INT "," INT ")" "attach" IDENT ";"
sfield_stmt    := "semantic_field" IDENT ":" ( "scalar" | "vector" | "tensor[" INT "]" ) "on" IDENT ";"
dfield_stmt    := "defect_field"   IDENT ":" "defects" "on" IDENT "{" .*? "}" ";"

kernel_block   := "kernel" IDENT ["(" .*? ")"] "on" IDENT "{" kernel_stmt* "}"
kernel_stmt    := ctrl_stmt | measure_stmt | sem_stmt | defect_stmt | return_stmt | hyst_stmt | relax_stmt | transport_stmt

ctrl_stmt      := "ctrl" GATE qtargets [angle_clause] [overlay_clause] [guard_clause] ";"
qtargets       := QREF ["," QREF]
QREF           := IDENT "[" INT "]" | IDENT
GATE           := IDENT            // v0.1: x, h, rx, cx, cz (others emitted as comments)

angle_clause   := "angle" "=" EXPR
overlay_clause := "with" "overlay" "{" overlay_kv ("," overlay_kv)* "}"
overlay_kv     := IDENT (("≥"|"≤"|"=="|"=") VALUE)?   // ASCII >= <= normalized
guard_clause   := "unless" EXPR

measure_stmt   := "measure" QREF ["," QREF] "->" IDENT ["," IDENT] ";"

sem_stmt       := init_stmt | observe_stmt | relax_stmt | transport_stmt | ( "return" "{" .*? "}" ";" )
init_stmt      := "initialize" IDENT "=" EXPR ";"
observe_stmt   := "observe" IDENT ["into" IDENT] ["with" "corrections" "{" kvpairs "}"] ";"
transport_stmt := "transport" IDENT "=" EXPR ";"

defect_stmt    := ( "nucleate" | "pin" | "anneal" | "evolve" ) .*? ";"
hyst_stmt      := "hysteresis_trace" "(" IDENT ["," "window" "=" INT ] ")" ";"

relax_stmt     := "relax" IDENT "(" "rate" "=" EXPR ")" ";"

return_stmt    := "return" "{" .*? "}" ";"

// Comments
comment        := "//" to end-of-line
```

**Whitespace & comments**  
- `//` line comments are stripped before parsing.
- Statements must end with `;` inside blocks.

**Lattice mapping**  
- Qubits are mapped row‑major: index `i` → `(x = i % cols, y = i // cols)`.

---

## 3. Overlays (constraints/hints)

Key–value entries inside `with overlay { ... }`. ASCII `>=`/`<=` accepted and normalized to `≥`/`≤`.

**Enforced in v0.1**

| Key                 | Form                       | Effect / Check |
|---------------------|----------------------------|----------------|
| `coherence_len`     | `≥ Nns`                    | Inserts `wait(N)` before the control op. |
| `path_len`          | `≤ k`                      | Manhattan distance between two targets must be ≤ `k` (requires 2‑qubit gate & lattice). |
| `damping`           | `η(Φ=Phi)` or `eta(Phi=Phi)` | Validates referenced semantic field exists. |
| `braid`             | `D`                        | Validates defect handle exists in workspace. |

**Floquet (expansion)**

| Key              | Type          | Meaning |
|------------------|---------------|---------|
| `floquet_period` | `Nns`         | Period per cycle (ns). |
| `cycles`         | integer ≥1    | Number of cycles. |
| `duty`           | 0<duty≤1      | ON fraction per period. OFF window is inserted as `wait(...)`. |
| `phase_step`     | deg           | Informational; logged/commented (affects visualizer only). |

**Recognized (not enforced in v0.1)**  
`span`, `coherence_budget` (accepted, logged as “recognized” only).

**Strict mode**  
`--strict-overlays` turns any overlay diagnostic marked *violated/malformed* into a hard error (nonzero exit).

---

## 4. IR Objects (Python dataclasses)

> Exposed for embedding if you import `SQUINT.py` as a module (names may change in v0.1.x).

```python
@dataclass
class WorkspaceIR:
    name: str
    qubits: int
    lattice: Tuple[int, int]                 # (cols, rows)
    semantic_fields: Dict[str, str]          # e.g., {"Phi": "scalar"}
    defect_fields: List[str]                 # e.g., ["D"]

@dataclass
class OperationIR:
    kind: str        # "quantum" | "semantic" | "braid"
    op: str          # e.g., "ctrl", "measure", "initialize", "nucleate", "return", ...
    args: Dict[str, Any] = field(default_factory=dict)
    overlay: Dict[str, Any] = field(default_factory=dict)
    line: int = 0

@dataclass
class KernelIR:
    name: str
    operations: List[OperationIR] = field(default_factory=list)

@dataclass
class ProgramIR:
    workspace: WorkspaceIR
    kernel: KernelIR
```

**Helper functions (internal)**
- `parse(code: str) -> ProgramIR`
- `compile_to_qua(prog: ProgramIR) -> str`  (attaches `_timeline` list to `prog`)
- `simulate(prog: ProgramIR) -> Dict[str, Any]`

---

## 5. QUA-like Output (text)

`compile_to_qua` emits a pseudo‑QUA text program:

- `wait(N)` inserted for `coherence_len ≥ Nns`.
- Supported gates: `x, h, rx, cx, cz`. Unknown gates are stubbed as comments.
- Floquet overlays expand a single `ctrl` into per‑cycle `play(...)` with OFF inserts:  
  ```
  # floquet: period=50ns, cycles=8, duty=0.4, phase_step=12deg
  play('cz', q[0], control=q[1])
  wait(30)
  ...
  ```
- Non‑quantum ops are emitted as comments prefixed by `# semantic:` or `# braid:`.

---

## 6. Log JSON Schema (`*.log.json`)

```jsonc
{
  "workspace": {
    "name": "Chip",
    "qubits": 4,
    "lattice": [2, 2],
    "semantic_fields": { "Phi": "scalar" },
    "defect_fields": ["D"]
  },
  "kernel": "CalibratedEPR",
  "events": [
    { "kind": "quantum", "op": "ctrl", "line": 6,
      "args": { "gate": "rx", "targets": ["q[0]"], "angle": "π/2" },
      "overlay": { "coherence_len": ">=80ns" } }
  ],
  "timeline": [
    { "line": 6, "t": 0,   "op": "wait", "ns": 80 },
    { "line": 6, "t": 80,  "op": "rx", "targets": ["q[0]"] },
    { "line": 7, "t": 80,  "op": "wait", "ns": 120 },
    { "line": 7, "t": 200, "op": "cz", "targets": ["q[0]","q[1]"] },

    // when Floquet is present
    { "line": 10, "t": 200, "op": "cz@floquet", "cycle": 1, "targets": ["q[0]","q[1]"] },
    { "line": 10, "t": 200, "op": "wait", "ns": 30, "cycle": 1 }
  ]
}
```

**Notes**
- `t` is a simple time cursor in **ns**, not a physical hardware schedule.
- `cycle` is present only for `@floquet` entries and their following waits.

---

## 7. Simulator JSON Schema (`*.sim.json`)

The toy simulator focuses on Φ and defect D to produce deterministic demo values.

```jsonc
{
  "fields": { "Phi": { "base": 0.4 } },
  "defects": {
    "D": { "coords": [[0,0],[1,1]], "density": 0.001, "phase": 0.55 }
  },
  "measurements": { "m0": 0, "m1": 1 },
  "latest_obs": {
    "T_eff": 0.4042, "into": "Te",
    "base": 0.4, "defects_term": 0.0002, "field_term": 0.0040
  },
  "events": [
    { "op": "init_phi", "value": 0.4 },
    { "op": "nucleate", "coords": [[0,0],[1,1]], "density": 0.01 },
    { "op": "evolve", "density": 0.0105, "phase": 0.55 },
    { "op": "quench", "amount": 0.02, "new_density": 0.001 },
    { "op": "observe", "Te": 0.4042 },
    { "op": "hysteresis", "window": 3, "trace": [0.0009, 0.0010, 0.0011] },
    { "op": "measure", "values": {"m0":0, "m1":1} },
    { "op": "return", "spec": "Te, corr = m0 ⊕ m1" }
  ]
}
```

**Stability**: keys are stable for v0.1; exact numeric values are placeholders for demos.

---

## 8. Overlay Diagnostics

Overlay checks return diagnostics printed during compile:

- **Info**: accepted/satisfied (e.g., `path_len satisfied (distance=1 ≤ 2)`).
- **Warn**: malformed but non‑strict (e.g., `coherence_len not understood`).  
- **Error (strict)**: malformed or violated; compilation stops with nonzero exit.

**Common messages**
- `coherence_len satisfied by wait(N) insertion`
- `path_len ≤ k violated (distance=d)`
- `damping malformed (got '...')`
- `braid handle 'X' not declared`

---

## 9. Embedding (import as a module)

Although `SQUINT.py` is a CLI script, you can import and reuse its internals:

```python
import SQUINT  # if the file is on sys.path

code = Path("examples/basic.squint").read_text()
prog = SQUINT.parse(code)
prog._strict_overlays = True               # optional flag
qua_text = SQUINT.compile_to_qua(prog)
timeline = getattr(prog, "_timeline", [])
sim = SQUINT.simulate(prog)
```

> This is **best-effort** in v0.1 (no packaging). For production, wrap these in your own module and pin a commit hash.

---

## 10. Errors & Exceptions (Python)

- `ParseError(msg)` — thrown by `parse()` when syntax is invalid.
- `OverlayError(msg, op_line=int)` — thrown by `compile_to_qua()` when `--strict-overlays` is in effect and a violation occurs.

Both bubble to CLI and print a clear message with the offending line (if available).

---

## 11. Visualizer hooks

`SQUINT_FloquetVisualizer.py` expects:
- `.log.json` → uses `workspace.lattice` and `timeline` (looks for `@floquet`).
- `.sim.json` → reads `fields.Phi.base`, `defects.D.coords`, `events`.

No strict schema coupling; missing keys fall back to reasonable defaults.

---

## 12. Compatibility notes

- Floquet expansion is **source‑level** (QUA-like text). Hardware executors must translate to actual pulse trains.
- Guard `unless <expr>` is parsed and preserved in IR but only emitted as a **comment** in v0.1.
- Unsupported gates are passed through as comments; add emitters as your backend supports them.

---

## 13. Examples (brief)

See `Examples.md` for copy‑paste snippets. Quick Floquet overlay:

```squint
ctrl cz q[0], q[1] with overlay {
  coherence_len >= 120ns,
  path_len <= 2,
  floquet_period = 50ns, cycles = 8, duty = 0.4, phase_step = 12deg
};
```

---

## 14. Future (preview)
- Enforce `coherence_budget`, add routing costs.
- Expand guarded ops and conditionals.
- Native OPX/QUA exporter and pulse parameterization.
- Block‑level `floquet { ... }` syntax.

---

_End of v0.1 reference._
