"""
search.py — Step 6: ricerca full-text e per parametri nel database SQLite

Uso:
    python search.py <query>                       # full-text su tutti i doc
    python search.py <query> --doc fontana         # filtra per documento
    python search.py <query> --section "setup base"# filtra per titolo sezione
    python search.py --param WMS_ABIL              # cerca nei parametri per nome
    python search.py --param WMS_ABIL --high-only  # solo parametri HIGH confidence
    python search.py <query> --limit 20            # max risultati (default 10)
    python search.py <query> --context             # mostra paragrafi vicini

Esempi:
    python search.py "versamento matricola"
    python search.py "WMS_ABIL_GIACENZE" --doc servizi
    python search.py --param "WMS_TIPO_SERVIZIO"
    python search.py "UMV" --doc fontana --limit 5
    python search.py "blocco stop" --context
"""

import argparse
import io
import sqlite3
import sys
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

DB_PATH = "data/mes_docs.db"

# Codici ANSI
BOLD   = "\033[1m"
CYAN   = "\033[0;36m"
YELLOW = "\033[0;33m"
GREEN  = "\033[0;32m"
RED    = "\033[0;31m"
DIM    = "\033[2m"
RESET  = "\033[0m"


def open_db() -> sqlite3.Connection:
    if not Path(DB_PATH).exists():
        print(f"DB non trovato: {DB_PATH}")
        print("Esegui prima: python extract.py")
        sys.exit(1)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    # Verifica FTS popolato
    n = conn.execute("SELECT count(*) FROM fts_paragraphs").fetchone()[0]
    if n == 0:
        print("Indice FTS vuoto. Esegui: python extract.py --build-fts")
        sys.exit(1)
    return conn


def highlight(text: str, query: str) -> str:
    """Evidenzia i termini della query nel testo (case-insensitive)."""
    terms = [t for t in query.split() if len(t) > 2]
    for term in terms:
        import re
        text = re.sub(f"({re.escape(term)})", f"{YELLOW}\\1{RESET}", text,
                      flags=re.IGNORECASE)
    return text


def truncate(text: str, width: int = 200) -> str:
    return text if len(text) <= width else text[:width] + "…"


# ---------------------------------------------------------------------------
# Ricerca full-text (FTS5)
# ---------------------------------------------------------------------------

def search_fulltext(conn: sqlite3.Connection, query: str,
                    doc_filter: str | None, section_filter: str | None,
                    limit: int, show_context: bool):

    # FTS5 query: ogni parola è un termine, più parole = AND implicito
    # Aggiungi * per prefix match sull'ultimo termine
    terms = query.strip().split()
    fts_query = " ".join(f'"{t}"' if len(t) > 2 else t for t in terms)

    sql = """
        SELECT
            f.paragraph_id,
            f.text,
            f.doc_label,
            f.doc_filename,
            f.section_title,
            rank
        FROM fts_paragraphs f
        WHERE fts_paragraphs MATCH ?
    """
    params: list = [fts_query]

    if doc_filter:
        sql += " AND (lower(f.doc_label) LIKE ? OR lower(f.doc_filename) LIKE ?)"
        params += [f"%{doc_filter.lower()}%", f"%{doc_filter.lower()}%"]

    if section_filter:
        sql += " AND lower(f.section_title) LIKE ?"
        params.append(f"%{section_filter.lower()}%")

    sql += " ORDER BY rank LIMIT ?"
    params.append(limit)

    try:
        rows = conn.execute(sql, params).fetchall()
    except sqlite3.OperationalError as e:
        print(f"{RED}Errore query FTS: {e}{RESET}")
        print(f"Query usata: {fts_query!r}")
        print("Suggerimento: per frasi esatte usa virgolette, es: python search.py '\"versamento matricola\"'")
        return

    if not rows:
        print(f"  Nessun risultato per: {query!r}")
        if doc_filter:
            print(f"  (filtro documento: {doc_filter!r})")
        return

    print(f"\n{BOLD}  {len(rows)} risultati per: {query!r}{RESET}")
    if doc_filter:
        print(f"  {DIM}filtro documento: {doc_filter!r}{RESET}")
    if section_filter:
        print(f"  {DIM}filtro sezione: {section_filter!r}{RESET}")
    print()

    for i, row in enumerate(rows, 1):
        doc_short = row["doc_filename"].replace(".docx", "").replace(".r0", " r0")
        section = row["section_title"] or "(nessuna sezione)"

        print(f"  {CYAN}{i:>3}.{RESET}  {BOLD}{doc_short}{RESET}")
        print(f"        {DIM}sezione: {truncate(section, 70)}{RESET}")
        text_hl = highlight(truncate(row["text"], 180), query)
        print(f"        {text_hl}")

        if show_context:
            # Mostra paragrafi adiacenti
            pid = row["paragraph_id"]
            neighbors = conn.execute("""
                SELECT text FROM paragraphs
                WHERE id IN (?, ?)
                AND length(text) > 5
            """, (pid - 1, pid + 1)).fetchall()
            if neighbors:
                print(f"        {DIM}--- contesto ---{RESET}")
                for nb in neighbors:
                    print(f"        {DIM}{truncate(nb['text'], 120)}{RESET}")

        print()


