# DRP — Analisi Documenti MES per JAS
> Documento di riferimento del progetto. Aggiornare man mano che si avanza.
> Ultima revisione: 2026-04-14

---

## Obiettivo

Costruire uno strumento che legga e indicizzi le specifiche tecniche MES (documenti Word su rete)
per permettere navigazione rapida, ricerca per parametro/sezione, e (in futuro) risposte in
linguaggio naturale tramite modelli AI locali (Ollama).

---

## Sorgenti dati

| File / Cartella | Note |
|---|---|
| `\\rete-ud-2\Documents\eDox\projects\095 - Servizi_Mes_per_JAS\SPECIFICHE\FONTANA\Fontana_standard.r01.docx` | Automatismi Fontana (3.567 paragrafi, 58 tabelle) |
| `\\rete-ud-2\Documents\eDox\projects\095 - Servizi_Mes_per_JAS\SPECIFICHE\MES_WEB_*.docx` | 26 file spec MES Web (il più grande: MES_WEB_SERVIZI r06, 14.720 paragrafi, 332 tabelle) |

I file da analizzare e le regole di inclusione/esclusione sono configurabili in `rules.yaml`.

---

## Architettura scelta

```
Documenti .docx (rete)
        │
        ▼
  Extraction layer       ← python-docx, regole in rules.yaml
  (heading, paragrafi,
   tabelle, parametri)
        │
        ▼
   SQLite database        ← storage principale, query SQL
  (mes_docs.db)
        │
        ├──► JSON export  ← per revisione/condivisione
        │
        └──► Search API   ← FTS5 full-text search
                │
                ▼
         Query engine      ← ricerca keyword + (futuro) embeddings
                │
                ▼
        Ollama API         ← modello leggero per RAG
        (risposta NL)
```

---

## Struttura database (schema target)

```sql
-- Documento sorgente
documents   (id, filename, full_path, revision, extracted_at)

-- Sezioni gerarchiche (heading 1, 2, 3...)
sections    (id, document_id, parent_id, level, title, order_index)

-- Contenuto testuale
paragraphs  (id, section_id, document_id, style, text, order_index)

-- Parametri di configurazione (es. WMS_ABIL_GIACENZE=1)
parameters  (id, document_id, section_id, name, value, raw_line)

-- Righe di tabelle
table_rows  (id, document_id, section_id, table_index, row_index, col_index, cell_text)

-- Indice FTS (full-text search)
fts_index   (virtual table su paragraphs + parameters)
```

---

## Piano di sviluppo (step-by-step)

### Step 1 — Setup e configurazione  ✅ (da fare)
- Struttura cartelle del progetto
- `rules.yaml` con lista file, encoding, filtri
- Dipendenze Python (`requirements.txt`)

### Step 2 — Extraction da un singolo file  ⬜
- Legge `Fontana_standard.r01.docx`
- Estrae heading, paragrafi, tabelle
- Output: stampa strutturata a console (ispezione visiva)

### Step 3 — Salvataggio in SQLite  ⬜
- Crea `mes_docs.db` con schema base
- Inserisce il contenuto del file Step 2
- Verifica con DB Browser for SQLite

### Step 4 — Rilevamento parametri CHIAVE=VALORE  ⬜
- Regex per identificare pattern `NOME_PARAMETRO = valore` nel testo libero
- Gestione parametri **tabellari**: nome in cella[0], valore in cella[1] (caso frequente nei doc MES)
- Popola tabella `parameters`
- Test: "quante configurazioni uguali tra documenti diversi?"
- **Nota:** Questo step è probabilmente più complesso del previsto. I parametri nei doc MES
  appaiono in almeno 3 forme: testo inline, tabelle 2 colonne, elenchi puntati con `nome = valore`.
  Prevedere iterazione dopo la prima ispezione visiva dei risultati.

### Step 5 — Pipeline completa su tutti i file  ⬜
- Loop su tutti i `MES_WEB_*.docx` + Fontana
- Gestione errori, log di importazione
- Statistiche finali (totale paragrafi, tabelle, parametri)

