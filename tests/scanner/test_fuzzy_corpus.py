"""
Hand-curated WRatio threshold validation corpus for the T12 FuzzyMatcher.

This corpus locks the fuzzy matching threshold by enforcing a 5-point safety
margin between known-good and known-bad book pairs. T12 implementation must
satisfy: min(should_match scores) > max(should_not_match scores) + 5.

Query format: normalize(f"{title} {author}") on both sides, scored with
rapidfuzz.fuzz.WRatio. The corpus excludes pairs that WRatio cannot resolve
in isolation (e.g., short title + suffix like "Dune" vs "Dune Messiah");
those cases are deferred to ISBN/embedded-id/exact-normalized signals before
fuzzy fallback in T12.

The test is marked xfail until T12 lands a `compute_fuzzy_score` callable in
backend.services.scanner.matchers. Once T12 ships, remove the xfail marker
and the test must pass.
"""

import json
from pathlib import Path

import pytest
from rapidfuzz import fuzz

from backend.services.scanner.normalize import normalize

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "fuzzy_pairs.json"


def _load_corpus() -> dict:
    with FIXTURE_PATH.open(encoding="utf-8") as f:
        return json.load(f)


def _query(title: str, author: str) -> str:
    return normalize(f"{title} {author}")


def _score(book_title: str, book_author: str, file_title: str, file_author: str) -> float:
    return fuzz.WRatio(_query(book_title, book_author), _query(file_title, file_author))


@pytest.mark.xfail(
    reason="depends on T12 FuzzyMatcher implementation; remove marker once compute_fuzzy_score lands",
    strict=False,
)
def test_fuzzy_threshold_corpus_separates_cleanly() -> None:
    try:
        from backend.services.scanner.matchers import compute_fuzzy_score
    except ImportError:
        pytest.fail("T12 FuzzyMatcher not implemented yet (backend.services.scanner.matchers)")

    corpus = _load_corpus()
    should_match = corpus["should_match"]
    should_not_match = corpus["should_not_match"]

    assert len(should_match) == 50, f"expected 50 should_match pairs, got {len(should_match)}"
    assert len(should_not_match) == 50, f"expected 50 should_not_match pairs, got {len(should_not_match)}"

    sm_results = []
    for pair in should_match:
        score = compute_fuzzy_score(
            book_title=pair["book_title"],
            book_author=pair["book_author"],
            file_title=pair["file_title"],
            file_author=pair["file_author"],
        )
        sm_results.append((score, pair))

    snm_results = []
    for pair in should_not_match:
        score = compute_fuzzy_score(
            book_title=pair["book_title"],
            book_author=pair["book_author"],
            file_title=pair["file_title"],
            file_author=pair["file_author"],
        )
        snm_results.append((score, pair))

    sm_failures = [(s, p) for s, p in sm_results if s < p["expected_score_min"]]
    assert not sm_failures, "should_match pairs scored below expected_score_min:\n" + "\n".join(
        f"  {s:.2f} < {p['expected_score_min']}: "
        f"{p['book_title']!r} / {p['book_author']!r} vs "
        f"{p['file_title']!r} / {p['file_author']!r} [{p['rationale']}]"
        for s, p in sm_failures
    )

    snm_failures = [(s, p) for s, p in snm_results if s > p["expected_score_max"]]
    assert not snm_failures, "should_not_match pairs scored above expected_score_max:\n" + "\n".join(
        f"  {s:.2f} > {p['expected_score_max']}: "
        f"{p['book_title']!r} / {p['book_author']!r} vs "
        f"{p['file_title']!r} / {p['file_author']!r} [{p['rationale']}]"
        for s, p in snm_failures
    )

    min_sm = min(sm_results, key=lambda r: r[0])
    max_snm = max(snm_results, key=lambda r: r[0])
    separation = min_sm[0] - max_snm[0]
    assert separation > 5, (
        f"insufficient threshold separation: {separation:.2f} <= 5\n"
        f"  weakest should_match  ({min_sm[0]:.2f}): "
        f"{min_sm[1]['book_title']!r} vs {min_sm[1]['file_title']!r} [{min_sm[1]['rationale']}]\n"
        f"  strongest should_not_match ({max_snm[0]:.2f}): "
        f"{max_snm[1]['book_title']!r} vs {max_snm[1]['file_title']!r} [{max_snm[1]['rationale']}]"
    )


def test_corpus_fixture_loads_and_is_well_formed() -> None:
    corpus = _load_corpus()
    assert "should_match" in corpus
    assert "should_not_match" in corpus
    assert len(corpus["should_match"]) == 50
    assert len(corpus["should_not_match"]) == 50

    required_match_keys = {"book_title", "book_author", "file_title", "file_author", "expected_score_min", "rationale"}
    required_no_match_keys = {
        "book_title",
        "book_author",
        "file_title",
        "file_author",
        "expected_score_max",
        "rationale",
    }

    for pair in corpus["should_match"]:
        assert required_match_keys.issubset(pair.keys()), f"missing keys in should_match pair: {pair}"
        assert pair["expected_score_min"] >= 85, (
            f"expected_score_min below 85 without documented rationale exception: {pair}"
        )
    for pair in corpus["should_not_match"]:
        assert required_no_match_keys.issubset(pair.keys()), f"missing keys in should_not_match pair: {pair}"
        assert pair["expected_score_max"] <= 80, f"expected_score_max above 80: {pair}"


def test_corpus_separates_cleanly_under_wratio_today() -> None:
    corpus = _load_corpus()

    sm_scores = [
        (_score(p["book_title"], p["book_author"], p["file_title"], p["file_author"]), p)
        for p in corpus["should_match"]
    ]
    snm_scores = [
        (_score(p["book_title"], p["book_author"], p["file_title"], p["file_author"]), p)
        for p in corpus["should_not_match"]
    ]

    sm_below = [(s, p) for s, p in sm_scores if s < p["expected_score_min"]]
    assert not sm_below, "should_match pairs scored below expected_score_min under WRatio:\n" + "\n".join(
        f"  {s:.2f} < {p['expected_score_min']}: {p['book_title']!r} vs {p['file_title']!r} [{p['rationale']}]"
        for s, p in sm_below
    )

    snm_above = [(s, p) for s, p in snm_scores if s > p["expected_score_max"]]
    assert not snm_above, "should_not_match pairs scored above expected_score_max under WRatio:\n" + "\n".join(
        f"  {s:.2f} > {p['expected_score_max']}: {p['book_title']!r} vs {p['file_title']!r} [{p['rationale']}]"
        for s, p in snm_above
    )

    min_sm = min(sm_scores, key=lambda r: r[0])
    max_snm = max(snm_scores, key=lambda r: r[0])
    separation = min_sm[0] - max_snm[0]
    assert separation > 5, (
        f"corpus does not separate cleanly under WRatio: separation={separation:.2f}\n"
        f"  weakest should_match  ({min_sm[0]:.2f}): {min_sm[1]['book_title']!r} vs {min_sm[1]['file_title']!r}\n"
        f"  strongest should_not_match ({max_snm[0]:.2f}): "
        f"{max_snm[1]['book_title']!r} vs {max_snm[1]['file_title']!r}"
    )
