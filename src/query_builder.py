"""BigQuery query construction and execution."""

from __future__ import annotations

import logging
from typing import Dict, List, Optional

from google.cloud import bigquery
from google.cloud.bigquery import QueryJobConfig, ScalarQueryParameter

from . import config, utils


def build_query(limit: int, description_word_limit: int) -> str:
    return f"""
WITH base AS (
  SELECT
    publication_number,
    SAFE.PARSE_DATE('%Y%m%d', CAST(publication_date AS STRING)) AS publication_date,
    COALESCE(
      (
        SELECT tl.text
        FROM UNNEST(title_localized) AS tl
        WHERE tl.language = 'en'
        LIMIT 1
      ),
      (
        SELECT tl.text
        FROM UNNEST(title_localized) AS tl
        LIMIT 1
      )
    ) AS title_en,
    COALESCE(
      (
        SELECT al.text
        FROM UNNEST(abstract_localized) AS al
        WHERE al.language = 'en'
        LIMIT 1
      ),
      (
        SELECT al.text
        FROM UNNEST(abstract_localized) AS al
        LIMIT 1
      )
    ) AS abstract_en,
    COALESCE(
      (
        SELECT dl.text
        FROM UNNEST(description_localized) AS dl
        WHERE dl.language = 'en'
        LIMIT 1
      ),
      (
        SELECT dl.text
        FROM UNNEST(description_localized) AS dl
        LIMIT 1
      )
    ) AS description_en,
    COALESCE(
      (
        SELECT cl.text
        FROM UNNEST(claims_localized) AS cl
        WHERE cl.language = 'en'
        LIMIT 1
      ),
      (
        SELECT cl.text
        FROM UNNEST(claims_localized) AS cl
        LIMIT 1
      )
    ) AS first_claim_en,
    (
      SELECT ARRAY_AGG(DISTINCT REPLACE(c.code, ' ', '') ORDER BY REPLACE(c.code, ' ', ''))
      FROM UNNEST(cpc) AS c
      WHERE c.code IS NOT NULL
    ) AS cpc_codes,
    (
      SELECT STRING_AGG(DISTINCT a.name, '; ' ORDER BY a.name)
      FROM UNNEST(assignee_harmonized) AS a
      WHERE a.name IS NOT NULL
    ) AS assignee_orgs
  FROM `{config.BIGQUERY_TABLE}`
  WHERE
    publication_date BETWEEN @start_date AND @end_date
    AND country_code = 'US'
    AND EXISTS (
      SELECT 1
      FROM UNNEST(cpc) AS c
      WHERE {utils.CPC_CONDITION}
    )
)
SELECT
  publication_number,
  FORMAT_DATE('%Y-%m-%d', publication_date) AS publication_date,
  EXTRACT(YEAR FROM publication_date) AS publication_year,
  title_en AS title,
  abstract_en AS abstract,
  assignee_orgs AS assignee,
  cpc_codes,
  CASE
    WHEN description_en IS NULL THEN NULL
    ELSE ARRAY_TO_STRING(ARRAY_SLICE(SPLIT(description_en, ' '), 0, @description_word_limit), ' ')
  END AS description_excerpt,
  first_claim_en AS first_claim
FROM base
WHERE (
  (title_en IS NOT NULL AND REGEXP_CONTAINS(LOWER(title_en), @keyword_pattern)) OR
  (abstract_en IS NOT NULL AND REGEXP_CONTAINS(LOWER(abstract_en), @keyword_pattern)) OR
  (description_en IS NOT NULL AND REGEXP_CONTAINS(LOWER(description_en), @keyword_pattern))
)
ORDER BY publication_date DESC
LIMIT {limit}
"""


def assemble_query_config(
    start_year: int,
    end_year: int,
    description_word_limit: int,
) -> QueryJobConfig:
    start_date = int(f"{start_year}0101")
    end_date = int(f"{end_year}1231")

    parameters = [
        ScalarQueryParameter("start_date", "INT64", start_date),
        ScalarQueryParameter("end_date", "INT64", end_date),
        ScalarQueryParameter("keyword_pattern", "STRING", utils.KEYWORD_PATTERN),
        ScalarQueryParameter("description_word_limit", "INT64", description_word_limit),
    ]

    return QueryJobConfig(query_parameters=parameters)


def fetch_patent_records(
    client: bigquery.Client,
    limit: int,
    start_year: int,
    end_year: int,
    description_word_limit: int,
) -> List[Dict[str, Optional[str]]]:
    sql = build_query(limit=limit, description_word_limit=description_word_limit)
    job_config = assemble_query_config(
        start_year=start_year,
        end_year=end_year,
        description_word_limit=description_word_limit,
    )
    logging.debug("Submitting BigQuery job.")
    query_job = client.query(sql, job_config=job_config)
    results = query_job.result()
    logging.info("Retrieved %s rows from BigQuery.", results.total_rows)

    extracted = []
    for row in results:
        extracted.append(
            {
                "publication_number": row.get("publication_number"),
                "publication_date": row.get("publication_date"),
                "publication_year": row.get("publication_year"),
                "title": row.get("title"),
                "abstract": row.get("abstract"),
                "assignee": row.get("assignee"),
                "cpc_codes": list(row.get("cpc_codes") or []),
                "description": row.get("description_excerpt"),
                "first_claim": row.get("first_claim"),
            }
        )
    return extracted
