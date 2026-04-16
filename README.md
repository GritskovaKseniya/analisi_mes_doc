# Analisi MES Doc

Strumento per indicizzare, cercare e navigare le specifiche tecniche MES (Manufacturing Execution System) in formato Word `.docx`.

## Problema

Le specifiche MES sono distribuite su ~27 documenti Word, alcuni con oltre 14.000 paragrafi. Trovare un parametro di configurazione o capire come funziona una funzionalità richiede ore di ricerca manuale.

## Soluzione

Pipeline che estrae il contenuto strutturato (sezioni, paragrafi, tabelle, parametri di configurazione) e lo indicizza in un database SQLite interrogabile. In futuro: ricerca semantica e assistente RAG con Ollama.

## Architettura

```
Documenti .docx (rete)
        │
        ▼
  Extraction layer     ← python-docx, regole in rules.yaml
  (headings, paragrafi,
   tabelle, parametri)
        │
        ▼
   SQLite (mes_docs.db) ← storage principale, FTS5 full-text search
        │
        ├──► JSON export
        └──► Query / Search CLI
                │
                ▼
          Ollama RAG        ← modello locale leggero (futuro)
```

## Stato del progetto

| Step | Descrizione | Stato |
|------|-------------|-------|
| 0 | Script ispezione struttura documenti | ✅ |
| 1 | Setup + `rules.yaml` configurabile | ✅ |
| 2 | Extraction pipeline (un file → SQLite) | ⬜ |
| 3 | Salvataggio SQLite schema completo | ⬜ |
| 4 | Rilevamento parametri CHIAVE=VALORE | ⬜ |
| 5 | Pipeline completa tutti i documenti | ⬜ |
| 6 | Ricerca FTS5 da terminale | ⬜ |
| 7 | RAG con Ollama | ⬜ |

## File

| File | Descrizione |
|------|-------------|
| `inspect_doc.py` | Step 0 — ispeziona struttura reale di un `.docx` |
| `rules.yaml` | Configurazione: file sorgente, pattern parametri, opzioni DB |
| `truth_table.csv` | Dataset di verità per misurare precision del rilevamento parametri |
| `drp_progetto.md` | Documento di riferimento del progetto (architettura, decisioni, piano) |

## Uso rapido

```bash
pip install python-docx

# Statistiche su un documento
python inspect_doc.py "path/al/file.docx" --stats

# Mostra i parametri rilevati con confidenza
python inspect_doc.py "path/al/file.docx" --params

# Mostra paragrafi che contengono una parola chiave
python inspect_doc.py "path/al/file.docx" --search "WMS_ABIL"

# Mostra solo i titoli (Heading 1)
python inspect_doc.py "path/al/file.docx" --style "Heading 1"

# Mostra struttura tabelle
python inspect_doc.py "path/al/file.docx" --tables --limit 10
```

## Configurazione

Modifica `rules.yaml` per:
- Aggiungere/rimuovere documenti sorgente (sezione `sources`)
- Cambiare i pattern di rilevamento parametri (sezione `parameter_patterns`)
- Impostare il path del database di output (sezione `database`)

## Rilevamento parametri — precision baseline

Sul campione `truth_table.csv` (25 righe, etichette manuali):

| Confidenza | Campioni | Precision stimata |
|------------|----------|-------------------|
| HIGH | 14 | 71% (target: >85% dopo fix) |
| MEDIUM | 2 | 100% |
| LOW | 3 | 67% |

Falsi positivi HIGH noti: query SQL (`SELECT/WHERE`), dati ambiente test (`radaid`, `jas`).

## Dipendenze

```
python-docx
pyyaml       # per leggere rules.yaml nella pipeline (Step 2+)
```

## Stack previsto

| Layer | Tecnologia |
|-------|------------|
| Parsing | python-docx |
| Storage | SQLite + FTS5 |
| Config | YAML |
| AI locale | Ollama (llama3.2 / phi3) |
| UI (futuro) | Streamlit |
