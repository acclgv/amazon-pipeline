"""
qa_checker.py — Control de calidad automático para artículos de Amazon Affiliate.

Fase 6 del roadmap:
  Evalúa los archivos Markdown generados por llm_writer.py.
  Implementa una serie de comprobaciones deterministas y una evaluación IA (opcional)
  para calcular una puntuación global de 0 a 100.
  Si la puntuación es < 68, el artículo se considera "RECHAZADO".

Uso:
  python scripts/qa_checker.py --niche mascotas --keyword "comedero automatico gato"
  python scripts/qa_checker.py --niche mascotas --all
  python scripts/qa_checker.py --niche mascotas --keyword "comedero automatico gato" --skip-ai
"""

import argparse
import json
import logging
import re
from datetime import datetime
from pathlib import Path

from llm_writer import MODEL_WRITER, OllamaClient, slugify
from utils import DATA_DIR, PROJECT_ROOT, setup_logging

# ─────────────────────────────────────────────
# Constantes
# ─────────────────────────────────────────────

SITE_CONTENT_DIR = PROJECT_ROOT / "site" / "content"
QA_OUTPUT_DIR = DATA_DIR / "qa_output"

MODEL_QA_AI_API = "gemma-4-31b-it"
MODEL_QA_AI_FALLBACK = "gemma2:9b-instruct-q4_K_M"

THRESHOLD_PASS = 68
THRESHOLD_WARN = 50

# Patrones para determinismo
REGEX_DISCLOSURE = r"> \*\*.*?Divulgación de afiliados"
REGEX_PRICE_PLACEHOLDER = r"\{\{PRICE_\d+\}\}"
REGEX_AFFILIATE_PLACEHOLDER = r"\{\{AFFILIATE_[A-Z_]+\}\}"
REGEX_HARDCODED_PRICE = r"\d+[.,]\d{2}\s*€"
REGEX_AMAZON_LINK = r"https?://(?:www\.)?amazon\.es/dp/[A-Z0-9]{10}\?tag=.*"
REGEX_AFFILIATE_LINK = r"\?tag="
REGEX_BROKEN_LINK = r"\]\(\s*\)"

# Frases de IA-speak y rechazos del LLM (lista negra completa)
IA_SPEAK_PHRASES = [
    "lo siento",
    "no puedo",
    "como modelo de lenguaje",
    "en conclusión",
    "es importante destacar",
    "sin lugar a dudas",
    "no me es posible",
    "cabe destacar",
    "soy una inteligencia artificial",
]

# Rechazos explícitos del LLM (score = 0 inmediato)
LLM_REFUSAL_PHRASES = [
    "lo siento, pero no puedo",
    "como modelo de lenguaje",
    "no puedo generar",
    "no puedo cumplir",
    "no puedo crear",
    "i cannot fulfill",
    "i cannot generate",
    "i'm sorry, but i can't",
    "as an ai language model",
    "soy una inteligencia artificial",
    "no me es posible generar",
    "no estoy en condiciones de",
]

logger = setup_logging("qa_checker")


# ─────────────────────────────────────────────
# Clases Modelos de QA
# ─────────────────────────────────────────────

class QACheck:
    def __init__(self, name: str, score: int, max_score: int, status: str, details: str = ""):
        self.name = name
        self.score = score
        self.max_score = max_score
        self.status = status  # pass, warn, fail
        self.details = details

    def to_dict(self):
        return {
            "name": self.name,
            "score": self.score,
            "max": self.max_score,
            "status": self.status,
            "details": self.details,
        }

