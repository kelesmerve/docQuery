"""
check_outputs.py — Çıktı Kalite Kontrolü

results/ altındaki tüm .md dosyalarını tarar ve sorunları raporlar.
"""

import os
import re
from config import OUTPUT_APPROVED_DIR, OUTPUT_REVIEW_DIR


def check_file(path: str, filename: str) -> list:
    issues = []
    with open(path, "r", encoding="utf-8") as f:
        content = f.read()

    # 1. Gövde uzunluğu
    yaml_end = re.search(r'^---\n.*?\n---\n', content, re.DOTALL)
    body = content[yaml_end.end():] if yaml_end else content
    body_lines = [l for l in body.splitlines() if l.strip()]
    if len(body_lines) < 5:
        issues.append(f"[GOVDE] Kaynak belge bos veya cok kisa ({len(body_lines)} satir)")

    # 2. Görsel açıklaması
    img_count  = len(re.findall(r'!\[.*?\]\([^)]+\)', content))
    desc_count = len(re.findall(r'\*\*Gorsel Aciklamasi:\*\*', content))
    if img_count > 0 and desc_count < img_count:
        issues.append(
            f"[GORSEL] {img_count} gorsel var, {desc_count} aciklama var "
            f"- {img_count - desc_count} eksik"
        )

    # 3. Kalan placeholder'lar (kod bloğu kaybı)
    leftover = re.findall(r'\[\[SECURE_CODE_BLOCK_\d+\]\]', content)
    if leftover:
        issues.append(f"[KOD] {len(leftover)} SECURE_CODE_BLOCK placeholder kaldi")

    # 4. Anonimleştirme uyarı notu
    if "ornek/kurgusal" not in content:
        issues.append("[ANON] Uyari notu eksik (ornek/kurgusal)")

    # 5. YAML front-matter var mı?
    if not content.startswith("---"):
        issues.append("[YAML] Front-matter eksik")

    return issues


def run_check():
    print("=" * 60)
    print("CIKTI KALİTE KONTROLÜ")
    print("=" * 60)

    all_files = []
    for output_dir in [OUTPUT_APPROVED_DIR, OUTPUT_REVIEW_DIR]:
        if not os.path.exists(output_dir):
            continue
        label = "[approved]" if "approved" in output_dir else "[review]"
        for filename in sorted(os.listdir(output_dir)):
            if filename.endswith(".md"):
                all_files.append((os.path.join(output_dir, filename), filename, label))

    if not all_files:
        print("Henuz hic cikti yok. Once run_batch.py calistirin.")
        return

    total_issues = 0
    problem_files = 0

    for path, filename, label in all_files:
        issues = check_file(path, filename)
        if issues:
            problem_files += 1
            total_issues  += len(issues)
            print(f"{label} {filename}")
            for issue in issues:
                print(f"  {issue}")

    print()
    print(f"Toplam dosya: {len(all_files)}")
    print(f"Sorunlu dosya: {problem_files}")
    print(f"Toplam sorun: {total_issues}")


if __name__ == "__main__":
    run_check()
