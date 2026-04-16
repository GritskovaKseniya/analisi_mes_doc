"""
app.py — Streamlit UI per la knowledge base MES

Avvio:
    streamlit run app.py
"""

import io
import json
import re
import sqlite3
import urllib.error
import urllib.request
from pathlib import Path

import streamlit as st

# ---------------------------------------------------------------------------
# Configurazione pagina
# ---------------------------------------------------------------------------

st.set_page_config(
    page_title="MES Knowledge Base",
    page_icon="🏭",
    layout="wide",
    initial_sidebar_state="expanded",
)

DB_PATH    = "data/mes_docs.db"
OLLAMA_URL = "http://localhost:11434/api/chat"
MODEL      = "llama3.2"

IT_STOPWORDS = {
    "come", "cosa", "quando", "dove", "perche", "chi", "che", "con", "per",
    "del", "della", "delle", "dei", "degli", "nel", "nella", "nelle", "nei",
    "sul", "sulla", "sulle", "sui", "dal", "dalla", "dalle", "dai", "tra",
    "fra", "una", "uno", "gli", "all", "allo", "alla", "alle", "agli",
    "non", "mai", "anche", "solo", "poi", "piu", "molto", "poco", "suo",
    "sua", "suoi", "sue", "loro", "questo", "questa", "questi", "queste",
    "quello", "quella", "quelli", "quelle", "sono", "siamo", "avere", "fare",
    "viene", "vengono", "essere", "stato", "stata", "stati", "state",
    "funziona", "funzionano", "differenza", "gestione",
}

SYSTEM_PROMPT = """Sei un assistente tecnico specializzato in sistemi MES (Manufacturing Execution System) di Tecnest/JFlex.
Rispondi SOLO basandoti sui documenti di specifica forniti nel contesto.
Regole:
- Se l'informazione non è nel contesto, dì "Non ho questa informazione nei documenti forniti."
- Cita sempre il documento e la sezione da cui proviene ogni informazione.
- Sii preciso sui valori dei parametri di configurazione.
- Rispondi in italiano, in modo chiaro e conciso."""


# ---------------------------------------------------------------------------
# DB — cached
# ---------------------------------------------------------------------------

@st.cache_resource
def get_db() -> sqlite3.Connection:
    if not Path(DB_PATH).exists():
        return None
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def db_ok(conn) -> bool:
    if conn is None:
        return False
    try:
        conn.execute("SELECT 1 FROM fts_paragraphs LIMIT 1")
        return True
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Helpers ricerca
# ---------------------------------------------------------------------------

def build_fts_query(query: str) -> str:
    tokens = re.split(r'\s+', query.strip())
    kept = []
    for t in tokens:
        t_clean = re.sub(r'[^a-zA-Z0-9_àèìòù]', '', t).lower()
        if len(t_clean) < 3 or t_clean in IT_STOPWORDS:
            continue
        original = re.sub(r'[^a-zA-Z0-9_]', '', t)
        if original:
            kept.append(f'"{original}"')
    return " OR ".join(kept)


def highlight_text(text: str, query: str) -> str:
    terms = [t for t in re.split(r'\s+', query) if len(t) > 2
             and t.lower() not in IT_STOPWORDS]
    for term in terms:
        text = re.sub(f"({re.escape(term)})", r"**\1**", text, flags=re.IGNORECASE)
    return text


def doc_short(filename: str) -> str:
    return filename.replace(".docx", "").replace(".r0", " r0")


# ---------------------------------------------------------------------------
# Sidebar
# ---------------------------------------------------------------------------

with st.sidebar:
    st.title("🏭 MES Knowledge Base")
    st.caption("Specifiche tecniche MES — Tecnest/JFlex")
    st.divider()

    conn = get_db()
    if db_ok(conn):
        n_docs  = conn.execute("SELECT count(*) FROM documents").fetchone()[0]
        n_para  = conn.execute("SELECT sum(paragraphs_n) FROM documents").fetchone()[0] or 0
        n_param = conn.execute("SELECT sum(parameters_n) FROM documents").fetchone()[0] or 0
        st.metric("Documenti", n_docs)
        st.metric("Paragrafi", f"{n_para:,}")
        st.metric("Parametri", f"{n_param:,}")
    else:
        st.error("DB non trovato. Esegui: `python extract.py`")

    st.divider()
    st.caption("Steps completati: 0→7 ✅")
    st.caption("Prossimo: embedding semantico")


# ---------------------------------------------------------------------------
# Tab principali
# ---------------------------------------------------------------------------

