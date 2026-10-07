import pytest

from jobseeker.contacts.names import (
    PersonName, candidates, clean_name, emails_in_text, first_name_title, infer_pattern, pattern_of,
)


@pytest.mark.parametrize("raw,expected", [
    ("Asha Rao", PersonName("asha", "rao", False)),
    ("Asha Rao, PMP | Ex-Flipkart", PersonName("asha", "rao", False)),
    ("Dr. Asha Rao (She/Her)", PersonName("asha", "rao", False)),
    ("Rahul Kumar Sharma", PersonName("rahul", "sharma", False)),
    ("K. Meshram", PersonName("k", "meshram", True)),
    ("Asha", PersonName("asha", "", False)),
    ("José Silva 🚀", PersonName("jose", "silva", False)),
    ("Harsh M.", PersonName("harsh", "", False)),
])
def test_clean_name(raw, expected):
    assert clean_name(raw) == expected


def test_clean_name_rejects_empty():
    assert clean_name("🚀 | Hiring!") is None


def test_candidates_default_order():
    assert candidates(clean_name("Asha Rao"), "zepto.com") == [
        "asha.rao@zepto.com", "asha@zepto.com", "asharao@zepto.com", "arao@zepto.com",
        "a.rao@zepto.com", "asha_rao@zepto.com", "ashar@zepto.com", "rao.asha@zepto.com"]


def test_candidates_hint_first_and_special_names():
    assert candidates(clean_name("Vikram Singh"), "zepto.com", ["first"])[:2] == ["vikram@zepto.com", "vikram.singh@zepto.com"]
    assert candidates(clean_name("K. Meshram"), "inito.com") == ["kmeshram@inito.com", "k.meshram@inito.com"]
    assert candidates(clean_name("Asha"), "zepto.com") == ["asha@zepto.com"]


def test_pattern_of():
    assert pattern_of("asha@zepto.com", clean_name("Asha Rao")) == "first"
    assert pattern_of("a.rao@zepto.com", clean_name("Asha Rao")) == "f.last"
    assert pattern_of("someone@zepto.com", clean_name("Asha Rao")) is None


def test_emails_in_text_and_infer_pattern():
    text = "Write to priya.nair@zepto.com or careers@zepto.com; press: rohit.verma@zepto.com, x@gmail.com"
    found = emails_in_text(text, "zepto.com")
    assert found == ["priya.nair@zepto.com", "careers@zepto.com", "rohit.verma@zepto.com"]
    assert infer_pattern(found) == "first.last"
    assert infer_pattern(["a.kumar@x.com", "r.shah@x.com"]) == "f.last"
    assert infer_pattern(["careers@x.com", "hello@x.com"]) is None


def test_first_name_title():
    assert first_name_title("Asha Rao, PMP") == "Asha"
    assert first_name_title("🚀") == ""
