"""
utils.py — Utilidades compartidas para todo el pipeline Amazon Affiliate.

Funciones reutilizables: HTTP con anti-bot, logging, throttling, carga de .env.
"""

import logging
import os
import random
import time
from pathlib import Path

import requests
from dotenv import load_dotenv

# ─────────────────────────────────────────────
# Constantes
# ─────────────────────────────────────────────

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data"
LOGS_DIR = PROJECT_ROOT / "logs"
SCRIPTS_DIR = PROJECT_ROOT / "scripts"

# Pool de User-Agents reales (Chrome/Firefox en Windows/Mac, actualizados 2025-2026)
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:133.0) Gecko/20100101 Firefox/133.0",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:132.0) Gecko/20100101 Firefox/132.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.1 Safari/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Ubuntu; Linux x86_64; rv:133.0) Gecko/20100101 Firefox/133.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:133.0) Gecko/20100101 Firefox/133.0",
]


# ─────────────────────────────────────────────
# Entorno
# ─────────────────────────────────────────────

def load_env() -> dict:
    """Carga variables de entorno desde .env y las devuelve como dict."""
    env_path = PROJECT_ROOT / ".env"
    load_dotenv(env_path)
    return {
        "AMAZON_TAG": os.getenv("AMAZON_TAG", ""),
        "AMAZON_ACCESS_KEY": os.getenv("AMAZON_ACCESS_KEY", ""),
        "AMAZON_SECRET_KEY": os.getenv("AMAZON_SECRET_KEY", ""),
        "GITHUB_TOKEN": os.getenv("GITHUB_TOKEN", ""),
    }


# ─────────────────────────────────────────────
# Logging
# ─────────────────────────────────────────────

def setup_logging(script_name: str, level: int = logging.INFO) -> logging.Logger:
    """
    Configura logging con salida a consola y archivo en logs/.
    
    Args:
        script_name: Nombre del script (sin extensión). Se usa como nombre del logger y del archivo.
        level: Nivel de logging (default: INFO).
    
    Returns:
        Logger configurado.
    """
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    
    logger = logging.getLogger(script_name)
    logger.setLevel(level)
    
    # Evitar duplicar handlers si se llama varias veces
    if logger.handlers:
        return logger
    
    formatter = logging.Formatter(
        fmt="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    
    # Handler: consola
    console_handler = logging.StreamHandler()
    console_handler.setLevel(level)
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)
    
    # Handler: archivo
    from datetime import date
    log_file = LOGS_DIR / f"{script_name}_{date.today().isoformat()}.log"
    file_handler = logging.FileHandler(log_file, encoding="utf-8")
    file_handler.setLevel(level)
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)
    
    return logger


# ─────────────────────────────────────────────
# HTTP / Anti-bot
# ─────────────────────────────────────────────

def get_random_headers(referer: str = "https://www.amazon.es/") -> dict:
    """
    Devuelve un dict de headers HTTP con User-Agent aleatorio
    y cabeceras realistas para simular un navegador real.
    """
    ua = random.choice(USER_AGENTS)
    return {
        "User-Agent": ua,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Accept-Language": "es-ES,es;q=0.9,en;q=0.5",
        "Accept-Encoding": "gzip, deflate, br",
        "Referer": referer,
        "Connection": "keep-alive",
        "Upgrade-Insecure-Requests": "1",
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "same-origin",
        "Sec-Fetch-User": "?1",
        "DNT": "1",
    }


def safe_request(
    url: str,
    headers: dict | None = None,
    max_retries: int = 3,
    backoff_base: float = 2.0,
    timeout: int = 15,
    logger: logging.Logger | None = None,
) -> requests.Response | None:
    """
    Wrapper de requests.get con retry + backoff exponencial.
    
    Returns:
        Response object si éxito, None si todos los reintentos fallan.
    """
    if headers is None:
        headers = get_random_headers()
    
    log = logger or logging.getLogger("safe_request")
    
    for attempt in range(1, max_retries + 1):
        try:
            response = requests.get(url, headers=headers, timeout=timeout)
            
            if response.status_code == 200:
                return response
            
            if response.status_code == 503:
                log.warning(f"  ⚠ CAPTCHA/bot detectado (503) en intento {attempt}/{max_retries}")
            elif response.status_code == 429:
                log.warning(f"  ⚠ Rate limit (429) en intento {attempt}/{max_retries}")
            else:
                log.warning(f"  ⚠ HTTP {response.status_code} en intento {attempt}/{max_retries}")
            
            if attempt < max_retries:
                wait = backoff_base ** attempt + random.uniform(0, 1)
                log.info(f"  ⏳ Esperando {wait:.1f}s antes de reintentar...")
                time.sleep(wait)
                # Rotar headers en el reintento
                headers = get_random_headers()
                
        except requests.exceptions.Timeout:
            log.warning(f"  ⚠ Timeout en intento {attempt}/{max_retries}")
            if attempt < max_retries:
                time.sleep(backoff_base ** attempt)
                
        except requests.exceptions.ConnectionError as e:
            log.error(f"  ✗ Error de conexión en intento {attempt}/{max_retries}: {e}")
            if attempt < max_retries:
                time.sleep(backoff_base ** attempt)
                
        except requests.exceptions.RequestException as e:
            log.error(f"  ✗ Error de request: {e}")
            return None
    
    log.error(f"  ✗ Todos los reintentos fallaron para {url}")
    return None


