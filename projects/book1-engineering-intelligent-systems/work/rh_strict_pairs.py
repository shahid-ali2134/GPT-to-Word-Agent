"""Strict-check pairs: chapter NN as in Word now vs the pre-rehumanize backup export (rh_orig).
python rh_strict_pairs.py <NN> <docx>  -> rh_review/strict_chNN_pairs.json"""
import json, os, shutil, subprocess, sys
HERE = os.path.dirname(os.path.abspath(__file__))
n, docx = sys.argv[1].zfill(2), sys.argv[2]
d = os.path.join(HERE, "rh_final")
shutil.rmtree(d, ignore_errors=True)
subprocess.run([sys.executable, os.path.join(HERE, "style_cleanup.py"), "export", docx, d], check=True, capture_output=True)
o = {e["id"]: e for e in json.load(open(os.path.join(HERE, "rh_orig", f"ch{n}.json"), encoding="utf-8"))}
f = [e for e in json.load(open(os.path.join(d, f"ch{n}.json"), encoding="utf-8")) if e["kind"] == "body"]
out = [{"id": e["id"], "now": e["text"], "math_now": e.get("math"), "before": o[e["id"]]["text"],
        "math_before": o[e["id"]].get("math")} for e in f]
json.dump(out, open(os.path.join(HERE, "rh_review", f"strict_ch{n}_pairs.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
print(len(out), "pairs")