class QAReport:
    def __init__(self, article_path: str):
        self.article_path = article_path
        self.score = 0
        self.max_possible = 100
        self.result = "PENDIENTE"
        self.checks: list[QACheck] = []
        self.issues: list[dict] = []
        self.timestamp = datetime.now().isoformat()

    def add_check(self, check: QACheck):
        self.checks.append(check)
        self.score += check.score

    def add_issue(self, severity: str, line: int, description: str):
        self.issues.append({
            "severity": severity,
            "line": line,
            "description": description
        })

    def evaluate_final_score(self, threshold: int, skip_ai: bool):
        # Si saltamos la IA, el maximo es 90, lo normalizamos a 100
        if skip_ai:
            if self.max_possible == 90:
                self.score = int((self.score / 90) * 100)
            self.max_possible = 100

        if self.score >= threshold:
            self.result = "APROBADO"
        elif self.score >= THRESHOLD_WARN:
            self.result = "REVISIÓN MANUAL"
        else:
            self.result = "RECHAZADO"

    def to_dict(self):
        return {
            "article_path": str(self.article_path),
            "score": self.score,
            "result": self.result,
            "timestamp": self.timestamp,
            "checks": [c.to_dict() for c in self.checks],
            "issues": self.issues
        }


# ─────────────────────────────────────────────
# Funciones Extraedoras
# ─────────────────────────────────────────────

def extract_front_matter_and_body(content: str) -> tuple[str, str]:
    """Separa el front matter YAML del cuerpo del artículo."""
    if not content.startswith("---"):
        return "", content

    parts = content.split("---", 2)
    if len(parts) >= 3:
        return parts[1], parts[2]
    return "", content

def split_into_lines_with_index(text: str) -> list[tuple[int, str]]:
    """Devuelve las líneas del text junto a su nº de ínea (1-indexed)."""
    return [(i + 1, line) for i, line in enumerate(text.split("\n"))]


# ─────────────────────────────────────────────
# CRITICAL CHECKS (Score = 0 inmediato)
# ─────────────────────────────────────────────

def check_unresolved_placeholders(report: QAReport, body: str) -> bool:
    """
    FALLO CRÍTICO: Si hay placeholders {{PRICE_N}} o {{AFFILIATE_*}} sin resolver,
    el artículo NO puede publicarse bajo ningún concepto.
    Devuelve True si el artículo está contaminado.
    """
    price_matches = re.findall(REGEX_PRICE_PLACEHOLDER, body)
    affiliate_matches = re.findall(REGEX_AFFILIATE_PLACEHOLDER, body)
    all_matches = price_matches + affiliate_matches

    if all_matches:
        detail = f"Placeholders sin resolver: {', '.join(all_matches[:5])}"
        report.add_check(QACheck("unresolved_placeholders", 0, 100, "fail", detail))
        report.add_issue("critical", 0, f"FALLO CRÍTICO: {len(all_matches)} placeholder(s) sin resolver")
        report.score = 0
        report.result = "RECHAZADO"
        logger.error(f"  🔴 FALLO CRÍTICO: {len(all_matches)} placeholder(s) detectados — score forzado a 0")
        return True
    return False


def check_llm_refusal(report: QAReport, body: str) -> bool:
    """
    FALLO CRÍTICO: Si el LLM se negó a generar contenido (refusal),
    el artículo es basura y NO puede publicarse.
    Devuelve True si se detecta un rechazo.
    """
    body_lower = body.lower()
    for phrase in LLM_REFUSAL_PHRASES:
        if phrase in body_lower:
            detail = f"Rechazo del LLM detectado: '{phrase}'"
            report.add_check(QACheck("llm_refusal", 0, 100, "fail", detail))
            report.add_issue("critical", 0, f"FALLO CRÍTICO: El LLM se negó a generar contenido")
            report.score = 0
            report.result = "RECHAZADO"
            logger.error(f"  🔴 FALLO CRÍTICO: Rechazo del LLM detectado ('{phrase}') — score forzado a 0")
            return True
    return False


# ─────────────────────────────────────────────
# Deterministic Checks
# ─────────────────────────────────────────────

def check_disclosure(report: QAReport, body: str):
    """Verifica la presencia de la divulgación de afiliados."""
    points = 10
    if re.search(REGEX_DISCLOSURE, body):
        report.add_check(QACheck("disclosure", points, points, "pass"))
    else:
        report.add_check(QACheck("disclosure", 0, points, "fail", "No se encontró el texto de divulgación de afiliados"))
        report.add_issue("critical", 0, "Falta bloque de divulgación de afiliados")

