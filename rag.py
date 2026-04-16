"""
rag.py — Step 7: assistente RAG sui documenti MES via Ollama

Uso:
    python rag.py "come si configura il versamento a matricola?"
    python rag.py "cosa fa WMS_ABIL_GIACENZE_SU_UMV?"
    python rag.py "differenza tra macchina e postazione in Fontana"
    python rag.py --interactive          # modalità chat continua
    python rag.py --model llama3.2       # specifica modello Ollama
    python rag.py "..." --top-k 8        # quanti chunk recuperare (default 5)
    python rag.py "..." --show-context   # mostra i chunk usati come contesto
"""

import argparse
import io
import json
import sqlite3
import sys
import urllib.request
import urllib.error
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

DB_PATH    = "data/mes_docs.db"
OLLAMA_URL = "http://localhost:11434/api/chat"
MODEL      = "llama3.2"

# Codici ANSI
BOLD   = "\033[1m"
CYAN   = "\033[0;36m"
YELLOW = "\033[0;33m"
GREEN  = "\033[0;32m"
DIM    = "\033[2m"
RESET  = "\033[0m"

SYSTEM_PROMPT = """Sei un assistente tecnico specializzato in sistemi MES (Manufacturing Execution System) di Tecnest/JFlex.
Rispondi SOLO basandoti sui documenti di specifica forniti nel contesto.
Regole:
- Se l'informazione non è nel contesto, dì esplicitamente "Non ho questa informazione nei documenti forniti."
- Cita sempre il documento e la sezione da cui proviene ogni informazione (es: [MES_WEB_SERVIZI, Setup Base]).
- Sii preciso sui valori dei parametri di configurazione.
- Rispondi in italiano, in modo chiaro e conciso."""


# ---------------------------------------------------------------------------
# DB
# ---------------------------------------------------------------------------

def open_db() -> sqlite3.Connection:
    if not Path(DB_PATH).exists():
        print(f"DB non trovato: {DB_PATH}. Esegui: python extract.py")
        sys.exit(1)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    n = conn.execute("SELECT count(*) FROM fts_paragraphs").fetchone()[0]
    if n == 0:
        print("Indice FTS vuoto. Esegui: python extract.py --build-fts")
        sys.exit(1)
    return conn


# ---------------------------------------------------------------------------
# Retrieval
# ---------------------------------------------------------------------------

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


def build_fts_query(query: str) -> str:
    """
    Costruisce una query FTS5 da testo libero.
    - Rimuove stop words italiane e parole corte
    - Usa OR implicito tra i termini (FTS5 default) per essere meno restrittivo
    - Mantiene termini maiuscoli intatti (nomi parametro MES)
    """
    import re
    tokens = re.split(r'\s+', query.strip())
    kept = []
    for t in tokens:
        t_clean = re.sub(r'[^a-zA-Z0-9_àèìòù]', '', t).lower()
        if len(t_clean) < 3:
            continue
        if t_clean in IT_STOPWORDS:
            continue
        # Preserva underscore per nomi parametro tipo WMS_ABIL
        original = re.sub(r'[^a-zA-Z0-9_]', '', t)
        if original:
            kept.append(f'"{original}"')
    return " OR ".join(kept) if kept else ""


def retrieve(conn: sqlite3.Connection, query: str, top_k: int) -> list[dict]:
    """
    Recupera i chunk più rilevanti per la query.
    Combina:
      1. FTS5 full-text (paragrafi) con stop-word filtering
      2. Ricerca diretta nei parametri per nome (token MAIUSCOLI)
    """
    chunks: list[dict] = []
    seen_ids: set[int] = set()

    # --- FTS5 paragrafi ---
    fts_query = build_fts_query(query)
    if fts_query:
        try:
            rows = conn.execute("""
                SELECT paragraph_id, text, doc_label, doc_filename, section_title, rank
                FROM fts_paragraphs
                WHERE fts_paragraphs MATCH ?
                ORDER BY rank
                LIMIT ?
            """, (fts_query, top_k)).fetchall()

            for row in rows:
                pid = row["paragraph_id"]
                if pid not in seen_ids:
                    seen_ids.add(pid)
                    chunks.append({
                        "text":     row["text"],
                        "doc":      row["doc_filename"].replace(".docx", ""),
                        "section":  row["section_title"] or "",
                        "source":   "fts",
                    })
        except sqlite3.OperationalError as e:
            print(f"{DIM}[FTS warn: {e}]{RESET}")

    # --- Parametri per nome (cerca token MAIUSCOLI nella query) ---
    import re
    param_tokens = re.findall(r'[A-Z][A-Z0-9_]{3,}', query)
    for token in param_tokens[:3]:  # max 3 token per evitare troppo rumore
        rows = conn.execute("""
            SELECT p.name, p.value, p.confidence, p.raw_text,
                   d.filename, s.title as section_title
            FROM parameters p
            JOIN documents d ON p.document_id = d.id
            LEFT JOIN sections s ON p.section_id = s.id
            WHERE lower(p.name) LIKE ?
              AND p.confidence IN ('HIGH', 'MEDIUM')
            ORDER BY p.confidence DESC
            LIMIT 4
        """, (f"%{token.lower()}%",)).fetchall()

        for row in rows:
            text = f"{row['name']} = {row['value']}"
            if row["raw_text"] and row["raw_text"] != row["name"]:
                text = row["raw_text"]
            key = f"param:{row['name']}:{row['filename']}"
            if key not in seen_ids:
                seen_ids.add(key)
                chunks.append({
                    "text":    text,
                    "doc":     row["filename"].replace(".docx", ""),
                    "section": row["section_title"] or "",
                    "source":  "param",
                })

    return chunks[:top_k + 3]  # un po' di margine, il prompt builder taglia


