import csv
import re
from datetime import date, datetime
from io import BytesIO, StringIO
from pathlib import Path
from typing import Any
from zipfile import BadZipFile

from fastapi import HTTPException, UploadFile
from openpyxl import load_workbook
from openpyxl.utils.exceptions import InvalidFileException

MAX_IMPORT_FILE_BYTES = 5 * 1024 * 1024
MAX_IMPORT_ROWS = 500
MAX_IMPORT_COLUMNS = 40


def _header_key(value: object) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(value or "").strip().casefold()).strip("_")


def _cell_value(value: object) -> Any:
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    return value


def read_spreadsheet_rows(
    upload: UploadFile,
    *,
    aliases: dict[str, str],
    required_columns: set[str],
) -> list[tuple[int, dict[str, Any]]]:
    filename = upload.filename or ""
    extension = Path(filename).suffix.casefold()
    if extension not in {".csv", ".xlsx"}:
        raise HTTPException(status_code=415, detail="Choose a .csv or .xlsx file.")

    content = upload.file.read(MAX_IMPORT_FILE_BYTES + 1)
    if len(content) > MAX_IMPORT_FILE_BYTES:
        raise HTTPException(status_code=413, detail="The file must be 5 MB or smaller.")
    if not content:
        raise HTTPException(status_code=422, detail="The file is empty.")

    if extension == ".csv":
        try:
            text = content.decode("utf-8-sig")
            rows = iter(csv.reader(StringIO(text, newline="")))
        except (UnicodeDecodeError, csv.Error) as error:
            raise HTTPException(
                status_code=422,
                detail="The CSV could not be read. Save it as UTF-8 CSV and try again.",
            ) from error
        workbook = None
    else:
        try:
            workbook = load_workbook(
                BytesIO(content),
                read_only=True,
                data_only=False,
                keep_links=False,
            )
        except (BadZipFile, InvalidFileException, OSError, ValueError, KeyError) as error:
            raise HTTPException(
                status_code=422,
                detail="The Excel file could not be read. Upload a valid .xlsx workbook.",
            ) from error
        if not workbook.worksheets:
            workbook.close()
            raise HTTPException(status_code=422, detail="The workbook has no worksheets.")
        worksheet = workbook.worksheets[0]
        if worksheet.max_column and worksheet.max_column > MAX_IMPORT_COLUMNS:
            workbook.close()
            raise HTTPException(
                status_code=422,
                detail=f"The first worksheet can have no more than {MAX_IMPORT_COLUMNS} columns.",
            )
        if worksheet.max_row and worksheet.max_row > MAX_IMPORT_ROWS + 1:
            workbook.close()
            raise HTTPException(
                status_code=413,
                detail=f"The first worksheet can contain no more than {MAX_IMPORT_ROWS} data rows.",
            )
        rows = worksheet.iter_rows(max_col=MAX_IMPORT_COLUMNS)

    try:
        header_row = next(rows, None)
        if not header_row:
            raise HTTPException(status_code=422, detail="The first worksheet has no header row.")
        header_values = (
            [cell.value for cell in header_row]
            if workbook is not None
            else header_row
        )
        headers = [str(value or "").strip() for value in header_values]
        while headers and not headers[-1]:
            headers.pop()
        if not headers:
            raise HTTPException(status_code=422, detail="The first row must contain column headers.")
        if len(headers) > MAX_IMPORT_COLUMNS:
            raise HTTPException(
                status_code=422,
                detail=f"The first worksheet can have no more than {MAX_IMPORT_COLUMNS} columns.",
            )

        canonical_headers: list[str] = []
        unknown_headers: list[str] = []
        for header in headers:
            key = _header_key(header)
            canonical = aliases.get(key)
            if not key:
                raise HTTPException(
                    status_code=422,
                    detail="Every populated column must have a header.",
                )
            if canonical is None:
                unknown_headers.append(header)
            else:
                canonical_headers.append(canonical)
        if unknown_headers:
            names = ", ".join(unknown_headers[:5])
            raise HTTPException(
                status_code=422,
                detail=f"Unsupported columns: {names}. Use the provided template.",
            )
        if len(set(canonical_headers)) != len(canonical_headers):
            raise HTTPException(
                status_code=422,
                detail="The file has duplicate columns after header normalization.",
            )
        missing_headers = required_columns.difference(canonical_headers)
        if missing_headers:
            names = ", ".join(sorted(missing_headers))
            raise HTTPException(
                status_code=422,
                detail=f"Required columns are missing: {names}.",
            )

        parsed_rows: list[tuple[int, dict[str, Any]]] = []
        for row_number, cells in enumerate(rows, start=2):
            if workbook is not None and any(cell.data_type == "f" for cell in cells):
                raise HTTPException(
                    status_code=422,
                    detail=f"Row {row_number} contains a formula. Replace formulas with values.",
                )
            values = (
                [_cell_value(cell.value) for cell in cells]
                if workbook is not None
                else cells
            )
            if len(values) > len(headers) and any(
                value not in (None, "") for value in values[len(headers):]
            ):
                raise HTTPException(
                    status_code=422,
                    detail=f"Row {row_number} has values outside the header columns.",
                )
            values = values[:len(headers)]
            values.extend([None] * (len(headers) - len(values)))
            if all(value is None or str(value).strip() == "" for value in values):
                continue
            parsed_rows.append(
                (row_number, dict(zip(canonical_headers, values, strict=True)))
            )
            if len(parsed_rows) > MAX_IMPORT_ROWS:
                raise HTTPException(
                    status_code=413,
                    detail=f"A file can contain no more than {MAX_IMPORT_ROWS} data rows.",
                )
        if not parsed_rows:
            raise HTTPException(status_code=422, detail="The file contains no data rows.")
        return parsed_rows
    except csv.Error as error:
        raise HTTPException(
            status_code=422,
            detail="The CSV has invalid row formatting. Check its column separators and try again.",
        ) from error
    finally:
        if workbook is not None:
            workbook.close()