def check_no_hardcoded_prices(report: QAReport, body: str):
    """
    Verifica que no haya precios hardcodeados que estén fuera 
    de las fichas técnicas y que puedan violar los ToS de Amazon.
    """
    points = 15
    score = points
    status = "pass"
    details = ""

    # Buscar precios hardcodeados
    lines = split_into_lines_with_index(body)
    in_ficha_tecnica = False
    
    for line_num, line in lines:
        if "### Ficha Técnica" in line:
            in_ficha_tecnica = True
        elif line.startswith("## ") and "Ficha Técnica" not in line:
            in_ficha_tecnica = False

        matches = re.findall(REGEX_HARDCODED_PRICE, line)
        if matches:
            # Penaliza agresivamente los precios hardcodeados (ToS Amazon)
            score -= 5
            status = "warn" if status == "pass" else "fail"
            report.add_issue("warning", line_num, f"Precio hardcodeado encontrado: {matches[0]}")
            details += f"Precio hardcodeado en la linea {line_num}. "

    score = max(0, score)
    if score == 0:
        status = "fail"

    report.add_check(QACheck("no_hardcoded_prices", score, points, status, details.strip()))

def check_ia_speak(report: QAReport, body: str):
    """Penaliza frases típicas de IA y rechazos."""
    points = 15
    score = points
    details = ""

    lines = split_into_lines_with_index(body)
    
    for line_num, line in lines:
        lower_line = line.lower()
        for phrase in IA_SPEAK_PHRASES:
            if phrase in lower_line:
                score -= 5
                details += f"Frase IA detectada en linea {line_num}: '{phrase}'. "
                report.add_issue("critical", line_num, f"Frase o rechazo de IA ('{phrase}')")

    score = max(0, score)
    status = "pass" if score == points else ("fail" if score <= 5 else "warn")
    report.add_check(QACheck("ia_speak", score, points, status, details.strip()))

def check_keyword_stuffing(report: QAReport, body: str, keyword: str):
    """Comprueba la densidad de la keyword en el texto (< 3%)."""
    points = 10
    
    words = body.lower().split()
    total_words = len(words)
    if total_words == 0:
        report.add_check(QACheck("keyword_stuffing", 0, points, "fail", "El cuerpo del artículo está vacío"))
        return

    keyword_tokens = keyword.lower().split()
    keyword_count = sum(1 for w in words if " ".join(keyword_tokens) in w or any(kt in w for kt in keyword_tokens))
    
    # Estimación un poco tonta pero funcional. Mejor contar ocurrencias exactas en el texto.
    actual_count = body.lower().count(keyword.lower())
    keyword_word_count = len(keyword.split())
    
    density = (actual_count * keyword_word_count) / total_words

    if density > 0.04:
        report.add_check(QACheck("keyword_stuffing", 0, points, "fail", f"Densidad = {density:.2%} (> 4%)"))
        report.add_issue("warning", 0, f"Keyword stuffing detectado ({density:.2%})")
    elif density > 0.03:
        report.add_check(QACheck("keyword_stuffing", 5, points, "warn", f"Densidad = {density:.2%} (> 3%)"))
    else:
        report.add_check(QACheck("keyword_stuffing", points, points, "pass"))

def check_structure(report: QAReport, body: str):
    """Verifica presencia de H2 fijos: Introducción, Comparativa, Guía de Compra, Conclusión."""
    points = 10
    score = points
    details = ""

    required_sections = ["Introducción", "Comparativa", "Guía de Compra", "Conclusión"]
    
    for sec in required_sections:
        if not re.search(rf"## .*{sec}.*", body, re.IGNORECASE):
            score -= 2
            details += f"Falta sección {sec}. "
            report.add_issue("warning", 0, f"Sección principal desaparecida: {sec}")

    headers_2 = re.findall(r"## \d+\..+", body)
    if len(headers_2) < 3:
        score -= 2
        details += "Hay menos de 3 productos enumerados (## N. ). "
        report.add_issue("warning", 0, f"Pocos productos analizados ({len(headers_2)})")

    score = max(0, score)
    status = "pass" if score == points else "warn"
    if score < 5: status = "fail"
    report.add_check(QACheck("structure", score, points, status, details.strip()))

