from tests.benchmarks.issue_357_corpus import CASES


def test_issue_357_corpus_covers_required_distribution() -> None:
    assert len(CASES) >= 40
    cohorts = {case.cohort for case in CASES}
    assert {
        "ambiguous",
        "deterministic",
        "dialogue_runtime",
        "multi",
        "multilingual",
        "narrator",
        "one_complex",
        "pending",
        "prerequisite",
    }.issubset(cohorts)
    assert all(case.expected_kinds for case in CASES)
    assert len({case.name for case in CASES}) == len(CASES)
