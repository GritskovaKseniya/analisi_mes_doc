"""
setup.py — Installazione e configurazione completa dell'ambiente MES Knowledge Base

Esegui una volta sola su un nuovo server/PC:
    python setup.py

Cosa fa:
  1. Verifica versione Python (>= 3.10)
  2. Installa le dipendenze pip
  3. Verifica/installa Ollama
  4. Scarica il modello llama3.2
  5. Crea le cartelle necessarie (data/, export/)
  6. Verifica accesso alla share di rete
  7. Esegue l'indicizzazione completa (extract.py)
  8. Mostra come avviare la UI

Opzioni:
    python setup.py --skip-ollama     # salta installazione Ollama/modello
    python setup.py --skip-index      # salta indicizzazione (solo dipendenze)
    python setup.py --check           # solo verifica stato, nessuna installazione
"""

import argparse
import importlib
import io
import os
import platform
import shutil
import subprocess
import sys
import urllib.request
from pathlib import Path

# ---------------------------------------------------------------------------
# Output helpers
# ---------------------------------------------------------------------------

WIDTH = 60

class C:
    OK    = "\033[0;32m✓\033[0m"
    FAIL  = "\033[0;31m✗\033[0m"
    WARN  = "\033[0;33m!\033[0m"
    INFO  = "\033[0;36m·\033[0m"
    BOLD  = "\033[1m"
    RESET = "\033[0m"

# Windows: abilita ANSI
if platform.system() == "Windows":
    os.system("")

def ok(msg):   print(f"  {C.OK}  {msg}")
def fail(msg): print(f"  {C.FAIL}  {msg}")
def warn(msg): print(f"  {C.WARN}  {msg}")
def info(msg): print(f"  {C.INFO}  {msg}")
def section(title):
    print(f"\n{C.BOLD}{'─'*WIDTH}")
    print(f"  {title}")
    print(f"{'─'*WIDTH}{C.RESET}")

def run(cmd: list[str], capture=False) -> subprocess.CompletedProcess:
    return subprocess.run(
        cmd,
        capture_output=capture,
        text=True,
        encoding="utf-8",
        errors="replace",
    )


# ---------------------------------------------------------------------------
# Step 1 — Versione Python
# ---------------------------------------------------------------------------

def check_python() -> bool:
    section("1. Versione Python")
    major, minor = sys.version_info[:2]
    ver = f"{major}.{minor}.{sys.version_info[2]}"
    if (major, minor) < (3, 10):
        fail(f"Python {ver} — richiesto >= 3.10")
        info("Scarica da https://python.org")
        return False
    ok(f"Python {ver}")
    return True


# ---------------------------------------------------------------------------
# Step 2 — Dipendenze pip
# ---------------------------------------------------------------------------

PACKAGES = [
    ("docx",      "python-docx"),
    ("yaml",      "pyyaml"),
    ("streamlit", "streamlit"),
]

def install_deps() -> bool:
    section("2. Dipendenze Python")
    all_ok = True
    to_install = []

    for module, package in PACKAGES:
        try:
            importlib.import_module(module)
            ok(f"{package} già installato")
        except ImportError:
            warn(f"{package} non trovato — verrà installato")
            to_install.append(package)

    if to_install:
        print()
        info(f"Installazione: {' '.join(to_install)}")
        result = run([sys.executable, "-m", "pip", "install", *to_install])
        if result.returncode != 0:
            fail("Installazione pip fallita")
            all_ok = False
        else:
            ok("Dipendenze installate")

    return all_ok


# ---------------------------------------------------------------------------
# Step 3 — Ollama
# ---------------------------------------------------------------------------

OLLAMA_DOWNLOAD = {
    "Windows": "https://ollama.com/download/OllamaSetup.exe",
    "Darwin":  "https://ollama.com/download/Ollama-darwin.zip",
    "Linux":   "curl -fsSL https://ollama.com/install.sh | sh",
}
MODEL = "llama3.2"

def check_ollama() -> bool:
    return shutil.which("ollama") is not None