def check_affiliate_links(report: QAReport, body: str):
    """Verifica que los ASINs tengan el link limpio."""
    points = 10
    score = points
    details = ""

    lines = split_into_lines_with_index(body)
    
    for line_num, line in lines:
        if re.search(REGEX_BROKEN_LINK, line):
            score -= 5
            report.add_issue("warning", line_num, "Enlace markdown roto detectado")
            details += f"Enlace roto en linea {line_num}. "
        
        # Si hay links a amazon, que tengan tag
        if "amazon.es" in line:
            if not re.search(REGEX_AFFILIATE_LINK, line):
                score -= 3
                report.add_issue("warning", line_num, "Enlace a Amazon sin tag de afiliado")
                details += f"Amazon sin tag afiliado en linea {line_num}. "

    score = max(0, score)
    status = "pass" if score == points else ("fail" if score < 5 else "warn")
    report.add_check(QACheck("affiliate_links", score, points, status, details.strip()))

def check_schema_jsonld(report: QAReport, body: str):
    """Valida presencia y veracidad del Schema."""
    points = 5
    
    schema_match = re.search(r'<script type="application/ld\+json">(.*?)</script>', body, re.DOTALL)
    if schema_match:
        try:
            schema_json = json.loads(schema_match.group(1))
            if schema_json.get("@type") == "ItemList":
                report.add_check(QACheck("schema_jsonld", points, points, "pass"))
            else:
                report.add_check(QACheck("schema_jsonld", 2, points, "warn", "Schema no es de ItemList"))
        except json.JSONDecodeError:
            report.add_check(QACheck("schema_jsonld", 0, points, "fail", "JSON-LD Invalido"))
            report.add_issue("warning", 0, "Schema JSON-LD malformado")
    else:
        report.add_check(QACheck("schema_jsonld", 0, points, "fail", "Sin json-ld tag"))
        report.add_issue("warning", 0, "Falta Schema JSON-LD")

def check_front_matter(report: QAReport, front_matter: str):
    """Revisa que el front_matter no esté roto y contenga campos básicos."""
    points = 5
    score = points
    details = ""

    required_fields = ["title:", "date:", "slug:", "description:", "tags:", "categories:", "cover:"]
    for field in required_fields:
        if field not in front_matter:
            score -= 1
            details += f"Falta {field}. "

    # Check for multiline unquoted description which often breaks Hugo YAML
    lines = front_matter.split("\n")
    for i, line in enumerate(lines):
        if line.startswith("description:"):
            # Si tiene comillas y acaba en la misma linea, guay. 
            pass # Simplificado por ahora
            
    score = max(0, score)
    status = "pass" if score == points else ("fail" if score == 0 else "warn")
    if score != points:
        report.add_issue("warning", 0, f"Problemas FrontMatter: {details}")
    report.add_check(QACheck("front_matter", score, points, status, details.strip()))

def check_images(report: QAReport, body: str):
    """Asegura que usamos hotlink m.media-amazon.com."""
    points = 5
    score = points
    details = ""
    # Buscar todas las imagenes MD ![alt](url)
    images = re.findall(r'!\[.*?\]\((.*?)\)', body)
    for img in images:
        if "m.media-amazon.com" not in img:
            score -= 2
            details += f"Imagen no es de Amazon: {img}. "
            report.add_issue("warning", 0, f"Imagen no permitida: {img}")

    score = max(0, score)
    status = "pass" if score == points else ("fail" if score < 3 else "warn")
    report.add_check(QACheck("images", score, points, status, details.strip()))

