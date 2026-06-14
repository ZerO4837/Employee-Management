from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from app.config import SALES_EXCEL_DATE_FORMAT, SALES_WORKBOOK_PATH, SALES_WORKSHEET_NAME


@dataclass(frozen=True)
class ExcelSyncResult:
    saved: bool
    row: int | None = None
    message: str = ""


class SalesWorkbook:
    HEADERS = (
        "Customer Name",
        "Items Sold",
        "Email/Order ID",
        "Buying Amount",
        "Selling Amount",
        "Profit",
        "Status",
        "Date",
    )

    def __init__(self, path: Path = SALES_WORKBOOK_PATH, worksheet_name: str = SALES_WORKSHEET_NAME) -> None:
        self.path = path
        self.worksheet_name = worksheet_name

    @property
    def display_path(self) -> str:
        return str(self.path)

    def sync_entry(self, entry: dict[str, Any]) -> ExcelSyncResult:
        workbook = None
        try:
            row = self._existing_row(entry)
            workbook, sheet = self._open_workbook()
            self._ensure_headers(sheet)
            if row is None:
                row = self._next_row(sheet)
            self._write_row(sheet, row, entry)
            self._request_formula_recalculation(workbook)
            workbook.save(self.path)
        except Exception as exc:
            return ExcelSyncResult(False, message=str(exc))
        finally:
            self._close_workbook(workbook)
        return ExcelSyncResult(True, row=row, message=f"Excel row {row}")

    def delete_row(self, row: int) -> ExcelSyncResult:
        if row <= 1:
            return ExcelSyncResult(False, message="Excel data row is invalid.")
        workbook = None
        try:
            workbook, sheet = self._open_workbook()
            if row > sheet.max_row:
                return ExcelSyncResult(False, row=row, message=f"Excel row {row} does not exist.")
            sheet.delete_rows(row, 1)
            self._request_formula_recalculation(workbook)
            workbook.save(self.path)
        except Exception as exc:
            return ExcelSyncResult(False, row=row, message=str(exc))
        finally:
            self._close_workbook(workbook)
        return ExcelSyncResult(True, row=row, message=f"Excel row {row} removed")

    def _existing_row(self, entry: dict[str, Any]) -> int | None:
        value = entry.get("excel_row")
        if value in (None, ""):
            return None
        try:
            row = int(value)
        except (TypeError, ValueError):
            return None
        return row if row > 1 else None

    def _open_workbook(self):
        if self.path.suffix.lower() not in {".xlsx", ".xlsm"}:
            raise ValueError("Sales workbook must be an .xlsx or .xlsm file.")

        try:
            from openpyxl import Workbook, load_workbook
        except ModuleNotFoundError as exc:
            raise RuntimeError("openpyxl is not installed. Run: pip install -r requirements.txt") from exc

        self.path.parent.mkdir(parents=True, exist_ok=True)
        if self.path.exists():
            workbook = load_workbook(self.path, keep_vba=self.path.suffix.lower() == ".xlsm")
            return workbook, self._select_sheet(workbook)

        workbook = Workbook()
        sheet = workbook.active
        if self.worksheet_name:
            sheet.title = self.worksheet_name
        return workbook, sheet

    def _select_sheet(self, workbook):
        if not self.worksheet_name:
            return workbook.active
        if self.worksheet_name in workbook.sheetnames:
            return workbook[self.worksheet_name]
        return workbook.create_sheet(self.worksheet_name)

    def _ensure_headers(self, sheet) -> None:
        has_headers = any(sheet.cell(row=1, column=column).value not in (None, "") for column in range(1, 9))
        if not has_headers:
            for column, header in enumerate(self.HEADERS, start=1):
                sheet.cell(row=1, column=column).value = header
            widths = (22, 26, 26, 16, 16, 14, 14, 14)
            for column, width in enumerate(widths, start=1):
                sheet.column_dimensions[chr(64 + column)].width = width

    def _next_row(self, sheet) -> int:
        value_columns = (1, 2, 3, 4, 5, 7, 8)
        for row in range(max(sheet.max_row, 1), 1, -1):
            if any(sheet.cell(row=row, column=column).value not in (None, "") for column in value_columns):
                return row + 1
        return 2

    def _write_row(self, sheet, row: int, entry: dict[str, Any]) -> None:
        sheet.cell(row=row, column=1).value = entry.get("customer", "")
        sheet.cell(row=row, column=2).value = entry.get("item", "")
        sheet.cell(row=row, column=3).value = entry.get("order_id", "")
        sheet.cell(row=row, column=4).value = self._number_or_text(entry.get("buying_amount", "0"))
        sheet.cell(row=row, column=5).value = self._number_or_text(entry.get("selling_amount", ""))
        sheet.cell(row=row, column=6).value = f"=E{row}-D{row}"
        sheet.cell(row=row, column=7).value = entry.get("status", "")

        date_cell = sheet.cell(row=row, column=8)
        date_cell.value = self._date_value(entry)
        date_cell.number_format = SALES_EXCEL_DATE_FORMAT

    def _number_or_text(self, value: Any) -> int | float | str:
        text = str(value or "").strip()
        if not text:
            return ""
        normalized = text.replace(",", "")
        try:
            number = float(normalized)
        except ValueError:
            return text
        if number.is_integer():
            return int(number)
        return number

    def _date_value(self, entry: dict[str, Any]):
        raw_date = str(entry.get("date") or entry.get("entry_date") or "").strip()
        if raw_date:
            try:
                return datetime.strptime(raw_date, "%Y-%m-%d").date()
            except ValueError:
                return raw_date
        return datetime.now().date()

    def _request_formula_recalculation(self, workbook) -> None:
        try:
            workbook.calculation.fullCalcOnLoad = True
        except AttributeError:
            pass

    def _close_workbook(self, workbook) -> None:
        if workbook is None:
            return
        close = getattr(workbook, "close", None)
        if callable(close):
            close()
        archive = getattr(workbook, "_archive", None)
        archive_close = getattr(archive, "close", None)
        if callable(archive_close):
            archive_close()
