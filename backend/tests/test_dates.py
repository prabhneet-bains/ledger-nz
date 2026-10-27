from datetime import date

from app.services.dates import nz_tax_year_ending


def test_tax_year_rolls_in_april():
    assert nz_tax_year_ending(date(2026, 10, 17)) == 2027
    assert nz_tax_year_ending(date(2026, 3, 31)) == 2026
    assert nz_tax_year_ending(date(2026, 4, 1)) == 2027
