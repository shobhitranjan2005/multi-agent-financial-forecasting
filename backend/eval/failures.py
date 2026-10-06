import json
import glob
from pathlib import Path

def build_failures():
    # Only consider multiagent runs, ignore nodebate/leave-one-out
    # Because we want the full debate
    files = [f for f in glob.glob("results/multiagent_*.json") if "no" not in f]
    files = sorted(files)
    if not files:
        print("No multiagent results found.")
        return
    latest = files[-1]
    
    with open(latest, 'r', encoding='utf-8') as f:
        data = json.load(f)
        
    records = data.get("records", [])
    scored = data.get("scored", [])
    
    if not records or len(records) != len(scored):
        print(f"Records missing or mismatched in JSON. (scored: {len(scored)}, records: {len(records)})")
        return

    lines = ["# Multi-Agent Failures Browser\n"]
    lines.append(f"Source: `{latest}`\n")
    
    count = 0
    for s, r in zip(scored, records):
        conf = s.get("confidence_pct")
        if conf is None or conf < 80:
            continue
            
        pred = s.get("predicted_direction")
        actual = s.get("actual_direction")
        if pred == actual:
            continue
            
        ticker = s.get("ticker")
        as_of = s.get("as_of")
        transcript = r.get("transcript") or "[No transcript available]"
        
        count += 1
        lines.append(f"## {ticker} on {as_of}")
        lines.append(f"- **Predicted**: {pred} ({conf}%)")
        lines.append(f"- **Actual**: {actual}")
        lines.append(f"\n### Debate Transcript\n")
        lines.append(transcript)
        lines.append("\n---\n")
        
    if count == 0:
        lines.append("\nNo high-confidence failures found in this run.\n")
        
    out_path = Path("docs/FAILURES.md")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"Wrote {count} failures to {out_path}")

if __name__ == "__main__":
    build_failures()