def check_length(report: QAReport, body: str):
    """Artículo > 2000 ch."""
    points = 5
    chars = len(body)
    if chars > 5000:
        report.add_check(QACheck("length", 5, 5, "pass"))
    elif chars > 2000:
        report.add_check(QACheck("length", 3, 5, "warn", "Longitud justa"))
    else:
        report.add_check(QACheck("length", 0, 5, "fail", f"Muy corto: {chars} chars"))
        report.add_issue("warning", 0, f"Artículo demasiado corto ({chars} chars)")

# ─────────────────────────────────────────────
# AI Check
# ─────────────────────────────────────────────

def check_ai_naturalness(report: QAReport, body: str, ollama: OllamaClient):
    """Pide a gemma2 puntuar de 1 a 10 la naturalidad."""
    points_max = 10
    
    # Extraer primer tercio del artículo (aprox) para no saturar memoria
    sample_text = body[:3000]

    system = "Eres una experta editora de textos seo en español. Tu objetivo es detectar la naturalidad humana."
    prompt = f"""
Lee el siguiente fragmento de un artículo de afiliado y dime cómo de natural y humano suena del 1 al 10.
Un 1 es una traducción automática o puro lenguaje robótico y repetitivo ("es importante destacar", "sin duda").
Un 10 es un artículo escrito por un nativo experto, ameno y directo.

[TEXTO]
{sample_text}

Tu respuesta debe ser un JSON estricto con este formato: {{"score": X, "reason": "tu justificacion breve"}}
"""
    try:
        response = ollama.generate(MODEL_QA_AI_FALLBACK, prompt, system, temperature=0.1, max_tokens=150)
        # Buscar el JSON
        match = re.search(r'\{.*\}', response, re.DOTALL)
        if match:
            data = json.loads(match.group(0))
            score_10 = data.get("score", 5)
            reason = data.get("reason", "")
            
            # Asignar los puntos del 0 al 10
            actual_score = max(0, min(10, int(score_10)))
            status = "pass" if actual_score >= 8 else ("warn" if actual_score >= 5 else "fail")
            report.add_check(QACheck("ai_naturalness", actual_score, points_max, status, reason))
            
            if status == "fail":
                report.add_issue("warning", 0, f"Evaluación IA mala: {reason} (Score {actual_score}/10)")
        else:
             logger.warning("No se pudo parsear json del LLM en check AI.")
             report.add_check(QACheck("ai_naturalness", 5, points_max, "warn", "Parser error LLM"))
    except Exception as e:
        logger.error(f"Error procesando AI QA: {e}")
        report.add_check(QACheck("ai_naturalness", 5, points_max, "warn", f"Error de generacion: {e}"))


# ─────────────────────────────────────────────
# Orquestador
# ─────────────────────────────────────────────

def run_qa_on_file(file_path: Path, keyword: str, skip_ai: bool, threshold: int, verbose: bool) -> QAReport:
    report = QAReport(file_path)

    try:
        with open(file_path, "r", encoding="utf-8") as f:
            content = f.read()
    except Exception as e:
        logger.error(f"  ✗ No se puede leer {file_path}: {e}")
        report.add_issue("critical", 0, f"Error de lectura: {e}")
        report.result = "ERROR"
        return report

    front_matter, body = extract_front_matter_and_body(content)

    if verbose: logger.info(f"  🔍 Ejecutando checks sobre {file_path.name}...")

    # ── CRITICAL CHECKS PRIMERO (cortocircuito instantáneo) ──
    if check_unresolved_placeholders(report, body):
        return report  # Score = 0, no hace falta seguir
    if check_llm_refusal(report, body):
        return report  # Score = 0, no hace falta seguir

    # Deterministic checks
    check_disclosure(report, body)
    check_no_hardcoded_prices(report, body)
    check_ia_speak(report, body)
    check_keyword_stuffing(report, body, keyword)
    check_structure(report, body)
    check_affiliate_links(report, body)
    check_schema_jsonld(report, body)
    check_front_matter(report, front_matter)
    check_images(report, body)
    check_length(report, body)

    # AI checking
    report.max_possible = 90
    if not skip_ai:
        ollama = OllamaClient()
        if ollama.is_available():
            if verbose: logger.info("  🤖 Evaluando naturalidad con IA...")
            report.max_possible = 100
            check_ai_naturalness(report, body, ollama)
        else:
            logger.warning("  ⚠ Ollama no disponible, omitiendo test IA.")
            skip_ai = True

    report.evaluate_final_score(threshold, skip_ai)

    if verbose:
        for c in report.checks:
            mark = "✅" if c.status == "pass" else ("⚠️" if c.status == "warn" else "❌")
            logger.info(f"     {mark} {c.name.ljust(20)}: {c.score}/{c.max_score} | {c.details[:60]}")

    return report