tab_cerca, tab_params, tab_docs, tab_rag = st.tabs([
    "🔍 Cerca", "⚙️ Parametri", "📚 Documenti", "🤖 Assistente"
])


# ============================================================
# TAB 1 — CERCA (full-text)
# ============================================================

with tab_cerca:
    st.header("Ricerca full-text")

    col_q, col_doc, col_lim = st.columns([3, 2, 1])
    with col_q:
        query = st.text_input("Testo da cercare", placeholder='es: "versamento matricola"',
                              key="ft_query")
    with col_doc:
        all_docs = []
        if db_ok(conn):
            all_docs = [r[0] for r in conn.execute(
                "SELECT label FROM documents ORDER BY label")]
        doc_filter = st.selectbox("Filtra documento", ["(tutti)"] + all_docs,
                                  key="ft_doc")
    with col_lim:
        limit = st.number_input("Max risultati", min_value=5, max_value=50,
                                value=10, key="ft_limit")

    show_ctx = st.checkbox("Mostra contesto (paragrafi vicini)", value=False)

    if query:
        fts_q = build_fts_query(query)
        if not fts_q:
            st.warning("Query troppo generica — prova parole più specifiche.")
        elif db_ok(conn):
            sql = """
                SELECT paragraph_id, text, doc_label, doc_filename, section_title, rank
                FROM fts_paragraphs
                WHERE fts_paragraphs MATCH ?
            """
            params = [fts_q]
            if doc_filter != "(tutti)":
                sql += " AND doc_label = ?"
                params.append(doc_filter)
            sql += " ORDER BY rank LIMIT ?"
            params.append(int(limit))

            try:
                rows = conn.execute(sql, params).fetchall()
            except sqlite3.OperationalError as e:
                st.error(f"Errore FTS: {e}")
                rows = []

            if not rows:
                st.info("Nessun risultato. Prova parole diverse o rimuovi il filtro documento.")
            else:
                st.caption(f"{len(rows)} risultati per: *{query}*")
                for row in rows:
                    section = row["section_title"] or "—"
                    with st.expander(
                        f"📄 **{doc_short(row['doc_filename'])}** — {section[:70]}",
                        expanded=True
                    ):
                        hl = highlight_text(row["text"], query)
                        st.markdown(hl)

                        if show_ctx:
                            pid = row["paragraph_id"]
                            neighbors = conn.execute("""
                                SELECT text FROM paragraphs
                                WHERE id IN (?, ?) AND length(text) > 5
                            """, (pid - 1, pid + 1)).fetchall()
                            if neighbors:
                                st.divider()
                                st.caption("Contesto:")
                                for nb in neighbors:
                                    st.caption(nb["text"][:200])


# ============================================================
# TAB 2 — PARAMETRI
# ============================================================

with tab_params:
    st.header("Parametri di configurazione")

    col_pq, col_pdoc, col_conf = st.columns([3, 2, 1])
    with col_pq:
        p_query = st.text_input("Nome parametro", placeholder="es: WMS_ABIL",
                                key="p_query")
    with col_pdoc:
        p_doc = st.selectbox("Filtra documento", ["(tutti)"] + all_docs,
                             key="p_doc")
    with col_conf:
        p_conf = st.selectbox("Confidenza", ["HIGH + MEDIUM", "HIGH only", "Tutti"],
                              key="p_conf")

    p_limit = st.slider("Max risultati", 10, 100, 30, key="p_limit")

    conf_map = {
        "HIGH only":      ("HIGH",),
        "HIGH + MEDIUM":  ("HIGH", "MEDIUM"),
        "Tutti":          ("HIGH", "MEDIUM", "LOW"),
    }
    conf_filter = conf_map[p_conf]

    if p_query and db_ok(conn):
        placeholders = ",".join("?" * len(conf_filter))
        sql = f"""
            SELECT p.name, p.value, p.confidence, p.raw_text,
                   d.label as doc_label, d.filename,
                   s.title as section_title
            FROM parameters p
            JOIN documents d ON p.document_id = d.id
            LEFT JOIN sections s ON p.section_id = s.id
            WHERE lower(p.name) LIKE ?
              AND p.confidence IN ({placeholders})
        """
        params = [f"%{p_query.lower()}%", *conf_filter]
        if p_doc != "(tutti)":
            sql += " AND d.label = ?"
            params.append(p_doc)
        sql += " ORDER BY p.confidence DESC, d.filename, p.name LIMIT ?"
        params.append(p_limit)

        rows = conn.execute(sql, params).fetchall()

        if not rows:
            st.info("Nessun parametro trovato.")
        else:
            st.caption(f"{len(rows)} occorrenze per *{p_query}*")

            # Raggruppa per documento
            by_doc: dict[str, list] = {}
            for row in rows:
                by_doc.setdefault(row["filename"], []).append(row)

            conf_badge = {"HIGH": "🟢", "MEDIUM": "🟡", "LOW": "🔴"}

            for filename, doc_rows in by_doc.items():
                st.subheader(f"📄 {doc_short(filename)}", divider="gray")
                for row in doc_rows:
                    badge  = conf_badge.get(row["confidence"], "⚪")
                    section = row["section_title"] or "—"
                    col_n, col_v, col_s = st.columns([3, 2, 3])
                    with col_n:
                        st.code(row["name"], language=None)
                    with col_v:
                        st.markdown(f"`= {row['value']}`")
                    with col_s:
                        st.caption(f"{badge} {row['confidence']} · {section[:50]}")
                    if row["raw_text"] and row["raw_text"] != row["name"]:
                        st.caption(f"↳ _{row['raw_text'][:120]}_")
    else:
        if db_ok(conn):
            # Mostra i parametri più frequenti come overview
            st.caption("Parametri HIGH più frequenti:")
            top = conn.execute("""
                SELECT name, count(*) as n
                FROM parameters WHERE confidence='HIGH'
                GROUP BY name ORDER BY n DESC LIMIT 20
            """).fetchall()
            cols = st.columns(4)
            for i, row in enumerate(top):
                cols[i % 4].metric(row["name"][:30], f"×{row['n']}")


