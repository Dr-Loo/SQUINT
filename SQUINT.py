# SQUINT.py — v0.1 runner with overlays (strict), path_len check, Floquet expansion,
# timeline logging, QUA-like output, JSON log, and --simulate

import re, sys, json, random
from dataclasses import dataclass, field, asdict
from typing import List, Dict, Tuple, Any, Optional
from pathlib import Path

# ---------- IR ----------
@dataclass
class WorkspaceIR:
    name: str
    qubits: int
    lattice: Tuple[int, int]                 # (cols, rows)
    semantic_fields: Dict[str, str]
    defect_fields: List[str]

@dataclass
class OperationIR:
    kind: str                                 # "quantum" | "semantic" | "braid"
    op: str                                   # "ctrl", "measure", "initialize", ...
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

# ---------- Parser ----------
class ParseError(Exception):
    pass

def _normalize_ascii_ops(s: str) -> str:
    # Allow >= and <= in overlays; normalize to ≥ and ≤
    return s.replace(">=", "≥").replace("<=", "≤")

_ws_name   = re.compile(r'\bworkspace\s+(\w+)\s*\{', re.I)
_qubits    = re.compile(r'\bqubits\s+\w+\[(\d+)\]\s*;', re.I)
_lattice   = re.compile(r'\blattice\s+\w+\(\s*(\d+)\s*,\s*(\d+)\s*\)\s*attach\s+\w+\s*;', re.I)
_sfield    = re.compile(r'\bsemantic_field\s+(\w+)\s*:\s*(scalar|vector|tensor\[\d+\])\s+on\s+(\w+)\s*;', re.I)
_dfield    = re.compile(r'\bdefect_field\s+(\w+)\s*:\s*defects\s+on\s+(\w+)\s*\{[^}]*\}\s*;', re.I)
_kernel    = re.compile(r'\bkernel\s+(\w+)\s*(?:\([^)]*\))?\s+on\s+(\w+)\s*\{', re.I)

_stmt_transport = re.compile(r'^\s*transport\s+(\w+)\s*=\s*(.+?)\s*;\s*$', re.I)
_stmt_quench    = re.compile(r'^\s*quench\s+(\w+)\s*=\s*inject\(\s*(\w+)\s*,\s*amount\s*=\s*([\d.eE\-]+)\s*\)\s*;\s*$', re.I)
_stmt_observe   = re.compile(r'^\s*observe\s+(\w+)(?:\s+into\s+(\w+))?(?:\s+with\s+corrections\s*\{([^}]*)\})?\s*;\s*$', re.I)
_stmt_ctrl      = re.compile(r'^\s*ctrl\s+(\w+)\s+(\w+(?:\[\d+\])?(?:\s*,\s*\w+(?:\[\d+\])?)?)(?:\s+angle\s*=\s*([^ \t;]+))?(?:\s+with\s+overlay\s*\{([^}]*)\})?(?:\s+unless\s+([^\{;]+))?\s*;\s*$', re.I)
_stmt_init      = re.compile(r'^\s*initialize\s+(\w+)\s*=\s*(.+?)\s*;\s*$', re.I)
_stmt_defect_ev = re.compile(r'^\s*(nucleate|pin|anneal|evolve)\s+(.+)$', re.I)
_stmt_measure   = re.compile(r'^\s*measure\s+(\w+(?:\[\d+\])?)(?:\s*,\s*(\w+(?:\[\d+\])?))?\s*->\s*(\w+)(?:\s*,\s*(\w+))?\s*;\s*$', re.I)
_stmt_return    = re.compile(r'^\s*return\s*\{(.+)\}\s*;\s*$', re.I)
_stmt_hyst      = re.compile(r'^\s*hysteresis_trace\s*\(\s*(\w+)(?:\s*,\s*window\s*=\s*([0-9]+))?\s*\)\s*;\s*$', re.I)
_stmt_relax     = re.compile(r'^\s*relax\s+(\w+)\s*\(\s*rate\s*=\s*(.+?)\s*\)\s*;\s*$', re.I)

