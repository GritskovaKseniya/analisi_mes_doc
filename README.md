# MES Knowledge Base

Piattaforma per indicizzare, cercare e navigare le specifiche tecniche MES (Manufacturing Execution System) in formato Word `.docx`.

## Problema

Le specifiche MES sono distribuite su 28 documenti Word, alcuni con oltre 14.000 paragrafi. Trovare un parametro di configurazione o capire come funziona una funzionalità richiede ore di ricerca manuale.

## Soluzione

Pipeline che estrae il contenuto strutturato (sezioni, paragrafi, tabelle, parametri) e lo indicizza in SQLite. Interfaccia web con ricerca full-text, browser parametri e assistente AI locale (Ollama).

## Architettura

```
Documenti .docx (rete)
        │
        ▼
  extract.py          ← python-docx + rules.yaml
  (heading, paragrafi,
   tabelle, parametri)
        │
        ▼
  SQLite mes_docs.db  ← FTS5 full-text search
        │
        ├──► search.py   (CLI ricerca)
        ├──► rag.py       (CLI assistente)
        └──► app.py       (Streamlit UI)
                │
                ▼
          Ollama (llama3.2) — RAG locale, nessun dato esterno
```

## Stato del progetto

| Step | Descrizione | Stato |
|------|-------------|-------|
| 0 | Script ispezione struttura documenti (`inspect_doc.py`) | ✅ |
| 1 | Setup + `rules.yaml` configurabile | ✅ |
| 2-4 | Extraction pipeline → SQLite + rilevamento parametri | ✅ |
| 5 | Pipeline completa su tutti i 28 documenti | ✅ |
| 6 | Ricerca FTS5 da terminale (`search.py`) | ✅ |
| 7 | Assistente RAG con Ollama (`rag.py`) | ✅ |
| 8 | Streamlit UI — 4 tab (Cerca, Parametri, Documenti, Assistente) | ✅ |

## Dati indicizzati

| | |
|---|---|
| Documenti | **28** |
| Paragrafi | **36.043** |
| Sezioni | **1.888** |
| Parametri rilevati | **1.386** |
| Righe FTS indicizzate | **35.883** |

## Installazione

```bash
# Clona il repo
git clone https://github.com/GritskovaKseniya/analisi_mes_doc.git
cd analisi_mes_doc

# Installa tutto (dipendenze + Ollama + modello + indicizzazione)
python setup.py
```

Oppure manualmente:

```bash
pip install python-docx pyyaml streamlit

# Installa Ollama da https://ollama.com, poi:
ollama pull llama3.2

# Indicizza i documenti
python extract.py

# Avvia la UI
streamlit run app.py
```

## Comandi disponibili

### UI web
```bash
streamlit run app.py          # apre http://localhost:8501
```

### Ricerca da terminale
```bash
python search.py "versamento matricola"
python search.py "blocco stop" --doc fontana --context
python search.py --param "WMS_TIPO" --high-only
python search.py "UMV" --section "setup base" --limit 20
```

### Assistente AI
```bash
python rag.py "come si configura il versamento a matricola?"
python rag.py "cosa fa WMS_ABIL_GIACENZE_SU_UMV?"
python rag.py --interactive          # modalità chat continua
```

### Pipeline estrazione
```bash
python extract.py                    # (ri)indicizza tutti i documenti
python extract.py --only "Fontana"   # solo un documento
python extract.py --build-fts        # rebuild indice FTS senza riestrarre
python extract.py --dry-run          # simula senza scrivere
```

### Ispezione documenti
```bash
python inspect_doc.py "path/file.docx" --stats
python inspect_doc.py "path/file.docx" --params
python inspect_doc.py "path/file.docx" --search "WMS_ABIL"
python inspect_doc.py "path/file.docx" --style "Heading 1"
```

## Configurazione

Modifica `rules.yaml` per:
- Aggiungere/rimuovere documenti sorgente (`sources`)
- Cambiare i pattern di rilevamento parametri (`parameter_patterns`)
- Impostare path DB e strategia revisioni (`database`)

```yaml
# Esempio: aggiungere un nuovo documento
sources:
  - path: "NUOVO_CLIENTE/nuovo_doc.r01.docx"
    label: "Nuovo Doc"
    tags: [cliente, modulo]
```

## Rilevamento parametri — precision baseline

Sul campione `truth_table.csv` (25 righe, etichette manuali):

| Confidenza | Campioni | Precision stimata |
|------------|----------|-------------------|
| HIGH | 14 | 71% (migliorabile con blacklist SQL/test) |
| MEDIUM | 2 | 100% |
| LOW | 3 | 67% |

Falsi positivi HIGH noti: contesto SQL (`SELECT/WHERE`), dati ambiente test (`radaid`, `jas`).

## File del progetto

| File | Descrizione |
|------|-------------|
| `app.py` | Streamlit UI — 4 tab: Cerca, Parametri, Documenti, Assistente |
| `extract.py` | Pipeline estrazione `.docx` → SQLite + FTS5 |
| `search.py` | Ricerca full-text e per parametri da terminale |
| `rag.py` | Assistente RAG con Ollama |
| `inspect_doc.py` | Ispezione struttura documenti (step 0) |
| `rules.yaml` | Configurazione sorgenti, pattern, DB |
| `setup.py` | Script installazione one-shot |
| `truth_table.csv` | Dataset verità per validazione precision |
| `drp_progetto.md` | Documento di riferimento architettura e decisioni |

## Stack

| Layer | Tecnologia |
|-------|------------|
| Parsing | python-docx |
| Storage | SQLite + FTS5 |
| Config | YAML |
| Ricerca | SQLite FTS5 (BM25) |
| AI locale | Ollama — llama3.2 |
| UI | Streamlit |
| Linguaggio | Python 3.10+ |

## Requisiti

- Python 3.10+
- Accesso alla share di rete `\\rete-ud-2\Documents\eDox\...`
- [Ollama](https://ollama.com) installato (per l'assistente AI)
- ~2 GB disco per il modello `llama3.2`