def ollama_running() -> bool:
    try:
        urllib.request.urlopen("http://localhost:11434", timeout=2)
        return True
    except Exception:
        return False

def install_ollama() -> bool:
    section("3. Ollama")

    if check_ollama():
        ok("ollama trovato nel PATH")
    else:
        warn("ollama non trovato")
        system = platform.system()
        url = OLLAMA_DOWNLOAD.get(system, "")
        if system == "Linux":
            info("Installazione Linux: esegui manualmente:")
            print(f"    curl -fsSL https://ollama.com/install.sh | sh")
        else:
            info(f"Scarica e installa da: {url}")
        info("Dopo l'installazione, ri-esegui setup.py")
        return False

    if not ollama_running():
        info("Avvio server Ollama...")
        if platform.system() == "Windows":
            subprocess.Popen(["ollama", "serve"],
                             creationflags=subprocess.CREATE_NEW_CONSOLE)
        else:
            subprocess.Popen(["ollama", "serve"],
                             stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL)
        import time; time.sleep(3)

    if ollama_running():
        ok("Server Ollama attivo su localhost:11434")
    else:
        warn("Server Ollama non risponde — avvialo manualmente con: ollama serve")

    return True


def pull_model() -> bool:
    section(f"4. Modello AI ({MODEL})")

    result = run(["ollama", "list"], capture=True)
    if MODEL in result.stdout:
        ok(f"Modello {MODEL} già presente")
        return True

    info(f"Download {MODEL} (~2 GB) — potrebbe richiedere qualche minuto...")
    result = run(["ollama", "pull", MODEL])
    if result.returncode == 0:
        ok(f"Modello {MODEL} scaricato")
        return True
    else:
        fail(f"Download {MODEL} fallito")
        info(f"Esegui manualmente: ollama pull {MODEL}")
        return False


# ---------------------------------------------------------------------------
# Step 4 — Cartelle e accesso rete
# ---------------------------------------------------------------------------

def setup_dirs() -> bool:
    section("5. Struttura cartelle")

    for d in ["data", "export"]:
        Path(d).mkdir(exist_ok=True)
        ok(f"Cartella {d}/")

    return True


def check_network() -> bool:
    section("6. Accesso share di rete")

    import yaml
    try:
        cfg = yaml.safe_load(open("rules.yaml", encoding="utf-8"))
        base = cfg["base_path"]
        base_path = Path(base)
    except Exception as e:
        warn(f"Impossibile leggere rules.yaml: {e}")
        return False

    if base_path.exists():
        sources = cfg.get("sources", [])
        accessible = sum(
            1 for s in sources
            if (base_path / s["path"]).exists()
        )
        ok(f"Share raggiungibile: {base}")
        ok(f"File accessibili: {accessible}/{len(sources)}")
        if accessible < len(sources):
            warn(f"{len(sources) - accessible} file non trovati — verifica il percorso in rules.yaml")
        return accessible > 0
    else:
        fail(f"Share non raggiungibile: {base}")
        info("Verifica la connessione di rete e il percorso in rules.yaml")
        return False


# ---------------------------------------------------------------------------
# Step 5 — Indicizzazione
# ---------------------------------------------------------------------------

def run_indexing() -> bool:
    section("7. Indicizzazione documenti")

    db = Path("data/mes_docs.db")
    if db.exists():
        import sqlite3
        try:
            conn = sqlite3.connect(str(db))
            n = conn.execute("SELECT count(*) FROM documents").fetchone()[0]
            conn.close()
            if n > 0:
                ok(f"DB esistente con {n} documenti — skip indicizzazione")
                info("Per reindicizzare: python extract.py  (con recreate_on_run: true)")
                return True
        except Exception:
            pass

    info("Avvio estrazione (potrebbe richiedere 1-2 minuti)...")
    result = run([sys.executable, "extract.py"])
    if result.returncode == 0:
        ok("Indicizzazione completata")
        return True
    else:
        fail("Indicizzazione fallita — controlla i log in data/extraction.log")
        return False


# ---------------------------------------------------------------------------
# Riepilogo finale
# ---------------------------------------------------------------------------

