from ai_processor import analyze_text

sample_text = """
We discussed building a React dashboard.
Suhas will implement authentication by tomorrow.
This is urgent because client demo is near.
We also reviewed UI components.
"""

result = analyze_text(sample_text, "2026-03-28")

print("\n=== RESULT ===")
print(result)