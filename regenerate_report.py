import sys
import os
import re
from datetime import datetime
import ai_processor
import meet_joiner

def main():
    if len(sys.argv) < 2:
        print("Usage: python regenerate_report.py <path_to_report.txt>")
        sys.exit(1)

    file_path = sys.argv[1]
    if not os.path.exists(file_path):
        print(f"Error: File '{file_path}' not found.")
        sys.exit(1)

    try:
        with open(file_path, "r", encoding="utf-8") as f:
            content = f.read()

        # Extract Transcript, Captions, Chat Log, Meet Link, Date, Times
        def extract(section, next_section=r"="):
            pattern = rf"{section}\n-+\n(.*?)(?={next_section}|\Z)"
            m = re.search(pattern, content, re.DOTALL)
            return m.group(1).strip() if m else ""

        transcript = extract("TRANSCRIPT")
        captions = extract("CAPTIONS")
        chat_log = extract("CHAT LOG", r"TRANSCRIPT|=")

        # If there's no combined transcript, rebuild it
        raw_transcript = transcript
        if not raw_transcript:
            parts = []
            if captions:
                parts.append("CAPTIONS\n" + str(captions))
            if chat_log:
                parts.append("CHAT\n" + str(chat_log))
            raw_transcript = "\n\n".join(parts)

        # Parse date and times
        date_match = re.search(r"Date\s*:\s*([\d-]+)", content)
        start_match = re.search(r"Start\s*:\s*([\d:]+)", content)
        end_match = re.search(r"End\s*:\s*([\d:]+)", content)
        link_match = re.search(r"Meet Link\s*:\s*(.+)", content)

        date_str = date_match.group(1).strip() if date_match else datetime.today().strftime("%Y-%m-%d")
        meet_link = link_match.group(1).strip() if link_match else "Unknown"

        try:
            start_time = datetime.strptime(f"{date_str} {start_match.group(1).strip()}", "%Y-%m-%d %H:%M") if start_match else datetime.now()
            end_time = datetime.strptime(f"{date_str} {end_match.group(1).strip()}", "%Y-%m-%d %H:%M") if end_match else datetime.now()
        except Exception:
            start_time = datetime.now()
            end_time = datetime.now()

        print(f"[Regenerate] Analyzing payload for {date_str}...")
        
        # Re-run AI processor
        ai_results = ai_processor.analyze_text(raw_transcript, date_str)
        
        # Inject old captions/chat back so they aren't lost
        ai_results["captions"] = captions
        ai_results["chat_log"] = chat_log
        ai_results["transcript"] = transcript

        # Delete the old file
        os.remove(file_path)

        # Save via meet_joiner to format it identically
        meet_joiner.save_report(meet_link, start_time, end_time, ai_results)

        print("[Regenerate] Successfully regenerated and overwrote the required report!")

    except Exception as e:
        print(f"Error regenerating report: {e}")

if __name__ == "__main__":
    main()