def discover_and_qa(niche: str, keyword: str = "", process_all: bool = False, skip_ai: bool = False, threshold: int = 68, verbose: bool = False):
    niche_dir = SITE_CONTENT_DIR / niche
    if not niche_dir.exists():
        logger.error(f"El directorio del nicho {niche} no existe: {niche_dir}")
        return

    files_to_process = []
    if process_all:
        files_to_process = list(niche_dir.glob("*.md"))
    else:
        if not keyword:
            logger.error("Se requiere --keyword si no pasas --all")
            return
        target_file = niche_dir / f"{slugify(keyword)}.md"
        if target_file.exists():
            files_to_process = [target_file]
        else:
            logger.error(f"No se encontró el articulo {target_file}")
            return
    
    if not files_to_process:
        logger.warning("No hay articulos .md para procesar.")
        return

    report_dir = QA_OUTPUT_DIR / niche
    report_dir.mkdir(parents=True, exist_ok=True)

    passed = 0
    failed = 0

    for file_path in files_to_process:
        # Si comprobamos global, la keyword suele ser el título o el basename (aproximado)
        kwd = keyword if keyword else file_path.stem.replace("-", " ") 
        logger.info(f"📝 Evaluando: {kwd} ({file_path.name})")

        report = run_qa_on_file(file_path, kwd, skip_ai, threshold, verbose)

        icon = "✅" if report.score >= threshold else "❌"
        logger.info(f"   {icon} Total QA Score: {report.score}/{report.max_possible} -> {report.result}")

        if report.score >= threshold: passed+=1
        else: failed+=1

        report_file = report_dir / f"{file_path.stem}_qa.json"
        with open(report_file, "w", encoding="utf-8") as rf:
            json.dump(report.to_dict(), rf, indent=2, ensure_ascii=False)
        
    logger.info(f"\n📊 Resumen Nicho: {passed} Aprobados | {failed} Suspendidos/Revisión")


# ─────────────────────────────────────────────
# Interfaz CLI
# ─────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Automatización QA de artículos Amazon Affiliates.")
    parser.add_argument("--niche", required=True, help="El nicho, ej. 'mascotas'")
    parser.add_argument("--keyword", help="Keyword específica a examinar")
    parser.add_argument("--all", action="store_true", help="Evaluar todos los .md del nicho")
    parser.add_argument("--skip-ai", action="store_true", help="Salta el validador IA de naturalidad (usará sobre 90 ptos normalizado a 100)")
    parser.add_argument("--verbose", action="store_true", help="Imprimir detalles completos")
    parser.add_argument("--threshold", type=int, default=THRESHOLD_PASS, help=f"Score paso (default: {THRESHOLD_PASS})")

    args = parser.parse_args()

    logger.info("🚀 Iniciando QA Checker")
    discover_and_qa(
        niche=args.niche,
        keyword=args.keyword,
        process_all=args.all,
        skip_ai=args.skip_ai,
        threshold=args.threshold,
        verbose=args.verbose
    )

if __name__ == "__main__":
    main()
