# Patent Coating Landscape Pipeline

Python workflow for mining the Google Patents Public Datasets via BigQuery, focusing on food and beverage container coating technologies. The script exports the relevant patent metadata to CSV and optionally classifies each record's coating chemistry using an OpenRouter-hosted LLM.

## Prerequisites

- Python 3.10 or newer.
- Google Cloud project with access to the [`patents-public-data.patents.publications`](https://console.cloud.google.com/bigquery?p=patents-public-data&d=patents&t=publications&page=table) dataset.
- Application Default Credentials or a service account key (set `GOOGLE_APPLICATION_CREDENTIALS`).
- OpenRouter API key (only required if you want automatic chemistry classification).

Install dependencies:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Copy `.env` and populate the credential values or export them in your shell before running the pipeline.
At a minimum set:

- `GOOGLE_APPLICATION_CREDENTIALS` – path to your service account key JSON.
- `GOOGLE_CLOUD_PROJECT` – BigQuery project that should be billed (defaults to `axial-analyzer-475800-v4` from `src/config.py` if omitted).
- `OPENROUTER_API_KEY` – only required when running the classification stage.

## Project Layout

```
├── notebooks/
│   └── 01_query_bigquery_patents.ipynb
├── src/
│   ├── config.py
│   ├── exporter.py
│   ├── llm_classifier.py
│   ├── pipeline.py
│   ├── query_builder.py
│   └── utils.py
├── data/
│   ├── patents_classified.csv
│   └── patents_raw.csv
├── requirements.txt
├── .env
└── README.md
```

The notebook is ideal for prototyping filters; `src/` houses the production pipeline.

## Running the Pipeline

The CLI now pulls defaults from `.env` and `src/config.py`, so the simplest invocation is:

```bash
python -m src.pipeline
```

By default the pipeline targets the trailing three publication years (current year inclusive), fetches up to 100 records, writes CSVs into `data/`, and bills the project id resolved in this order: `--project-id` flag ➜ `GOOGLE_CLOUD_PROJECT` env ➜ configuration default.

Set the following environment variables when running classification:

- `OPENROUTER_API_KEY` – required for LLM calls.
- `OPENROUTER_APP_URL` – optional, identifies your application to OpenRouter.
- `OPENROUTER_TITLE` – optional, short run label.

Use CLI flags when you need to override the defaults, for example:

```bash
python -m src.pipeline --start-year 2020 --end-year 2023 --limit 250 --log-level DEBUG
```

Add `--skip-llm` if you only need the BigQuery export step.

### BigQuery Query Design

- Scope to US publications: `country_code = 'US'`.
- Date bounds are set via `publication_date BETWEEN @start_date AND @end_date` (YYYYMMDD integers).
- Coating-specific CPC filters use the set `B65D 25/14`, `C09D 7/65`, `C09D 163`, `C09D 167`. The SQL normalises spaces and matches prefixes so subclasses are included.
- Keyword filter searches the English title, abstract, and description for food/beverage terms (`"food can"`, `"beverage container"`, etc.). You can trim this to title/abstract only by editing `KEYWORD_PHRASES` or the SQL in `src/query_builder.py`.
- Text fields are flattened with `UNNEST` and the first English entry is chosen, matching how BigQuery stores localized strings.

Example SQL (simplified to show the filtering logic):

```sql
SELECT
  publication_number,
  publication_date,
  title_en,
  abstract_en,
  assignee_orgs,
  cpc_codes,
  description_excerpt,
  first_claim_en
FROM `patents-public-data.patents.publications`
WHERE
  country_code = 'US'
  AND publication_date BETWEEN 20230101 AND 20251231
  AND EXISTS (
    SELECT 1 FROM UNNEST(cpc) AS c
    WHERE LOWER(REPLACE(c.code, ' ', '')) LIKE 'c09d167%'
       OR LOWER(REPLACE(c.code, ' ', '')) LIKE 'c09d163%'
       OR LOWER(REPLACE(c.code, ' ', '')) LIKE 'c09d7/65%'
       OR LOWER(REPLACE(c.code, ' ', '')) LIKE 'b65d25/14%'
  )
  AND (
    REGEXP_CONTAINS(LOWER(title_en), r'(food can|beverage can|food container)') OR
    REGEXP_CONTAINS(LOWER(abstract_en), r'(food can|beverage can|food container)')
  )
ORDER BY publication_date DESC
LIMIT 100;
```

Tune the limit, keyword list, and CPC prefixes to broaden or narrow the result set. Preview queries in the BigQuery UI, then let the pipeline automate extraction and CSV export.

### Description and Claims Extraction

The pipeline keeps the first ~800 words of the English description (`--description-word-limit`) to approximate the introductory section (field/background/summary). Adjust this parameter or add heading-based heuristics if you want a more precise cut.

The first English claim is included in full; if you require all claims, remove the limit in `build_query`.

## Classification Strategy

When classification is enabled, each record is sent to an OpenRouter model with a concise prompt that summarises title, abstract, assignee, CPC codes, description excerpt, and first claim. The model must return one of:

- `Epoxy (BPA)`
- `Epoxy (BPF)`
- `Polyester`
- `Acrylic`
- `PVC`
- `Polyolefin`
- `Oleoresin/Phenolic`
- `Hybrid`
- `BPA-Free (Unspecified)`

The script stores the selected `coating_type`, optional `classification_confidence`, and an `era` label (`pre-BPA`, `BPA-era`, `modern`) when `--era-column` is set. Use `--skip-llm` to export data without classification and handle chemistry assignment manually (e.g., keyword heuristics or your own model).

## Output Fields

- `publication_number`, `publication_date`, `title`, `abstract`, `assignee`
- `cpc_codes` (semicolon-separated list)
- `description` (first ~800 words of the English description)
- `first_claim` (first English claim)
- `coating_type`, `classification_confidence` (only when LLM classification is enabled)
- Optional `era` column derived from publication year and chemistry assignment.

Adjust the logging level with `--log-level DEBUG` to examine the generated SQL and API responses.
