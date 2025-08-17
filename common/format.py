# common/format.py
from datetime import datetime

def header(vendor: str) -> str:
    now = datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")
    return f"<b>{vendor} - Estado de Incidentes</b>\n<i>{now}</i>"

def render_incidents(activos, pasados):
    lines = []
    if activos:
        lines.append("\n<b>Incidentes activos</b>")
        for i, inc in enumerate(activos, 1):
            t, s, u = inc["title"], inc["status"], inc.get("url")
            started = inc.get("started_at")
            started_s = started.strftime("%Y-%m-%d %H:%M UTC") if started else "N/D"
            line = f"{i}. <b>{s}</b> — "
            line += f'<a href="{u}">{t}</a>' if u else t
            lines.append(line + f"\n   Inicio: {started_s}")
    else:
        lines.append("\n<b>Incidentes activos</b>\n- No hay incidentes activos reportados.")

    if pasados:
        lines.append("\n<b>Incidentes últimos 15 días</b>")
        for i, inc in enumerate(pasados, 1):
            t, s, u = inc["title"], inc["status"], inc.get("url")
            st, en = inc.get("started_at"), inc.get("ended_at")
            st_s = st.strftime("%Y-%m-%d %H:%M UTC") if st else "N/D"
            en_s = en.strftime("%Y-%m-%d %H:%M UTC") if en else "N/D"
            line = f"{i}. <b>{s}</b> — "
            line += f'<a href="{u}">{t}</a>' if u else t
            lines.append(line + f"\n   Inicio: {st_s} · Fin: {en_s}")
    else:
        lines.append("\n<b>Incidentes últimos 15 días</b>\n- No hay incidentes en los últimos 15 días.")
    return "\n".join(lines)
