import re
from typing import Dict, Tuple, Optional

SUBJECT_RE = re.compile(r"^\s*Asunto\s*:\s*(.+)\s*$", re.IGNORECASE)
TITLE_RE = re.compile(r"<title>(.*?)</title>", re.IGNORECASE | re.DOTALL)
PLACEHOLDER_RE = re.compile(r"{{\s*([A-Za-z0-9_]+)\s*}}")

def load_text_template(path: str) -> Tuple[Optional[str], str]:
    """
    Devuelve (subject, body). Si no encuentra 'Asunto:', subject=None.
    """
    with open(path, "r", encoding="utf-8") as f:
        raw = f.read()
    subject = None
    lines = raw.splitlines()
    body_start = 0
    for i, line in enumerate(lines):
        m = SUBJECT_RE.match(line)
        if m:
            subject = m.group(1).strip()
            body_start = i + 1
            break
    # Salta líneas en blanco tras el asunto
    while body_start < len(lines) and lines[body_start].strip() == "":
        body_start += 1
    body = "\n".join(lines[body_start:]) if body_start < len(lines) else ""
    return subject, body

def load_html_template(path: str) -> Tuple[Optional[str], str]:
    """
    Devuelve (title_as_subject, html).
    """
    with open(path, "r", encoding="utf-8") as f:
        html = f.read()
    m = TITLE_RE.search(html)
    subject = m.group(1).strip() if m else None
    return subject, html

def render_placeholders(template: str, data: Dict[str, str]) -> str:
    """
    Sustituye {{KEY}} por data['KEY']. Si falta, lo deja tal cual.
    """
    def _rep(m):
        key = m.group(1)
        return str(data.get(key, m.group(0)))
    return PLACEHOLDER_RE.sub(_rep, template)

def wrap_codeblock(lang: str, content: str) -> str:
    """
    Envuelve el contenido en bloque de código para chats Markdown.
    Asegura que las secuencias ``` no rompan el bloque.
    """
    safe = content.replace("```", "``\u200b`")
    return f"```{lang}\n{safe}\n```"

def chunk_text(text: str, limit: int = 3900):
    """
    Trocea el texto en trozos <= limit (útil para Telegram ~4096).
    Intenta cortar en saltos de línea.
    """
    if len(text) <= limit:
        yield text
        return
    start = 0
    while start < len(text):
        end = min(start + limit, len(text))
        # intenta buscar salto de línea hacia atrás
        nl = text.rfind("\n", start, end)
        if nl == -1 or nl <= start:
            nl = end
        yield text[start:nl]
        start = nl