# ---------------------------------------------------------------------------
# Prompt builder
# ---------------------------------------------------------------------------

def build_prompt(query: str, chunks: list[dict], max_context_chars: int = 4000) -> str:
    """Costruisce il messaggio utente con contesto embedded."""
    context_parts = []
    used_chars = 0

    for i, chunk in enumerate(chunks, 1):
        source_tag = f"[{chunk['doc']}"
        if chunk["section"]:
            source_tag += f" — {chunk['section'][:60]}"
        source_tag += "]"

        entry = f"{source_tag}\n{chunk['text']}\n"
        if used_chars + len(entry) > max_context_chars:
            break
        context_parts.append(entry)
        used_chars += len(entry)

    context = "\n".join(context_parts)

    return (
        f"Contesto dai documenti MES:\n"
        f"{'─' * 40}\n"
        f"{context}\n"
        f"{'─' * 40}\n\n"
        f"Domanda: {query}"
    )


# ---------------------------------------------------------------------------
# Ollama API
# ---------------------------------------------------------------------------

def call_ollama(model: str, system: str, user_msg: str, stream: bool = True) -> str:
    """Chiama Ollama /api/chat. Con stream=True stampa a schermo man mano."""
    payload = {
        "model":    model,
        "messages": [
            {"role": "system",  "content": system},
            {"role": "user",    "content": user_msg},
        ],
        "stream": stream,
    }
    data = json.dumps(payload).encode("utf-8")
    req  = urllib.request.Request(
        OLLAMA_URL,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    full_response = []
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            for line in resp:
                line = line.strip()
                if not line:
                    continue
                obj = json.loads(line)
                token = obj.get("message", {}).get("content", "")
                if token:
                    print(token, end="", flush=True)
                    full_response.append(token)
                if obj.get("done"):
                    break
    except urllib.error.URLError as e:
        print(f"\n{YELLOW}Errore connessione Ollama: {e}{RESET}")
        print("Assicurati che Ollama sia in esecuzione: ollama serve")
        sys.exit(1)

    print()  # newline finale
    return "".join(full_response)


# ---------------------------------------------------------------------------
# Risposta singola
# ---------------------------------------------------------------------------

def ask(conn: sqlite3.Connection, query: str, model: str,
        top_k: int, show_context: bool):

    print(f"\n{BOLD}{CYAN}Domanda:{RESET} {query}\n")

    # Retrieval
    chunks = retrieve(conn, query, top_k)

    if not chunks:
        print(f"{YELLOW}Nessun contesto trovato nel DB per questa domanda.{RESET}")
        return

    # Mostra sorgenti usate
    print(f"{DIM}Contesto recuperato da {len(chunks)} chunk:{RESET}")
    for i, c in enumerate(chunks, 1):
        src_icon = "⚙" if c["source"] == "param" else "¶"
        section_short = f" / {c['section'][:50]}" if c["section"] else ""
        print(f"  {DIM}{src_icon} {i}. {c['doc']}{section_short}{RESET}")

    if show_context:
        print(f"\n{DIM}{'─'*50}")
        for c in chunks:
            print(f"  [{c['doc']}] {c['text'][:120]}")
        print(f"{'─'*50}{RESET}")

    # Genera risposta
    user_msg = build_prompt(query, chunks)
    print(f"\n{BOLD}{GREEN}Risposta:{RESET}\n")
    call_ollama(model, SYSTEM_PROMPT, user_msg)
    print()


# ---------------------------------------------------------------------------
# Modalità interattiva
# ---------------------------------------------------------------------------

def interactive(conn: sqlite3.Connection, model: str, top_k: int):
    print(f"\n{BOLD}MES Assistant — modalità interattiva{RESET}")
    print(f"{DIM}Modello: {model} | Digita 'exit' per uscire{RESET}\n")

    while True:
        try:
            query = input(f"{CYAN}Tu:{RESET} ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nArrivederci!")
            break

        if not query:
            continue
        if query.lower() in ("exit", "quit", "esci", "q"):
            print("Arrivederci!")
            break

        ask(conn, query, model, top_k, show_context=False)


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Assistente RAG sui documenti MES",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__)

    parser.add_argument("query",    nargs="?", default=None,
                        help="Domanda in linguaggio naturale")
    parser.add_argument("--model",  default=MODEL,
                        help=f"Modello Ollama (default: {MODEL})")
    parser.add_argument("--top-k",  type=int, default=5,
                        help="Chunk da recuperare per la risposta (default: 5)")
    parser.add_argument("--show-context", action="store_true",
                        help="Mostra il testo dei chunk usati come contesto")
    parser.add_argument("--interactive", action="store_true",
                        help="Modalità chat interattiva")

    args = parser.parse_args()

    if not args.query and not args.interactive:
        parser.print_help()
        sys.exit(0)

    conn = open_db()

    if args.interactive:
        interactive(conn, args.model, args.top_k)
    else:
        ask(conn, args.query, args.model, args.top_k, args.show_context)

    conn.close()


if __name__ == "__main__":
    main()