# ---------------------------------------------------------------------------
# Ricerca parametri
# ---------------------------------------------------------------------------

def search_params(conn: sqlite3.Connection, name_query: str,
                  doc_filter: str | None, high_only: bool, limit: int):

    sql = """
        SELECT
            p.name, p.value, p.confidence, p.raw_text,
            d.label as doc_label, d.filename,
            s.title as section_title
        FROM parameters p
        JOIN documents d ON p.document_id = d.id
        LEFT JOIN sections s ON p.section_id = s.id
        WHERE lower(p.name) LIKE ?
    """
    params: list = [f"%{name_query.lower()}%"]

    if doc_filter:
        sql += " AND (lower(d.label) LIKE ? OR lower(d.filename) LIKE ?)"
        params += [f"%{doc_filter.lower()}%", f"%{doc_filter.lower()}%"]

    if high_only:
        sql += " AND p.confidence = 'HIGH'"

    sql += " ORDER BY p.confidence DESC, d.filename, p.name LIMIT ?"
    params.append(limit)

    rows = conn.execute(sql, params).fetchall()

    if not rows:
        print(f"  Nessun parametro trovato per: {name_query!r}")
        return

    conf_color = {"HIGH": GREEN, "MEDIUM": YELLOW, "LOW": RED}

    print(f"\n{BOLD}  {len(rows)} parametri per: {name_query!r}{RESET}")
    if high_only:
        print(f"  {DIM}(solo HIGH confidence){RESET}")
    print()

    current_doc = None
    for row in rows:
        if row["filename"] != current_doc:
            current_doc = row["filename"]
            doc_short = current_doc.replace(".docx", "").replace(".r0", " r0")
            print(f"  {BOLD}{CYAN}[ {doc_short} ]{RESET}")

        cc = conf_color.get(row["confidence"], "")
        name_padded = row["name"][:45].ljust(45)
        val_padded  = str(row["value"])[:20].ljust(20)
        section = row["section_title"] or ""

        print(f"    {cc}{row['confidence']:<6}{RESET}  "
              f"{BOLD}{name_padded}{RESET} = {val_padded}  "
              f"{DIM}{truncate(section, 50)}{RESET}")
        if row["raw_text"] and row["raw_text"] != row["name"]:
            raw = truncate(row["raw_text"], 100)
            print(f"             {DIM}raw: {raw}{RESET}")

    print()


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Cerca nel database MES docs",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__)

    parser.add_argument("query", nargs="?", default=None,
                        help="Testo da cercare (full-text)")
    parser.add_argument("--param",   default=None,
                        help="Cerca per nome parametro (es: WMS_ABIL)")
    parser.add_argument("--doc",     default=None,
                        help="Filtra per nome documento (parziale)")
    parser.add_argument("--section", default=None,
                        help="Filtra per titolo sezione (parziale)")
    parser.add_argument("--limit",   type=int, default=10,
                        help="Max risultati (default: 10)")
    parser.add_argument("--high-only", action="store_true",
                        help="Solo parametri HIGH confidence (con --param)")
    parser.add_argument("--context", action="store_true",
                        help="Mostra paragrafi adiacenti al risultato")

    args = parser.parse_args()

    if not args.query and not args.param:
        parser.print_help()
        sys.exit(0)

    conn = open_db()

    if args.param:
        search_params(conn, args.param, args.doc, args.high_only, args.limit)

    if args.query:
        search_fulltext(conn, args.query, args.doc, args.section, args.limit, args.context)

    conn.close()


if __name__ == "__main__":
    main()