def print_summary(results: dict):
    section("Riepilogo installazione")

    all_ok = all(results.values())
    for step, status in results.items():
        if status:
            ok(step)
        else:
            fail(step)

    print()
    if all_ok:
        print(f"  {C.BOLD}✅ Setup completato con successo!{C.RESET}")
        print()
        print(f"  {C.BOLD}Avvia la UI:{C.RESET}")
        print(f"    streamlit run app.py")
        print()
        print(f"  {C.BOLD}Oppure usa da terminale:{C.RESET}")
        print(f"    python search.py \"versamento matricola\"")
        print(f"    python rag.py --interactive")
        print()
        print(f"  UI disponibile su: http://localhost:8501")
    else:
        print(f"  {C.BOLD}⚠️  Setup completato con errori — vedi i dettagli sopra.{C.RESET}")
        print(f"  Risolvi i problemi segnalati e ri-esegui: python setup.py")


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Setup MES Knowledge Base")
    parser.add_argument("--skip-ollama", action="store_true",
                        help="Salta installazione Ollama e download modello")
    parser.add_argument("--skip-index",  action="store_true",
                        help="Salta indicizzazione documenti")
    parser.add_argument("--check",       action="store_true",
                        help="Solo verifica stato, nessuna installazione")
    args = parser.parse_args()

    print(f"\n{C.BOLD}{'═'*WIDTH}")
    print(f"  MES Knowledge Base — Setup")
    print(f"  Python {sys.version.split()[0]} · {platform.system()} {platform.release()}")
    print(f"{'═'*WIDTH}{C.RESET}")

    results = {}

    # Python
    results["Python >= 3.10"] = check_python()
    if not results["Python >= 3.10"]:
        print_summary(results)
        sys.exit(1)

    # Dipendenze
    if not args.check:
        results["Dipendenze pip"] = install_deps()
    else:
        try:
            import docx, yaml, streamlit
            results["Dipendenze pip"] = True
            ok("python-docx, pyyaml, streamlit — OK")
        except ImportError as e:
            results["Dipendenze pip"] = False
            fail(f"Mancante: {e}")

    # Ollama
    if not args.skip_ollama:
        results["Ollama installato"] = install_ollama()
        if results["Ollama installato"] and not args.check:
            results[f"Modello {MODEL}"] = pull_model()
        elif args.check:
            section(f"4. Modello AI ({MODEL})")
            r = run(["ollama", "list"], capture=True) if check_ollama() else None
            if r and MODEL in r.stdout:
                ok(f"{MODEL} presente"); results[f"Modello {MODEL}"] = True
            else:
                warn(f"{MODEL} non trovato"); results[f"Modello {MODEL}"] = False
    else:
        info("Ollama: saltato (--skip-ollama)")

    # Cartelle
    if not args.check:
        results["Cartelle data/ export/"] = setup_dirs()

    # Rete
    results["Share di rete accessibile"] = check_network()

    # Indicizzazione
    if not args.skip_index and not args.check and results.get("Share di rete accessibile"):
        results["Indicizzazione documenti"] = run_indexing()
    elif args.check:
        section("7. Database")
        db = Path("data/mes_docs.db")
        if db.exists():
            import sqlite3
            conn = sqlite3.connect(str(db))
            try:
                n_docs = conn.execute("SELECT count(*) FROM documents").fetchone()[0]
                n_para = conn.execute("SELECT sum(paragraphs_n) FROM documents").fetchone()[0] or 0
                n_fts  = conn.execute("SELECT count(*) FROM fts_paragraphs").fetchone()[0]
                ok(f"DB presente: {n_docs} documenti, {n_para:,} paragrafi, {n_fts:,} FTS")
                results["Database indicizzato"] = True
            except Exception as e:
                warn(f"DB presente ma problemi: {e}")
                results["Database indicizzato"] = False
            conn.close()
        else:
            warn("DB non trovato — esegui: python extract.py")
            results["Database indicizzato"] = False

    print_summary(results)


if __name__ == "__main__":
    main()
