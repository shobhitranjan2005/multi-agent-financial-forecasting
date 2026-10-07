import json
import glob
from pathlib import Path
from datetime import datetime

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

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_path = Path(f"results/failures_{stamp}.md")
    
    lines = ["# Multi-Agent Failures Browser\n"]
    lines.append(f"Source: `{latest}`\n")
    
    count = 0
    total_cases = len(records)
    has_news_count = 0
    has_fund_count = 0
    has_macro_count = 0

    for r in records:
        ef = r.get("evidence_flags") or {}
        if ef.get("has_news"): has_news_count += 1
        if ef.get("has_fundamentals"): has_fund_count += 1
        if ef.get("has_macro", True): has_macro_count += 1

    lines.append("## Evidence Availability Rates\n")
    lines.append(f"- **News/Sentiment**: {has_news_count}/{total_cases} ({has_news_count/total_cases*100:.1f}%)")
    lines.append(f"- **Fundamentals**: {has_fund_count}/{total_cases} ({has_fund_count/total_cases*100:.1f}%)")
    lines.append(f"- **Macro**: {has_macro_count}/{total_cases} ({has_macro_count/total_cases*100:.1f}%)")
    lines.append("\n## Wrong Forecasts (Confidence >= 80%)\n")
    
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
        lines.append(f"### {ticker} on {as_of}")
        lines.append(f"- **Predicted**: {pred} ({conf}%)")
        lines.append(f"- **Actual**: {actual}")
        lines.append(f"- **Realised Move**: {s.get('return_pct', 0):.2f}% (vs Benchmark {s.get('benchmark_return_pct', 0):.2f}%)")
        
        # Specialists disagreed?
        sigs = r.get("specialist_signals") or {}
        lines.append(f"- **Specialist Signals**: {json.dumps(sigs)}")
        
        # Reconciliation flags
        recon_notes = [n for n in r.get("notes", []) if "reconciliation" in n.lower()]
        lines.append(f"- **Reconciliation Flags**: {', '.join(recon_notes) if recon_notes else 'None'}")
        
        lines.append(f"\n#### Debate Transcript\n")
        lines.append(transcript)
        lines.append("\n---\n")
        
    if count == 0:
        lines.append("\nNo high-confidence failures found in this run.\n")
        
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"Wrote {count} failures to {out_path}")

if __name__ == "__main__":
    build_failures()
