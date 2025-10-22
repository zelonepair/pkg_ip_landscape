"""Command-line interface for the patent coating pipeline."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import logging
import os
import platform
import sys
import time
from typing import Optional, Sequence

from dotenv import find_dotenv, load_dotenv
from google.cloud import bigquery
from google.oauth2 import service_account

from . import config, exporter, llm_classifier, query_builder, utils


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Query Google Patents via BigQuery and classify coating chemistries."
    )
    parser.add_argument(
        "--project-id",
        default=None,
        help=(
            "Google Cloud project id used for the BigQuery client. "
            "If omitted, the value is sourced from environment or configuration."
        ),
    )
    parser.add_argument(
        "--start-year",
        type=int,
        default=config.DEFAULT_START_YEAR,
        help="Lower bound (inclusive) for publication year filter.",
    )
    parser.add_argument(
        "--end-year",
        type=int,
        default=config.DEFAULT_END_YEAR,
        help="Upper bound (inclusive) for publication year filter.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=config.DEFAULT_LIMIT,
        help="Maximum number of patent records to fetch (applied after filters).",
    )
    parser.add_argument(
        "--output-raw",
        default="data/patents_raw.csv",
        help="Destination CSV filename for raw export.",
    )
    parser.add_argument(
        "--output-classified",
        default="data/patents_classified.csv",
        help="Destination CSV filename for classified export.",
    )
    parser.add_argument(
        "--openrouter-model",
        default=config.DEFAULT_OPENROUTER_MODEL,
        help="OpenRouter model identifier for classification calls.",
    )
    parser.add_argument(
        "--openrouter-timeout",
        type=float,
        default=config.DEFAULT_OPENROUTER_TIMEOUT,
        help="Timeout (seconds) for OpenRouter API calls.",
    )
    parser.add_argument(
        "--openrouter-delay",
        type=float,
        default=config.DEFAULT_OPENROUTER_DELAY,
        help="Delay between successive classification calls to avoid rate limits.",
    )
    parser.add_argument(
        "--skip-llm",
        action="store_true",
        help="Skip OpenRouter classification stage (coating_type will be empty).",
    )
    parser.add_argument(
        "--era-column",
        action="store_true",
        help="Add an era column derived from publication year and chemistry type.",
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"],
        help="Logging level for console output.",
    )
    parser.add_argument(
        "--description-word-limit",
        type=int,
        default=config.DEFAULT_DESCRIPTION_WORD_LIMIT,
        help="Maximum number of words to retain from the description excerpt.",
    )
    parser.add_argument(
        "--max-retries",
        type=int,
        default=config.DEFAULT_MAX_RETRIES,
        help="Maximum retries for OpenRouter requests when transient failures occur.",
    )
    return parser.parse_args(argv)


def initialise_environment() -> bool:
    """Load .env configuration and validate Google credential prerequisites."""
    env_path = find_dotenv(usecwd=True)
    if env_path:
        load_dotenv(env_path)
        logging.info("Loaded environment variables from %s", env_path)
    else:
        logging.warning("No .env file found; relying on ambient environment variables.")

    credential_path = os.getenv("GOOGLE_APPLICATION_CREDENTIALS")
    if not credential_path:
        logging.error("GOOGLE_APPLICATION_CREDENTIALS is not set. Populate .env before running the pipeline.")
        return False

    resolved_path = os.path.expanduser(os.path.expandvars(credential_path.strip()))
    logging.debug("Resolved GOOGLE_APPLICATION_CREDENTIALS to %s", resolved_path)

    if not os.path.isfile(resolved_path):
        logging.error("Credential file %s does not exist.", resolved_path)
        return False

    if not os.access(resolved_path, os.R_OK):
        logging.error("Credential file %s is not readable.", resolved_path)
        return False

    try:
        credentials = service_account.Credentials.from_service_account_file(resolved_path)
    except Exception as err:  # noqa: BLE001
        logging.error("Unable to load Google credentials from %s: %s", resolved_path, err)
        return False

    try:
        credential_size = os.path.getsize(resolved_path)
    except OSError:
        credential_size = None

    project_hint = getattr(credentials, "project_id", None) or "<missing>"
    email = getattr(credentials, "service_account_email", "") or "<unknown>"
    email_domain = email.split("@", 1)[-1] if "@" in email else "<unknown>"
    size_msg = f"{credential_size} bytes" if credential_size is not None else "size unreadable"

    logging.info(
        "Validated Google service account credentials (project hint=%s, domain=%s, file=%s, size=%s).",
        project_hint,
        email_domain,
        resolved_path,
        size_msg,
    )

    if os.getenv(config.ENV_OPENROUTER_API_KEY):
        logging.info("OpenRouter API key detected in environment.")
    else:
        logging.info("OpenRouter API key not detected; classification stage may be skipped.")

    return True


def resolve_project_id(cli_value: Optional[str]) -> tuple[Optional[str], str]:
    """Resolve project id from CLI arg, environment, or config defaults."""
    if cli_value:
        return cli_value, "CLI argument"

    env_value = os.getenv(config.ENV_GCP_PROJECT_ID)
    if env_value:
        return env_value, f"environment variable {config.ENV_GCP_PROJECT_ID}"

    config_value = getattr(config, "DEFAULT_GCP_PROJECT_ID", None)
    if config_value:
        return config_value, "configuration constant DEFAULT_GCP_PROJECT_ID"

    return None, ""


def run_pipeline(args: argparse.Namespace) -> int:
    logging.basicConfig(level=getattr(logging, args.log_level), format="%(levelname)s: %(message)s")
    start_time = time.perf_counter()

    logging.info("Patent coating pipeline invoked at %s", datetime.now(timezone.utc).isoformat())
    logging.debug("Python %s (%s)", platform.python_version(), sys.executable)
    logging.debug("Current working directory: %s", os.getcwd())
    logging.debug("CLI arguments: %s", vars(args))

    if not initialise_environment():
        return 1

    project_id, project_source = resolve_project_id(args.project_id)
    if not project_id:
        logging.error(
            "BigQuery project id is not configured. Provide --project-id, set %s, or update config.DEFAULT_GCP_PROJECT_ID.",
            config.ENV_GCP_PROJECT_ID,
        )
        return 1

    logging.info("Using BigQuery project %s (source: %s).", project_id, project_source)
    args.project_id = project_id

    try:
        utils.validate_years(args.start_year, args.end_year)
    except ValueError as err:
        logging.error("Invalid year configuration: %s", err)
        return 1

    logging.info(
        "Running query for patents between %s and %s (limit %s).",
        args.start_year,
        args.end_year,
        args.limit,
    )
    logging.debug("Target BigQuery project: %s", project_id)

    try:
        client = bigquery.Client(project=project_id)
    except Exception as err:  # noqa: BLE001
        logging.error("Unable to initialise BigQuery client: %s", err)
        return 1

    try:
        records = query_builder.fetch_patent_records(
            client=client,
            limit=args.limit,
            start_year=args.start_year,
            end_year=args.end_year,
            description_word_limit=args.description_word_limit,
        )
    except Exception as err:  # noqa: BLE001
        logging.error("BigQuery execution failed: %s", err)
        return 1

    logging.info("Fetched %s candidate patents.", len(records))

    # Always write the raw export after the BigQuery step.
    try:
        exporter.write_csv(records=records, path=args.output_raw, include_era=False)
    except Exception as err:  # noqa: BLE001
        logging.error("Failed to write raw CSV: %s", err)
        return 1

    if not args.skip_llm:
        api_key = os.getenv(config.ENV_OPENROUTER_API_KEY)
        if not api_key:
            logging.error("%s environment variable is required for classification.", config.ENV_OPENROUTER_API_KEY)
            return 1
        llm_classifier.classify_records(
            records=records,
            api_key=api_key,
            model=args.openrouter_model,
            timeout=args.openrouter_timeout,
            max_retries=args.max_retries,
            delay=args.openrouter_delay,
            include_era=args.era_column,
        )
    else:
        logging.info("Skipping LLM classification as requested.")
        for record in records:
            record["coating_type"] = None
            record["classification_confidence"] = None
            if args.era_column:
                record["era"] = utils.determine_era(record.get("publication_year"), None)

    try:
        exporter.write_csv(
            records=records,
            path=args.output_classified,
            include_era=args.era_column,
        )
    except Exception as err:  # noqa: BLE001
        logging.error("Failed to write classified CSV: %s", err)
        return 1

    logging.info("Raw data saved to %s", args.output_raw)
    logging.info("Classified data saved to %s", args.output_classified)
    logging.info("Pipeline completed successfully in %.2f seconds.", time.perf_counter() - start_time)
    return 0


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(argv)
    return run_pipeline(args)


if __name__ == "__main__":  # pragma: no cover - CLI entry
    sys.exit(main())