# ============================================================
# TAB 3 — DOCUMENTI
# ============================================================

with tab_docs:
    st.header("Documenti indicizzati")

    if db_ok(conn):
        docs = conn.execute("""
            SELECT filename, label, revision, tags,
                   paragraphs_n, tables_n, parameters_n, extracted_at
            FROM documents ORDER BY paragraphs_n DESC
        """).fetchall()

        # Totali
        tot_p = sum(r["paragraphs_n"] for r in docs)
        tot_t = sum(r["tables_n"] for r in docs)
        tot_par = sum(r["parameters_n"] for r in docs)
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Documenti", len(docs))
        c2.metric("Paragrafi totali", f"{tot_p:,}")
        c3.metric("Tabelle totali", f"{tot_t:,}")
        c4.metric("Parametri totali", f"{tot_par:,}")
        st.divider()

        # Tabella
        table_data = []
        for r in docs:
            tags = r["tags"].strip("[]").replace("'", "") if r["tags"] else ""
            table_data.append({
                "File": doc_short(r["filename"]),
                "Label": r["label"] or "",
                "Rev": r["revision"] or "",
                "Paragrafi": r["paragraphs_n"],
                "Tabelle": r["tables_n"],
                "Parametri": r["parameters_n"],
                "Tag": tags,
            })
        st.dataframe(table_data, use_container_width=True, hide_index=True)

        # Explorer sezioni di un documento
        st.divider()
        st.subheader("Explorer sezioni")
        doc_sel = st.selectbox(
            "Seleziona documento",
            options=[r["filename"] for r in docs],
            format_func=doc_short,
            key="doc_exp"
        )
        if doc_sel:
            doc_id = conn.execute(
                "SELECT id FROM documents WHERE filename=?", (doc_sel,)
            ).fetchone()["id"]
            sections = conn.execute("""
                SELECT level, title, id FROM sections
                WHERE document_id=? AND title != ''
                ORDER BY order_index
            """, (doc_id,)).fetchall()
            if sections:
                for s in sections:
                    indent = "　" * (s["level"] - 1)
                    prefix = ["▌", "▸", "·", "·", "·"][min(s["level"] - 1, 4)]
                    st.markdown(
                        f"{indent}{prefix} {'**' if s['level']==1 else ''}"
                        f"{s['title'][:100]}{'**' if s['level']==1 else ''}"
                    )
            else:
                st.info("Nessuna sezione strutturata trovata in questo documento.")


# ============================================================
# TAB 4 — ASSISTENTE RAG
# ============================================================

