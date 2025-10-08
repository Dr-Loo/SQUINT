from pathlib import Path
import subprocess, json, sys

EX_DIR = Path("squint/examples")
SQUINT = ["squint"]

def run(cmd):
    print(">", " ".join(map(str, cmd)))
    return subprocess.run(cmd, check=True, text=True, capture_output=True)

def main():
    oks = 0
    for p in sorted(EX_DIR.glob("*.squint")):
        out = p.with_suffix(".qua.txt")
        log = p.with_suffix(".log.json")

        run(SQUINT + ["compile", str(p), "--output", str(out), "--log", "--strict-overlays"])
        run(SQUINT + ["compile", str(p), "--output", str(out.with_name(p.stem + "_verify.qua.txt")), "--log", "--strict-overlays"])

        # Simple existence + JSON sanity
        assert out.exists(), f"Missing {out}"
        assert log.exists(), f"Missing {log}"
        json.loads(log.read_text(encoding="utf-8"))
        oks += 1
    print(f"OK: {oks} examples compiled and logged.")
    return 0

if __name__ == "__main__":
    sys.exit(main())
