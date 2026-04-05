"""
audit_hugo.py — Auditor QA de archivos Markdown en site/content/.

Comprueba:
  1. Enlaces HTTP inseguros (deben ser HTTPS).
  2. Placeholders de precio sin resolver ({{PRICE_N}}).
  3. Frases de IA-speak que se hayan colado en la conclusión.
  4. URLs de Schema JSON-LD incorrectas (dominio antiguo).
  5. Precios hardcodeados en texto (fuera de fichas técnicas).

Uso:
  python scripts/audit_hugo.py
  python scripts/audit_hugo.py --fix    # Aplicar correcciones automáticas
"""

import argparse
import re
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SITE_CONTENT_DIR = PROJECT_ROOT / "site" / "content"

CORRECT_DOMAIN = "https://compras-top.pages.dev"

# Patrones de problemas
ISSUES = {
    "http_link": re.compile(r'http://(?!localhost)'),
    "price_placeholder": re.compile(r'\{\{PRICE_\d+\}\}'),
    "ia_speak_conclusion": re.compile(
        r'(?:lo siento|no puedo|como modelo de lenguaje|soy una inteligencia artificial)',
        re.IGNORECASE,
    ),
    "old_domain_schema": re.compile(r'guiadecompraspro\.es'),
    "hardcoded_price_in_text": re.compile(r'(?<!\|)\s*\d{2,3}[.,]\d{2}\s*€'),
}


def audit_file(filepath: Path, fix: bool = False) -> list[dict]:
    """Audita un archivo .md y devuelve (y opcionalmente corrige) problemas."""
    findings = []

    try:
        content = filepath.read_text(encoding="utf-8")
    except Exception as e:
        findings.append({"file": str(filepath), "line": 0, "issue": f"Error leyendo: {e}", "severity": "ERROR"})
        return findings

    original_content = content
    lines = content.split("\n")

    for line_num, line in enumerate(lines, 1):
        # 1. HTTP inseguro
        if ISSUES["http_link"].search(line):
            findings.append({
                "file": filepath.name, "line": line_num,
                "issue": "Enlace HTTP inseguro detectado", "severity": "WARNING",
                "snippet": line.strip()[:80],
            })
            if fix:
                lines[line_num - 1] = line.replace("http://", "https://")

        # 2. Placeholder de precio sin resolver
        if ISSUES["price_placeholder"].search(line):
            findings.append({
                "file": filepath.name, "line": line_num,
                "issue": "Placeholder {{PRICE_N}} sin resolver", "severity": "CRITICAL",
                "snippet": line.strip()[:80],
            })
            if fix:
                lines[line_num - 1] = ISSUES["price_placeholder"].sub(
                    "[Ver precio actual en Amazon]", line
                )

        # 3. IA-speak en todo el artículo
        match = ISSUES["ia_speak_conclusion"].search(line)
        if match:
            findings.append({
                "file": filepath.name, "line": line_num,
                "issue": f"Frase IA-speak detectada: '{match.group()}'", "severity": "CRITICAL",
                "snippet": line.strip()[:80],
            })

        # 4. Dominio antiguo en schema
        if ISSUES["old_domain_schema"].search(line):
            findings.append({
                "file": filepath.name, "line": line_num,
                "issue": "URL con dominio antiguo (guiadecompraspro.es)", "severity": "WARNING",
                "snippet": line.strip()[:80],
            })
            if fix:
                lines[line_num - 1] = re.sub(
                    r'https?://guiadecompraspro\.es',
                    CORRECT_DOMAIN,
                    line
                )

        # 5. Precio hardcodeado fuera de ficha técnica
        if ISSUES["hardcoded_price_in_text"].search(line):
            # Solo penalizar si no es una fila de tabla
            if not line.strip().startswith("|"):
                findings.append({
                    "file": filepath.name, "line": line_num,
                    "issue": "Posible precio hardcodeado en texto", "severity": "WARNING",
                    "snippet": line.strip()[:80],
                })

    # Aplicar correcciones
    if fix:
        new_content = "\n".join(lines)
        if new_content != original_content:
            filepath.write_text(new_content, encoding="utf-8")
            findings.append({
                "file": filepath.name, "line": 0,
                "issue": "CORRECCIONES APLICADAS automáticamente", "severity": "FIX",
            })

    return findings


def main():
    parser = argparse.ArgumentParser(description="Auditor QA de Markdowns Hugo")
    parser.add_argument("--fix", action="store_true", help="Aplicar correcciones automáticas")
    args = parser.parse_args()

    md_files = list(SITE_CONTENT_DIR.rglob("*.md"))

    if not md_files:
        print("[!] No se encontraron archivos .md en site/content/")
        return

    print(f"\n[SCAN] Auditando {len(md_files)} archivos Markdown...\n")
    print(f"{'-' * 70}")

    total_findings = 0

    for filepath in sorted(md_files):
        findings = audit_file(filepath, fix=args.fix)
        total_findings += len(findings)

        for f in findings:
            icon = {"CRITICAL": "[X]", "WARNING": "[!]", "FIX": "[+]", "ERROR": "[E]"}.get(f["severity"], "[?]")
            print(f"  {icon} [{f['severity']}] {f['file']}:{f['line']} -- {f['issue']}")
            if f.get("snippet"):
                print(f"     |-- {f['snippet']}")

    print(f"\n{'-' * 70}")
    print(f"Total: {total_findings} hallazgos en {len(md_files)} archivos")
    if args.fix:
        print("[OK] Se han aplicado todas las correcciones posibles.")
    else:
        print("[TIP] Usa --fix para aplicar correcciones automáticas.")
    print()


if __name__ == "__main__":
    main()