### Step 6 — Ricerca base (FTS5)  ⬜
- Virtual table SQLite FTS5
- Script di ricerca da terminale: `search.py "WMS_ABIL"`
- Output: documento, sezione, testo trovato

### Step 7 — RAG con Ollama  ⬜
- Integrazione Ollama API (modello leggero: llama3.2 o phi3)
- Pipeline: domanda → FTS5 retrieval → context → risposta LLM
- Valutazione qualità risposte

### Step 8 — (opzionale) Embedding semantico  ⬜
- Embeddings via Ollama (nomic-embed-text o simile)
- Vector search per similarità semantica
- Combinazione con FTS5 (hybrid search)

---

## Gestione aggiornamenti e revisioni dei documenti

I file usano suffissi di revisione (`r01`, `r02`, `r06`...). Quando esce una nuova versione:

### Strategia scelta: `replace` (default)

Il documento viene identificato per **nome base** (senza revisione), es. `MES_WEB_SERVIZI`.
Una nuova revisione sovrascrive la precedente nel DB. Semplice, occupa meno spazio.

**Pro:** Query semplici, nessuna duplicazione.
**Contro:** Non si può confrontare cosa è cambiato tra r06 e r07.

### Strategia alternativa: `keep_all`

Ogni revisione è un documento separato nel DB (campo `revision` nella tabella `documents`).
Configurabile in `rules.yaml → database.revision_strategy`.

**Quando usarla:** Se si vuole tracciare l'evoluzione delle specifiche nel tempo.

### Procedura di aggiornamento (modalità replace)

1. Aggiornare il path in `rules.yaml` (es. `r06` → `r07`)
2. Eseguire `extract.py` con `recreate_on_run: false`
3. L'extractor identifica il documento per nome base, cancella le righe precedenti e reinserisce
4. Il log riporta quanti paragrafi/tabelle sono cambiati

---

## Note architetturali — AI/ML

### Perché il vero lavoro è nell'estrazione, non nell'AI

I documenti MES hanno formati inconsistenti (mix Normal/Heading/ListParagraph, tabelle variabili,
parametri scritti in modi diversi). Se l'estrazione è buona, anche un modello piccolo darà
risposte utili. Se l'estrazione è rumorosa, nessun modello la salva.

**Principio:** 80% del valore viene da estrazione pulita + buona ricerca. AI è il 20% finale.

### Ruolo di Ollama

- Usato per **comprensione query** (riformulazione) e **generazione risposta** (RAG)
- Modelli suggeriti: `llama3.2:3b` o `phi3:mini` (veloci, leggeri, girano in locale)
- **NON** usato per parsing dei documenti (quello lo fa il codice)
- Architettura: RAG classico — retrieve → augment → generate

### Perché non usare Claude/GPT per tutto

- Costo per chiamata su 14.000+ paragrafi
- Latenza per uso interattivo
- Dipendenza da internet / privacy sui documenti aziendali
- Ollama locale risolve tutti e tre i problemi

---

## Struttura cartelle progetto

```
analisi_mes_doc/
├── drp_progetto.md          ← questo file
├── rules.yaml               ← configurazione (file sorgente, filtri, ecc.)
├── requirements.txt         ← dipendenze Python
├── extract.py               ← Step 2-4: extraction pipeline
├── search.py                ← Step 6: ricerca da terminale
├── rag.py                   ← Step 7: integrazione Ollama
├── data/
│   └── mes_docs.db          ← database SQLite
└── export/                  ← JSON exports
```

---

## Decisioni prese

| Decisione | Scelta | Motivazione |
|---|---|---|
| Storage | SQLite | Query cross-document, ricerca FTS5, nessun server richiesto |
| Export | JSON opzionale | Per condivisione/revisione manuale |
| AI locale | Ollama | Privacy, costo zero, funziona offline |
| Modello AI | llama3.2:3b / phi3:mini | Veloci per RAG, non servono modelli grandi |
| Linguaggio | Python 3.12 | python-docx già disponibile, ecosistema ML ricco |

