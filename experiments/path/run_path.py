#!/usr/bin/env python3
import json, os
import numpy as np

RESULTS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "results")

def p_detect_bvi(p, H):
    if H < 2: return 0.0
    rs = np.arange(1, H)
    return float(np.mean((1-(1-p)**rs)*(1-(1-p)**(H-rs))))

def p_detect_bbca(p, H):
    return float(p**H)

def simulate(trials=20000, H_values=(3,5,8,12), seed=11):
    rng = np.random.default_rng(seed)
    p_values = np.round(np.arange(0.0, 1.001, 0.1), 2)
    rows = []
    for H in H_values:
        for p in p_values:
            bvi_det = bbca_det = total = 0
            for _ in range(trials):
                total += 1
                participates = rng.random(H) < p
                r = int(rng.integers(1, max(2, H)))
                up = bool(participates[:r].any())
                dn = bool(participates[r:].any())
                if up and dn:
                    bvi_det += 1
                if participates.all():
                    bbca_det += 1
            rows.append({
                "H": H, "p": float(p),
                "bvi_detection": bvi_det/max(1,total),
                "bvi_closed_form": p_detect_bvi(p, H),
                "bbca_detection": bbca_det/max(1,total),
                "bbca_closed_form": p_detect_bbca(p, H),
            })
    return rows

def main():
    os.makedirs(RESULTS, exist_ok=True)
    print("=" * 70)
    print("E3 - PATH COVERAGE SWEEP (Table 3)")
    print("=" * 70)
    print("Running simulation... (20,000 calls per cell)\n")

    rows = simulate()

    print(f"{'H':>4} {'p':>6} {'BVI detect':>12} {'BBCA detect':>12}")
    print("-" * 40)
    for r in rows:
        if round(r["p"]*10) % 2 == 0:
            print(f"{r['H']:>4} {r['p']:>6.1f} {r['bvi_detection']*100:>11.1f}% {r['bbca_detection']*100:>11.1f}%")

    print("\n--- Participation needed for 50% detection ---")
    print(f"{'H':>4} {'BVI':>8} {'BBCA':>8}")
    for H in (3,5,8,12):
        sub = sorted([r for r in rows if r["H"]==H], key=lambda x: x["p"])
        bvi_p  = next((r["p"] for r in sub if r["bvi_detection"]>=0.5), None)
        bbca_p = next((r["p"] for r in sub if r["bbca_detection"]>=0.5), None)
        print(f"{H:>4} {str(round(bvi_p,2)) if bvi_p else 'never':>8} {str(round(bbca_p,2)) if bbca_p else 'never':>8}")

    with open(os.path.join(RESULTS,"table3_path_coverage.json"),"w") as f:
        json.dump({"rows": rows}, f, indent=2)

    with open(os.path.join(RESULTS,"table3_path_coverage.csv"),"w") as f:
        f.write("H,p,bvi_detection,bvi_closed_form,bbca_detection,bbca_closed_form\n")
        for r in rows:
            f.write(f"{r['H']},{r['p']},{r['bvi_detection']:.5f},{r['bvi_closed_form']:.5f},{r['bbca_detection']:.5f},{r['bbca_closed_form']:.5f}\n")

    ps = [0.1,0.25,0.5,0.75,1.0]
    tex_rows = ""
    for H in (3,5,8,12):
        for scheme,key in (("BVI","bvi_detection"),("BBCA","bbca_detection")):
            cells = []
            for p in ps:
                r = min([x for x in rows if x["H"]==H], key=lambda x: abs(x["p"]-p))
                cells.append(f"{r[key]*100:.1f}\\%")
            lead = str(H) if scheme=="BVI" else ""
            tex_rows += f"{lead} & {scheme} & " + " & ".join(cells) + " \\\\\n"

    tex = f"""\\begin{{table}}[t]
\\centering
\\caption{{Path attestation coverage. BVI vs BBCA at varying carrier participation $p$ and path length $H$. 20,000 simulated calls per cell.}}
\\label{{tab:path}}
\\begin{{tabular}}{{llrrrrr}}
\\toprule
$H$ & Scheme & $p=0.1$ & $p=0.25$ & $p=0.5$ & $p=0.75$ & $p=1.0$ \\\\
\\midrule
{tex_rows}\\bottomrule
\\end{{tabular}}
\\end{{table}}"""

    with open(os.path.join(RESULTS,"table3_path_coverage.tex"),"w") as f:
        f.write(tex)

    print(f"\nWritten to {RESULTS}/table3_path_coverage.{{json,csv,tex}}")

if __name__ == "__main__":
    main()