def _parse_overlay(s: str) -> Dict[str, str]:
    if not s:
        return {}
    s = _normalize_ascii_ops(s)
    out: Dict[str, str] = {}
    for raw in s.split(','):
        item = raw.strip()
        if not item:
            continue
        if '≥' in item:
            k, v = item.split('≥', 1)
            out[k.strip()] = f'>={v.strip()}'
        elif '≤' in item:
            k, v = item.split('≤', 1)
            out[k.strip()] = f'<={v.strip()}'
        elif '==' in item:
            k, v = item.split('==', 1)
            out[k.strip()] = v.strip()
        elif '=' in item:
            k, v = item.split('=', 1)
            out[k.strip()] = v.strip()
        else:
            out[item] = 'true'
    return out

def parse(code: str) -> ProgramIR:
    code = "\n".join(ln for ln in code.splitlines() if not ln.strip().startswith("//"))

    m = _ws_name.search(code)
    if not m:
        raise ParseError("workspace block not found")
    ws_name = m.group(1)

    # workspace block braces
    i = m.end()
    depth = 1
    while i < len(code) and depth:
        if code[i] == '{': depth += 1
        elif code[i] == '}': depth -= 1
        i += 1
    ws_block = code[m.end():i-1]

    qm = _qubits.search(ws_block)
    if not qm:
        raise ParseError("qubits decl not found (expect: qubits q[N];)")
    qubits = int(qm.group(1))

    lm = _lattice.search(ws_block)
    if not lm:
        raise ParseError("lattice decl not found (expect: lattice L(x,y) attach q;)")
    lattice = (int(lm.group(1)), int(lm.group(2)))

    sfields = {m.group(1): m.group(2) for m in _sfield.finditer(ws_block)}
    dfields = [m.group(1) for m in _dfield.finditer(ws_block)]
    ws = WorkspaceIR(ws_name, qubits, lattice, sfields, dfields)

    # kernel block
    km = _kernel.search(code, i)
    if not km:
        raise ParseError("kernel block not found")
    kname, target_ws = km.group(1), km.group(2)
    if target_ws != ws_name:
        raise ParseError(f"kernel '{kname}' targets workspace '{target_ws}' but workspace is '{ws_name}'")
    j = km.end()
    depth = 1
    while j < len(code) and depth:
        if code[j] == '{': depth += 1
        elif code[j] == '}': depth -= 1
        j += 1
    kblock = code[km.end():j-1]

    ops: List[OperationIR] = []
    for ln_no, raw in enumerate(kblock.splitlines(), start=1):
        line = raw.strip()
        if not line:
            continue

        m = _stmt_ctrl.match(line)
        if m:
            gate = m.group(1)
            targets = [t.strip() for t in m.group(2).split(',')]
            angle = m.group(3)
            overlay = _parse_overlay(m.group(4) or '')
            guard = m.group(5)
            args = {"gate": gate, "targets": targets}
            if angle:
                args["angle"] = angle
            if guard:
                args["guard"] = guard
            ops.append(OperationIR("quantum", "ctrl", args=args, overlay=overlay, line=ln_no))
            continue

        m = _stmt_measure.match(line)
        if m:
            t1, t2, o1, o2 = m.groups()
            args = {"targets": [t for t in [t1, t2] if t], "outputs": [o for o in [o1, o2] if o]}
            ops.append(OperationIR("quantum", "measure", args=args, line=ln_no))
            continue

        m = _stmt_transport.match(line)
        if m:
            name, expr = m.groups()
            ops.append(OperationIR("semantic", "transport", args={"name": name, "expr": expr}, line=ln_no))
            continue

        m = _stmt_quench.match(line)
        if m:
            name, handle, amount = m.groups()
            ops.append(OperationIR("braid", "quench", args={"name": name, "handle": handle, "amount": float(amount)}, line=ln_no))
            continue

        m = _stmt_observe.match(line)
        if m:
            what, into, corr = m.groups()
            corr_map = {}
            if corr:
                for kv in corr.split(','):
                    if '=' in kv:
                        k, v = kv.split('=', 1)
                        corr_map[k.strip()] = v.strip()
            ops.append(OperationIR("semantic", "observe", args={"what": what, "into": into, "corrections": corr_map}, line=ln_no))
            continue

        m = _stmt_init.match(line)
        if m:
            name, expr = m.groups()
            ops.append(OperationIR("semantic", "initialize", args={"name": name, "expr": expr}, line=ln_no))
            continue

        m = _stmt_hyst.match(line)
        if m:
            handle, window = m.groups()
            a = {"handle": handle}
            if window:
                a["window"] = int(window)
            ops.append(OperationIR("semantic", "hysteresis_trace", args=a, line=ln_no))
            continue

        m = _stmt_relax.match(line)
        if m:
            name, rate = m.groups()
            ops.append(OperationIR("semantic", "relax", args={"name": name, "rate": rate}, line=ln_no))
            continue

        m = _stmt_defect_ev.match(line)
        if m:
            kind, rest = m.groups()
            ops.append(OperationIR("braid", kind.lower(), args={"spec": rest.strip().rstrip(';')}, line=ln_no))
            continue

        m = _stmt_return.match(line)
        if m:
            ops.append(OperationIR("semantic", "return", args={"spec": m.group(1).strip()}, line=ln_no))
            continue

        raise ParseError(f"Unrecognized statement on line {ln_no}: {line}")

    return ProgramIR(workspace=ws, kernel=KernelIR(kname, ops))

