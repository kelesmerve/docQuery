"""
run_batch.py — Toplu İşlem

test_input/ altındaki tüm .md dosyalarını sırayla pipeline'dan geçirir.
Sonuçlar results/approved/ veya results/needs_review/ altına yazılır.
"""

import os
import time
from graph import app
from config import INPUT_DIR, OUTPUT_APPROVED_DIR, OUTPUT_REVIEW_DIR

os.makedirs(OUTPUT_APPROVED_DIR, exist_ok=True)
os.makedirs(OUTPUT_REVIEW_DIR,   exist_ok=True)


def run_batch():
    md_files = sorted([
        f for f in os.listdir(INPUT_DIR) if f.endswith(".md")
    ])

    if not md_files:
        print(f"[Batch] {INPUT_DIR} altinda .md dosyasi bulunamadi.")
        return

    print(f"[Batch] {len(md_files)} dosya isleniyor...\n")

    approved = []
    review   = []
    errors   = []

    for i, filename in enumerate(md_files, 1):
        md_path = os.path.join(INPUT_DIR, filename)
        print(f"[{i}/{len(md_files)}] {filename}")
        print("-" * 60)
        t0 = time.time()

        try:
            initial_state = {
                "markdown_path":     md_path,
                "markdown_content":  "",
                "original_markdown": "",
                "image_refs":        [],
                "vision_outputs":    {},
                "validation_results": {},
                "anonymization_map": {},
                "qa_issues":         [],
                "enriched_content":  "",
                "metadata_yaml":     {},
                "extracted_codes":   {},
            }

            result     = app.invoke(initial_state)
            qa_issues  = result.get('qa_issues', [])
            output_dir = OUTPUT_REVIEW_DIR if qa_issues else OUTPUT_APPROVED_DIR

            output_path = os.path.join(output_dir, filename)
            with open(output_path, "w", encoding="utf-8") as f:
                f.write(result["enriched_content"])

            elapsed = time.time() - t0
            if qa_issues:
                review.append(filename)
                print(f"  → İnceleme ({elapsed:.1f}s) — {len(qa_issues)} sorun")
                for issue in qa_issues:
                    print(f"     - {issue}")
            else:
                approved.append(filename)
                print(f"  → Onaylandi ({elapsed:.1f}s)")

        except Exception as e:
            errors.append((filename, str(e)))
            print(f"  → HATA: {e}")

        print()

    # Özet
    print("=" * 60)
    print("OZET")
    print("=" * 60)
    print(f"Onaylandi  : {len(approved)}/{len(md_files)}")
    print(f"İnceleme   : {len(review)}/{len(md_files)}")
    print(f"Hata       : {len(errors)}/{len(md_files)}")

    if review:
        print("\nİnceleme gereken dosyalar:")
        for f in review:
            print(f"  {f}")

    if errors:
        print("\nHata veren dosyalar:")
        for f, e in errors:
            print(f"  {f}: {e}")


if __name__ == "__main__":
    run_batch()