# ─────────────────────────────────────────────
# Sesión Amazon (Anti-CAPTCHA)
# ─────────────────────────────────────────────

def create_amazon_session(
    base_url: str = "https://www.amazon.es",
    logger: logging.Logger | None = None,
) -> tuple[requests.Session, str]:
    """
    Crea una requests.Session que simula un navegador real visitando Amazon.

    Estrategia:
    1. Elige un User-Agent fijo para toda la sesión (un navegador no cambia de UA).
    2. Visita la homepage para obtener cookies de sesión (session-id, i18n-prefs, etc.).
    3. Devuelve la sesión lista para hacer búsquedas.

    Returns:
        Tupla (session, user_agent) — la sesión con cookies y el UA usado.
    """
    log = logger or logging.getLogger("amazon_session")

    session = requests.Session()
    user_agent = random.choice(USER_AGENTS)

    # Headers base consistentes para toda la sesión
    session.headers.update({
        "User-Agent": user_agent,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Accept-Language": "es-ES,es;q=0.9,en;q=0.5",
        "Accept-Encoding": "gzip, deflate, br",
        "Connection": "keep-alive",
        "Upgrade-Insecure-Requests": "1",
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "none",
        "Sec-Fetch-User": "?1",
        "DNT": "1",
    })

    # Warm-up: visitar homepage para obtener cookies
    log.info("  🌐 Warm-up: visitando Amazon.es para obtener cookies...")
    try:
        warmup_resp = session.get(base_url, timeout=15)
        cookie_names = [c.name for c in session.cookies]
        log.info(f"  🍪 Cookies obtenidas: {cookie_names}")

        if warmup_resp.status_code != 200:
            log.warning(f"  ⚠ Warm-up devolvió HTTP {warmup_resp.status_code}")
    except Exception as e:
        log.warning(f"  ⚠ Error en warm-up: {e}. Continuando sin cookies iniciales.")

    # Después del warm-up, las peticiones de búsqueda vienen "del mismo sitio"
    session.headers.update({
        "Referer": base_url + "/",
        "Sec-Fetch-Site": "same-origin",
    })

    return session, user_agent


def safe_session_request(
    session: requests.Session,
    url: str,
    max_retries: int = 3,
    backoff_base: float = 3.0,
    timeout: int = 20,
    captcha_wait_range: tuple[float, float] = (30.0, 60.0),
    logger: logging.Logger | None = None,
) -> requests.Response | None:
    """
    Petición HTTP usando una sesión existente con manejo inteligente de CAPTCHAs.

    Diferencias con safe_request():
    - Usa sesión compartida (cookies persistentes).
    - No rota UA entre reintentos (un navegador real no lo hace).
    - Ante CAPTCHA: espera 30-60s (backoff agresivo) antes de reintentar.
    - Si CAPTCHA persiste: devuelve None (la sesión se puede recrear externamente).

    Returns:
        Response object si éxito, None si todos los reintentos fallan.
    """
    log = logger or logging.getLogger("session_request")

    for attempt in range(1, max_retries + 1):
        try:
            response = session.get(url, timeout=timeout)

            # Detectar CAPTCHA antes de evaluar status code
            is_captcha = False
            if response.status_code == 200:
                body_lower = response.text[:5000].lower()  # Solo primeros 5KB para eficiencia
                if "captcha" in body_lower or "robot" in body_lower:
                    is_captcha = True

            if response.status_code == 503:
                is_captcha = True

            if is_captcha:
                wait = random.uniform(*captcha_wait_range)
                log.warning(
                    f"  🤖 CAPTCHA detectado (intento {attempt}/{max_retries}). "
                    f"Esperando {wait:.0f}s..."
                )
                if attempt < max_retries:
                    time.sleep(wait)
                    continue
                else:
                    log.error("  ✗ CAPTCHA persistente. Necesita nueva sesión.")
                    return None

            if response.status_code == 200:
                return response

            if response.status_code == 429:
                log.warning(f"  ⚠ Rate limit (429) en intento {attempt}/{max_retries}")
            else:
                log.warning(f"  ⚠ HTTP {response.status_code} en intento {attempt}/{max_retries}")

            if attempt < max_retries:
                wait = backoff_base ** attempt + random.uniform(0, 2)
                log.info(f"  ⏳ Esperando {wait:.1f}s antes de reintentar...")
                time.sleep(wait)

        except requests.exceptions.Timeout:
            log.warning(f"  ⚠ Timeout en intento {attempt}/{max_retries}")
            if attempt < max_retries:
                time.sleep(backoff_base ** attempt)

        except requests.exceptions.ConnectionError as e:
            log.error(f"  ✗ Error de conexión en intento {attempt}/{max_retries}: {e}")
            if attempt < max_retries:
                time.sleep(backoff_base ** attempt)

        except requests.exceptions.RequestException as e:
            log.error(f"  ✗ Error de request: {e}")
            return None

    log.error(f"  ✗ Todos los reintentos fallaron para {url}")
    return None


# ─────────────────────────────────────────────
# Throttling
# ─────────────────────────────────────────────

def throttle(min_sec: float = 3.0, max_sec: float = 8.0) -> None:
    """
    Pausa aleatoria entre min_sec y max_sec para simular comportamiento humano.
    Imprime el tiempo de espera para transparencia en logs.
    """
    wait = random.uniform(min_sec, max_sec)
    time.sleep(wait)
