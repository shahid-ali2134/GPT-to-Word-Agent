"""Find display equations that define the same well-known concept in different
units (notation may differ). Usage: python concept_eq_check.py [extra.blocks.json ...]"""
import json
import re
import sys
from collections import defaultdict

from dup_check import written_units

CONCEPTS = {
    "cosine similarity": r"\\cos|\\lVert.*\\rVert.*\\lVert|\\sqrt\{\\sum.*\}\\sqrt\{\\sum|\\operatorname\{sim\}|\\mathrm\{sim\}",
    "softmax": r"\\exp\([^)]*\)\s*\}?\s*\{?\\sum.*\\exp|\\mathrm\{softmax\}|\\operatorname\{softmax\}",
    "autoregressive product": r"\\prod_\{t=1\}.*\\mid\s*[a-z]_\{<t\}",
    "cross-entropy / NLL": r"-\s*\\sum.*\\log|-\\frac\{1\}\{[^}]*\}\\sum.*\\log",
    "MSE": r"\\operatorname\{MSE\}|\\mathrm\{MSE\}|\(y_i-\\hat\{y\}_i\)\^\{?2",
    "Bayes": r"P\(E\\mid H\)|\\frac\{P\([^)]*\\mid[^)]*\)P\(",
    "empirical risk argmin": r"\\arg\\min_\{\\theta\}.*\\sum.*\\mathcal\{L\}",
    "utilization rho": r"\\rho\s*=\s*\\frac\{\\lambda\}",
    "attention": r"\\mathbf\{Q\}.*\\mathbf\{K\}\^\{?\\top",
    "precision/recall": r"\\mathrm\{(Precision|Recall)\}|\\operatorname\{(Precision|Recall)\}",
    "KL / PSI divergence": r"D_\{\\mathrm\{KL\}\}|\\mathrm\{PSI\}|\\ln\\frac",
    "L2 norm normalization": r"\\frac\{[^{}]*\}\{\\lVert[^}]*\\rVert",
    "expected value loss": r"\\mathbb\{E\}\[L\(",
    "quantization memory": r"\\frac\{[^}]*b[^}]*\}\{8\}|\\cdot\s*\\frac\{b\}\{8\}",
}


def main():
    units = written_units()
    for extra in sys.argv[1:]:
        units.append(("NEW:" + extra.replace("\\", "/").split("/")[-1], extra))
    hits = defaultdict(list)
    for label, path in units:
        for i, b in enumerate(json.load(open(path, encoding="utf-8"))):
            if b.get("type") != "equation":
                continue
            tex = b.get("latex") or ""
            for name, rx in CONCEPTS.items():
                if re.search(rx, tex, re.S):
                    hits[name].append((f"{label}#{i}", tex.replace("\n", " ")[:110]))
    for name, locs in hits.items():
        if len({l.split("#")[0] for l, _ in locs}) >= 2:
            print(f"== {name}")
            for l, t in locs:
                print(f"   {l}: {t}")


if __name__ == "__main__":
    main()
