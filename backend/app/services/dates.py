from datetime import date


def nz_tax_year_ending(d: date) -> int:
    """NZ tax year ends 31 March. 17 Oct 2026 → 2027."""
    return d.year + 1 if d.month >= 4 else d.year


def current_nz_fy(today: date | None = None) -> tuple[date, date]:
    today = today or date.today()
    year_end = nz_tax_year_ending(today)
    return date(year_end - 1, 4, 1), date(year_end, 3, 31)