# ---------- Overlay checking ----------
class OverlayError(Exception):
    def __init__(self, message, op_line=None):
        super().__init__(message)
        self.op_line = op_line

_re_num_ns = re.compile(r'(\d+)\s*ns\b', re.I)

def _parse_required_ns(v: str) -> Optional[int]:
    if not isinstance(v, str):
        return None
    m = _re_num_ns.search(v)
    return int(m.group(1)) if m else None

def _parse_eta_phi(expr: str) -> Optional[str]:
    # Extract field name from η(Φ=Phi) or eta(Phi=Phi)
    s = (expr or "").replace(" ", "")
    for pat in [r'η\(Φ=(\w+)\)', r'eta\(Phi=(\w+)\)', r'η\(Phi=(\w+)\)']:
        m = re.match(pat, s)
        if m:
            return m.group(1)
    return None

def _q_name_to_xy(name: str, ws: WorkspaceIR) -> Optional[Tuple[int, int]]:
    # Map q[i] to lattice coords (row-major): x = i % cols, y = i // cols
    m = re.match(r'(\w+)\[(\d+)\]', name)
    if not m:
        return None
    idx = int(m.group(2))
    cols = ws.lattice[0]
    return (idx % cols, idx // cols)

def _manhattan(a: str, b: str, ws: WorkspaceIR) -> Optional[int]:
    A = _q_name_to_xy(a, ws)
    B = _q_name_to_xy(b, ws)
    if A is None or B is None:
        return None
    return abs(A[0] - B[0]) + abs(A[1] - B[1])

def check_overlay_constraints(op: dict, workspace: WorkspaceIR) -> Tuple[bool, List[str]]:
    """
    Validate overlay for a ctrl operation. op should include keys:
      - "overlay": dict
      - "args": {"targets":[...], ...}
    """
    ov = op.get("overlay", {}) or {}
    args = op.get("args", {}) or {}
    tgts = args.get("targets", [])
    diags: List[str] = []
    ok = True

    # coherence_len
    if "coherence_len" in ov:
        req = ov["coherence_len"]
        ns = _parse_required_ns(req)
        if ns is None or not str(req).startswith(">="):
            ok = False
            diags.append(f"coherence_len malformed (got '{req}', expect >=###ns)")
        else:
            diags.append(f"coherence_len satisfied by wait({ns}) insertion")

    # damping η(Φ=Phi)
    if "damping" in ov:
        f = _parse_eta_phi(ov["damping"])
        if not f:
            ok = False
            diags.append(f"damping malformed (got '{ov['damping']}', expect η(Φ=Phi) or eta(Phi=Phi))")
        elif f not in workspace.semantic_fields:
            ok = False
            diags.append(f"damping references missing semantic field '{f}'")

    # braid handle
    if "braid" in ov:
        handle = ov["braid"]
        if handle not in workspace.defect_fields:
            ok = False
            diags.append(f"braid handle '{handle}' not declared in defect fields {workspace.defect_fields}")

    # path_len ≤ k  (only meaningful for 2-qubit gates)
    if "path_len" in ov:
        req = ov["path_len"]
        ok_req = str(req).startswith("<=")
        try:
            k = int(str(req).replace("<=", "").strip())
        except Exception:
            k, ok_req = None, False

        if not ok_req or len(tgts) != 2 or k is None:
            ok = False
            diags.append(f"path_len malformed (got '{req}', expect <=k on 2-qubit op)")
        else:
            d = _manhattan(tgts[0], tgts[1], workspace)
            if d is None:
                diags.append("path_len check skipped (couldn’t map targets to lattice)")
            elif d > k:
                ok = False
                diags.append(f"path_len ≤ {k} violated (distance={d})")
            else:
                diags.append(f"path_len satisfied (distance={d} ≤ {k})")

    # --- Floquet overlays: floquet_period, cycles, duty, phase_step ---
    if "floquet_period" in ov:
        p = ov["floquet_period"]
        # accept "50ns" or raw number with 'ns'
        s = str(p).strip().lower()
        if s.endswith("ns"): s = s[:-2]
        try:
            p_ns = int(float(s))
            if p_ns <= 0: raise ValueError
            diags.append(f"floquet_period accepted: {p_ns} ns")
        except Exception:
            ok = False
            diags.append(f"floquet_period malformed (got '{p}', expect e.g. 50ns)")
    if "cycles" in ov:
        try:
            cyc = int(str(ov["cycles"]))
            if cyc <= 0: raise ValueError
            diags.append(f"cycles accepted: {cyc}")
        except Exception:
            ok = False
            diags.append(f"cycles malformed (got '{ov['cycles']}', expect positive integer)")
    if "duty" in ov:
        try:
            duty = float(str(ov["duty"]))
            if not (0.0 < duty <= 1.0): raise ValueError
            diags.append(f"duty accepted: {duty}")
        except Exception:
            ok = False
            diags.append(f"duty malformed (got '{ov['duty']}', expect 0<duty<=1)")
    if "phase_step" in ov:
        s = str(ov["phase_step"]).lower().strip()
        if s.endswith("deg"): s = s[:-3]
        try:
            float(s)
            diags.append(f"phase_step accepted: {ov['phase_step']}")
        except Exception:
            ok = False
            diags.append(f"phase_step malformed (got '{ov['phase_step']}', expect e.g. 15deg)")

    # Recognized but not enforced (future work)
    for k in ("span", "coherence_budget"):
        if k in ov:
            diags.append(f"{k} overlay recognized but not enforced in v0.1 stub")

    return ok, diags

# ---------- QUA-like exporter (with timeline + Floquet) ----------
def _emit_wait_ns(ns: int) -> str:
    return f"    wait({ns})"

def _ns_from_overlay(v: Any) -> Optional[int]:
    if isinstance(v, str) and v.startswith(">=") and v.endswith("ns"):
        try:
            return int(v[2:-2])
        except Exception:
            return None
    return None

def compile_to_qua(prog: ProgramIR) -> str:
    ws, krn = prog.workspace, prog.kernel
    strict = getattr(prog, "_strict_overlays", False)

    lines: List[str] = []
    lines.append("program = QUAProgram()")
    lines.append(f"# workspace {ws.name} qubits={ws.qubits} lattice={ws.lattice}")
    lines.append("with program:")

    # simple timeline (MUST be initialized before use)
    time_ns = 0
    timeline: List[Dict[str, Any]] = []

    for op in krn.operations:
        if op.kind == "quantum" and op.op == "ctrl":
            gate = op.args["gate"].lower()
            tgts = op.args["targets"]
            angle = op.args.get("angle")

            # Validate overlays
            ok, diags = check_overlay_constraints({"overlay": op.overlay, "args": op.args}, ws)
            for d in diags:
                print(f"ℹ️  overlay[{op.line}]: {d}")
            if not ok and strict:
                raise OverlayError(f"Overlay unsatisfied on line {op.line}: {'; '.join(diags)}", op_line=op.line)

            # Apply coherence_len → wait(ns)
            coh = op.overlay.get("coherence_len")
            wait_needed = _ns_from_overlay(coh)
            if coh and wait_needed is None:
                print(f"⚠️  overlay coherence_len not understood: {coh} (expect >=###ns)")
            if wait_needed:
                lines.append(_emit_wait_ns(wait_needed))
                timeline.append({"line": op.line, "t": time_ns, "op": "wait", "ns": wait_needed})
                time_ns += wait_needed

            # ----- Floquet expansion (optional) -----
            if ("floquet_period" in op.overlay) or ("cycles" in op.overlay) or ("duty" in op.overlay):
                # Parse numbers
                def _ns_from_any(v):
                    if v is None: return None
                    s = str(v)
                    if s.endswith("ns"): s = s[:-2]
                    try: return int(float(s))
                    except: return None
                period_ns = _ns_from_any(op.overlay.get("floquet_period"))
                cycles    = int(float(op.overlay.get("cycles", 1)))
                duty_f    = float(op.overlay.get("duty", 0.5))
                ps        = str(op.overlay.get("phase_step", "0deg"))  # informational

                if period_ns is None or cycles <= 0 or not (0.0 < duty_f <= 1.0):
                    print(f"⚠️  Floquet parameters malformed (period={op.overlay.get('floquet_period')}, cycles={op.overlay.get('cycles')}, duty={op.overlay.get('duty')}) — emitting single pulse.")
                    # Fall back to single play
                    if gate == "rx":
                        lines.append(f"    play('rx', {tgts[0]}, angle={angle})")
                    elif gate == "x":
                        lines.append(f"    play('x', {tgts[0]})")
                    elif gate == "h":
                        lines.append(f"    play('h', {tgts[0]})")
                    elif gate == "cx":
                        lines.append(f"    play('cnot', {tgts[0]}, control={tgts[1]})")
                    elif gate == "cz":
                        lines.append(f"    play('cz', {tgts[0]}, control={tgts[1]})")
                    else:
                        lines.append(f"    # unsupported gate '{gate}' on {tgts}")
                    timeline.append({"line": op.line, "t": time_ns, "op": gate, "targets": tgts})
                else:
                    on_ns  = int(round(period_ns * duty_f))
                    off_ns = max(0, period_ns - on_ns)
                    lines.append(f"    # floquet: period={period_ns}ns, cycles={cycles}, duty={duty_f}, phase_step={ps}")
                    for c in range(cycles):
                        # ON window: emit the gate
                        if gate == "rx":
                            lines.append(f"    play('rx', {tgts[0]}, angle={angle})")
                        elif gate == "x":
                            lines.append(f"    play('x', {tgts[0]})")
                        elif gate == "h":
                            lines.append(f"    play('h', {tgts[0]})")
                        elif gate == "cx":
                            lines.append(f"    play('cnot', {tgts[0]}, control={tgts[1]})")
                        elif gate == "cz":
                            lines.append(f"    play('cz', {tgts[0]}, control={tgts[1]})")
                        else:
                            lines.append(f"    # unsupported gate '{gate}' on {tgts}")
                        timeline.append({"line": op.line, "t": time_ns, "op": f"{gate}@floquet", "cycle": c+1, "targets": tgts})
                        # OFF window: wait remainder of the period
                        if off_ns > 0:
                            lines.append(_emit_wait_ns(off_ns))
                            timeline.append({"line": op.line, "t": time_ns, "op": "wait", "ns": off_ns, "cycle": c+1})
                            time_ns += off_ns
            else:
                # ----- Single-shot emission (existing behavior) -----
                if gate == "rx":
                    lines.append(f"    play('rx', {tgts[0]}, angle={angle})")
                elif gate == "x":
                    lines.append(f"    play('x', {tgts[0]})")
                elif gate == "h":
                    lines.append(f"    play('h', {tgts[0]})")
                elif gate == "cx":
                    lines.append(f"    play('cnot', {tgts[0]}, control={tgts[1]})")
                elif gate == "cz":
                    lines.append(f"    play('cz', {tgts[0]}, control={tgts[1]})")
                else:
                    lines.append(f"    # unsupported gate '{gate}' on {tgts}")
                timeline.append({"line": op.line, "t": time_ns, "op": gate, "targets": tgts})

        elif op.kind == "quantum" and op.op == "measure":
            tgts = op.args["targets"]
            outs = op.args["outputs"]
            for t, o in zip(tgts, outs):
                lines.append(f"    measure({t}) -> {o}")
                timeline.append({"line": op.line, "t": time_ns, "op": "measure", "target": t, "out": o})

        elif op.kind == "semantic":
            lines.append(f"    # semantic:{op.op} {op.args}")

        elif op.kind == "braid":
            lines.append(f"    # braid:{op.op} {op.args}")

    lines.append("end_program()")

    # attach the timeline for optional logging
    setattr(prog, "_timeline", timeline)
    return "\n".join(lines)

# ---------- Mini semantic/defect simulator ----------
_num_in_tuple = re.compile(r'\((-?\d+)\s*,\s*(-?\d+)\)')

def _coords_from_spec(spec: str):
    return [(int(x), int(y)) for x, y in _num_in_tuple.findall(spec)]

def simulate(prog: ProgramIR) -> Dict[str, Any]:
    random.seed(42)
    state = {"fields": {}, "defects": {}, "measurements": {}, "latest_obs": None, "events": []}
    phi_base = 0.0
    def_density = 0.0
    def_phase = 0.0

    for op in prog.kernel.operations:
        if op.kind == "semantic" and op.op == "initialize":
            if op.args["name"] == "Phi":
                m = re.search(r'constant\(([^)]+)\)', op.args["expr"])
                if m:
                    phi_base = float(m.group(1))
                state["fields"]["Phi"] = {"base": phi_base}
                state["events"].append({"op": "init_phi", "value": phi_base})

        elif op.kind == "braid" and op.op == "nucleate":
            coords = _coords_from_spec(op.args["spec"])
            def_density = 0.0100
            state["defects"]["D"] = {"coords": coords, "density": def_density, "phase": def_phase}
            state["events"].append({"op": "nucleate", "coords": coords, "density": def_density})

        elif op.kind == "braid" and op.op == "evolve":
            def_density = round(def_density * 1.05, 4)
            def_phase = 0.55
            if "D" in state["defects"]:
                state["defects"]["D"]["density"] = def_density
                state["defects"]["D"]["phase"] = def_phase
            state["events"].append({"op": "evolve", "density": def_density, "phase": def_phase})

        elif op.kind == "braid" and op.op == "quench":
            amt = float(op.args.get("amount", 0.0))
            def_density = 0.001 if amt >= 0.02 else max(0.0, def_density - amt)
            if "D" in state["defects"]:
                state["defects"]["D"]["density"] = def_density
            state["events"].append({"op": "quench", "amount": amt, "new_density": def_density})

        elif op.kind == "semantic" and op.op == "observe":
            defects_term = 0.0002 if "D" in state["defects"] else 0.0
            field_term = round(0.01 * phi_base, 4)
            Te = round(phi_base + defects_term + field_term, 4)
            into = op.args.get("into") or "obs"
            state["latest_obs"] = {"T_eff": Te, "into": into, "base": phi_base,
                                   "defects_term": defects_term, "field_term": field_term}
            state["events"].append({"op": "observe", "Te": Te})

        elif op.kind == "semantic" and op.op == "hysteresis_trace":
            w = int(op.args.get("window", 3))
            trace = [round(def_density * (0.9 + 0.1 * i / max(1, w - 1)), 4) for i in range(w)]
            state["events"].append({"op": "hysteresis", "window": w, "trace": trace})

        elif op.kind == "quantum" and op.op == "measure":
            outs = op.args["outputs"]
            vals = [0, 1][:len(outs)]
            for o, v in zip(outs, vals):
                state["measurements"][o] = v
            state["events"].append({"op": "measure", "values": state["measurements"].copy()})

        elif op.kind == "semantic" and op.op == "return":
            state["events"].append({"op": "return", "spec": op.args["spec"]})

    return state

# ---------- CLI ----------
def _parse_cli(argv: List[str]):
    src = None
    out = None
    want_log = False
    want_sim = False
    strict_ov = False
    it = iter(argv)
    other: List[str] = []
    for a in it:
        if a == "--out":
            out = next(it, None)
        elif a == "--log":
            want_log = True
        elif a == "--simulate":
            want_sim = True
        elif a == "--strict-overlays":
            strict_ov = True
        else:
            other.append(a)
    if other:
        src = other[0]
    return src, out, want_log, want_sim, strict_ov

def main():
    src_arg, out_arg, want_log, want_sim, strict_ov = _parse_cli(sys.argv[1:])
    src = Path(src_arg) if src_arg else Path("CalibratedEPR.squint")

    try:
        code = src.read_text(encoding="utf-8")
    except FileNotFoundError:
        print(f"❌ File {src} not found")
        return

    code = _normalize_ascii_ops(code)

    try:
        prog = parse(code)
    except ParseError as e:
        print(f"❌ Parse error: {e}")
        return

    setattr(prog, "_strict_overlays", strict_ov)

    print("🧠 Parsed Workspace:", prog.workspace.name)
    print("   Qubits:", prog.workspace.qubits, "Lattice:", prog.workspace.lattice)
    print("   Semantic Fields:", prog.workspace.semantic_fields)
    print("   Defect Fields:", prog.workspace.defect_fields)
    print("\n⚙️  Kernel:", prog.kernel.name)
    print("   Operations:", len(prog.kernel.operations))
    print("\n🔍 Operation Classification:")
    for i, op in enumerate(prog.kernel.operations):
        print(f"   {i}: {op.op:16s} -> {op.kind:8s} @ line {op.line}")

    qua = compile_to_qua(prog)
    dst = Path(out_arg) if out_arg else src.with_suffix(".qua.txt")
    dst.write_text(qua, encoding="utf-8")

    # Optional JSON event log (+ timeline)
    if want_log:
        log_path = src.with_suffix(".log.json")
        events = [{"kind": o.kind, "op": o.op, "line": o.line, "args": o.args, "overlay": o.overlay}
                  for o in prog.kernel.operations]
        payload = {
            "workspace": asdict(prog.workspace),
            "kernel": prog.kernel.name,
            "events": events,
            "timeline": getattr(prog, "_timeline", [])
        }
        log_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        print(f"🧾 Log: {log_path}")

    # Optional simulator
    if want_sim:
        sim = simulate(prog)
        sim_json = src.with_suffix(".sim.json")
        sim_txt  = src.with_suffix(".sim.txt")
        sim_json.write_text(json.dumps(sim, indent=2), encoding="utf-8")

        lines = []
        lines.append("🚀 ENHANCED EXECUTION WITH SEMANTIC FIELD SIMULATION")
        lines.append("============================================================\n")
        lines.append("🎯 SEMANTIC FIELD SIMULATION RESULTS")
        lines.append("============================================================")
        if "Phi" in sim["fields"]:
            lines.append(f"   🌐 Initialized field 'Phi' = {sim['fields']['Phi']['base']}")
        if "D" in sim["defects"]:
            coords = sim['defects']['D']['coords']
            lines.append(f"   🔷 Nucleated D at {coords}")
            lines.append(f"   🔄 Evolved D: density 0.0100→{sim['defects']['D']['density']:.4f}, "
                         f"phase: {sim['defects']['D']['phase']:.2f} rad")
            lines.append(f"   ❄️ Quenched D: density now {sim['defects']['D']['density']:.4f}")
        if sim["latest_obs"]:
            Te   = sim["latest_obs"]["T_eff"]
            base = sim["latest_obs"]["base"]
            dt   = sim["latest_obs"]["defects_term"]
            ft   = sim["latest_obs"]["field_term"]
            lines.append(f"   🌡️ Observed T_eff → {sim['latest_obs']['into']} = {Te} "
                         f"(base: {base:.2f} + defects: {dt:.4f} + field: {ft:.4f})")
        ht = [ev for ev in sim["events"] if ev["op"] == "hysteresis"]
        if ht:
            tr = ht[-1]["trace"]
            lines.append(f"   📈 Hysteresis trace for D: {len(tr)} points, range [{min(tr):.4f}, {max(tr):.4f}]")
        if sim["measurements"]:
            m = sim["measurements"]
            lines.append(f"   📤 Return: {sim['latest_obs']['into']} = {Te}, "
                         f"m0={m.get('m0','?')}, m1={m.get('m1','?')}, m0⊕m1={(m.get('m0',0))^(m.get('m1',0))}")
            for k, v in m.items():
                lines.append(f"   📊 Measured {k} = {v}")

        lines.append("\n📊 FINAL STATE:")
        lines.append(f"   Fields: {list(sim['fields'].keys())}")
        lines.append(f"   Defects: {list(sim['defects'].keys())}")
        lines.append(f"   Measurements: {sim['measurements']}")
        if sim["latest_obs"]:
            lines.append(f"   Latest observation: {sim['latest_obs']['into']} = {sim['latest_obs']['T_eff']}")
        sim_txt.write_text("\n".join(lines), encoding="utf-8")
        print("\n".join(lines))
        print(f"\n💾 Simulation data: {sim_json}")
        print(f"💾 Simulation report: {sim_txt}")

    print("\n--- QUA-like output ---\n")
    print(qua)
    print(f"\n💾 Saved: {dst}")

if __name__ == "__main__":
    main()
