"""Reusable CSV / XLSX export helpers.

Net-new for the project — the codebase previously only *imported* spreadsheets (catalog supplier
uploads). ``csv_response`` uses the stdlib ``csv`` module; ``xlsx_response`` uses ``openpyxl`` (an
existing dependency). Both return a downloadable ``HttpResponse`` with a ``Content-Disposition``
attachment header. Kept in their own module so future modules can reuse them.
"""
import csv

from django.http import HttpResponse

XLSX_CONTENT_TYPE = (
    'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
)


def csv_response(filename, header, rows):
    """A ``text/csv`` attachment built from a header row + an iterable of row lists."""
    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    writer = csv.writer(response)
    writer.writerow(list(header))
    for row in rows:
        writer.writerow(list(row))
    return response


def xlsx_response(filename, header, rows, *, sheet_title='Sheet1'):
    """An ``.xlsx`` attachment built from a header row + an iterable of row lists."""
    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    ws.title = (sheet_title or 'Sheet1')[:31]
    ws.append(list(header))
    for row in rows:
        ws.append(list(row))
    response = HttpResponse(content_type=XLSX_CONTENT_TYPE)
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    wb.save(response)
    return response
