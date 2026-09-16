"""Read-only Google Sheets API transport for the normalized row adapter."""
from __future__ import annotations

from collections.abc import Sequence
import os
from typing import Any
from urllib.parse import quote

READ_ONLY_SCOPE = "https://www.googleapis.com/auth/spreadsheets.readonly"
API_ROOT = "https://sheets.googleapis.com/v4/spreadsheets"


def values_to_rows(values: Sequence[Sequence[Any]]) -> list[dict[str, str]]:
    """Convert a Sheets values response into header-keyed string rows."""
    if not values:
        raise ValueError("Google worksheet is empty")
    headers = [str(value).strip() for value in values[0]]
    if not headers or any(not header for header in headers):
        raise ValueError("Google worksheet has an empty header")
    if len(set(headers)) != len(headers):
        raise ValueError("Google worksheet has duplicate headers")

    rows: list[dict[str, str]] = []
    for row_number, values_row in enumerate(values[1:], start=2):
        if len(values_row) > len(headers):
            raise ValueError(f"Google worksheet row {row_number} has more values than headers")
        padded = list(values_row) + [""] * (len(headers) - len(values_row))
        if any(str(value).strip() for value in padded):
            rows.append({header: str(value) for header, value in zip(headers, padded, strict=True)})
    if not rows:
        raise ValueError("Google worksheet contains no data rows")
    return rows


def _authorized_session():
    try:
        from google.auth.transport.requests import AuthorizedSession
        from google.oauth2 import service_account
    except ImportError as error:
        raise RuntimeError("install requirements.txt to enable Google Sheets API access") from error

    credential_path = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")
    if not credential_path:
        raise ValueError("GOOGLE_APPLICATION_CREDENTIALS is not set")
    credentials = service_account.Credentials.from_service_account_file(
        credential_path,
        scopes=[READ_ONLY_SCOPE],
    )
    return AuthorizedSession(credentials)


def fetch_first_worksheet_rows(spreadsheet_id: str, worksheet_id: int = 0) -> tuple[str, list[dict[str, str]]]:
    """Fetch one worksheet using a read-only service-account session."""
    if not spreadsheet_id or not spreadsheet_id.replace("-", "").replace("_", "").isalnum():
        raise ValueError("invalid spreadsheet id")

    session = _authorized_session()
    metadata_response = session.get(
        f"{API_ROOT}/{spreadsheet_id}",
        params={"fields": "sheets.properties(sheetId,title,index,hidden)"},
        timeout=30,
    )
    if not metadata_response.ok:
        hint = ""
        if metadata_response.status_code == 403:
            hint = "; enable the Sheets API and share the sheet with the service account as Viewer"
        raise RuntimeError(f"Google Sheets metadata request failed ({metadata_response.status_code}){hint}")
    sheets = metadata_response.json().get("sheets", [])
    matching = [
        sheet.get("properties", {})
        for sheet in sheets
        if sheet.get("properties", {}).get("sheetId") == worksheet_id
    ]
    if not matching:
        raise ValueError(f"worksheet id {worksheet_id} was not found")
    title = matching[0].get("title")
    if not isinstance(title, str) or not title:
        raise ValueError("worksheet title is missing")

    cell_range = f"'{title}'!A:ZZ"
    values_response = session.get(
        f"{API_ROOT}/{spreadsheet_id}/values/{quote(cell_range, safe='')}",
        params={"majorDimension": "ROWS", "valueRenderOption": "UNFORMATTED_VALUE"},
        timeout=30,
    )
    if not values_response.ok:
        raise RuntimeError(f"Google Sheets values request failed ({values_response.status_code})")
    values = values_response.json().get("values", [])
    return title, values_to_rows(values)