with tab_rag:
    st.header("🤖 Assistente MES")
    st.caption(f"Modello: `{MODEL}` · Risponde solo dai documenti indicizzati")

    if "messages" not in st.session_state:
        st.session_state.messages = []

    def retrieve_chunks(query: str, top_k: int = 5) -> list[dict]:
        chunks = []
        seen = set()
        fts_q = build_fts_query(query)
        if fts_q and db_ok(conn):
            try:
                rows = conn.execute("""
                    SELECT paragraph_id, text, doc_filename, section_title, rank
                    FROM fts_paragraphs
                    WHERE fts_paragraphs MATCH ?
                    ORDER BY rank LIMIT ?
                """, (fts_q, top_k)).fetchall()
                for row in rows:
                    if row["paragraph_id"] not in seen:
                        seen.add(row["paragraph_id"])
                        chunks.append({
                            "text": row["text"],
                            "doc":  doc_short(row["doc_filename"]),
                            "section": row["section_title"] or "",
                        })
            except sqlite3.OperationalError:
                pass

        # Parametri espliciti nella query
        param_tokens = re.findall(r'[A-Z][A-Z0-9_]{3,}', query)
        for token in param_tokens[:3]:
            rows = conn.execute("""
                SELECT p.name, p.value, p.raw_text, d.filename, s.title
                FROM parameters p
                JOIN documents d ON p.document_id=d.id
                LEFT JOIN sections s ON p.section_id=s.id
                WHERE lower(p.name) LIKE ? AND p.confidence IN ('HIGH','MEDIUM')
                ORDER BY p.confidence DESC LIMIT 3
            """, (f"%{token.lower()}%",)).fetchall()
            for row in rows:
                key = f"{row['name']}:{row['filename']}"
                if key not in seen:
                    seen.add(key)
                    chunks.append({
                        "text": row["raw_text"] or f"{row['name']} = {row['value']}",
                        "doc": doc_short(row["filename"]),
                        "section": row[4] or "",
                    })

        return chunks[:top_k + 2]

    def build_context(query: str, chunks: list[dict]) -> str:
        parts = []
        used = 0
        for c in chunks:
            tag = f"[{c['doc']}" + (f" — {c['section'][:50]}" if c["section"] else "") + "]"
            entry = f"{tag}\n{c['text']}\n"
            if used + len(entry) > 4000:
                break
            parts.append(entry)
            used += len(entry)
        return "\n".join(parts)

    def ask_ollama_stream(context: str, question: str):
        user_msg = (
            f"Contesto dai documenti MES:\n{'─'*40}\n{context}\n{'─'*40}\n\n"
            f"Domanda: {question}"
        )
        payload = {
            "model": MODEL,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user",   "content": user_msg},
            ],
            "stream": True,
        }
        data = json.dumps(payload).encode("utf-8")
        req  = urllib.request.Request(
            OLLAMA_URL, data=data,
            headers={"Content-Type": "application/json"}, method="POST"
        )
        try:
            with urllib.request.urlopen(req, timeout=120) as resp:
                for line in resp:
                    line = line.strip()
                    if not line:
                        continue
                    obj = json.loads(line)
                    token = obj.get("message", {}).get("content", "")
                    if token:
                        yield token
                    if obj.get("done"):
                        break
        except urllib.error.URLError as e:
            yield f"\n⚠️ Errore connessione Ollama: {e}"

    # Mostra cronologia
    for msg in st.session_state.messages:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])
            if msg.get("sources"):
                with st.expander("📎 Fonti usate", expanded=False):
                    for s in msg["sources"]:
                        section = f" / {s['section'][:50]}" if s["section"] else ""
                        st.caption(f"· {s['doc']}{section}")

    # Input
    if prompt := st.chat_input("Fai una domanda sui documenti MES..."):
        st.session_state.messages.append({"role": "user", "content": prompt})
        with st.chat_message("user"):
            st.markdown(prompt)

        with st.chat_message("assistant"):
            if not db_ok(conn):
                st.error("DB non disponibile.")
            else:
                chunks = retrieve_chunks(prompt)
                if not chunks:
                    answer = "Non ho trovato informazioni rilevanti nei documenti per questa domanda."
                    st.markdown(answer)
                else:
                    context = build_context(prompt, chunks)
                    # Stream della risposta
                    answer = st.write_stream(ask_ollama_stream(context, prompt))

                st.session_state.messages.append({
                    "role": "assistant",
                    "content": answer,
                    "sources": chunks if chunks else [],
                })
                # Mostra fonti sotto la risposta
                if chunks:
                    with st.expander("📎 Fonti usate", expanded=False):
                        for c in chunks:
                            section = f" / {c['section'][:50]}" if c["section"] else ""
                            st.caption(f"· {c['doc']}{section}")

    if st.session_state.messages:
        if st.button("🗑️ Cancella conversazione"):
            st.session_state.messages = []
            st.rerun()
