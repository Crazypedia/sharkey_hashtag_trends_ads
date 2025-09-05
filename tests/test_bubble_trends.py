import os
from sharkey_ads.bubble_trends import parse_selection_ranges, load_domains

def test_parse_selection_ranges_basic():
    assert parse_selection_ranges("1-3,5", 10) == [1,2,3,5]

def test_parse_selection_ranges_out_of_bounds_and_bad_input():
    result = parse_selection_ranges("0,2,a,4-3,8-9", 7)
    assert result == [2,3,4]

def test_load_domains(tmp_path):
    p = tmp_path / "domains.txt"
    p.write_text("# comment\nExample.COM\n\n example.org \n# another\n", encoding="utf-8")
    assert load_domains(str(p)) == ["example.com", "example.org"]
