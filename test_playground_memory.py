import playground


def test_normalize_runtime_memory_value_collapses_whitespace():
    result = playground.normalize_runtime_memory_value("  I prefer   step by   step   ")
    assert result == "I prefer step by step"


def test_build_memory_key_is_case_insensitive():
    key_a = playground.build_memory_key("preference", "I Prefer Step By Step")
    key_b = playground.build_memory_key("preference", "i prefer step by step")
    assert key_a == key_b


def test_build_memory_key_treats_hyphen_and_space_as_same():
    key_a = playground.build_memory_key("preference", "I prefer step-by-step learning")
    key_b = playground.build_memory_key("preference", "I prefer step by step learning")
    assert key_a == key_b


def test_extract_runtime_memory_candidate_filters_known_transient_identity():
    candidate = playground.extract_runtime_memory_candidate("I'm tired today")
    assert candidate is None


def test_extract_runtime_memory_candidate_filters_additional_transient_identity():
    candidate = playground.extract_runtime_memory_candidate("I am stressed lately")
    assert candidate is None


def test_extract_runtime_memory_candidate_keeps_project_statement():
    candidate = playground.extract_runtime_memory_candidate("I'm building an AI agent")
    assert candidate is not None
    assert candidate["category"] == "project"


def test_extract_runtime_memory_candidate_keeps_non_transient_identity():
    candidate = playground.extract_runtime_memory_candidate("I am a backend engineer")
    assert candidate is not None
    assert candidate["category"] == "identity"


def test_extract_runtime_memory_candidate_transient_identity_matrix():
    transient_examples = [
        "I am exhausted right now",
        "I'm anxious today",
        "I am sick this week",
        "I'm burned out lately",
    ]
    for text in transient_examples:
        candidate = playground.extract_runtime_memory_candidate(text)
        assert candidate is None


def test_extract_runtime_memory_candidate_persistent_identity_matrix():
    persistent_examples = [
        "I am a software engineer",
        "I'm a parent and builder",
        "I am detail oriented",
    ]
    for text in persistent_examples:
        candidate = playground.extract_runtime_memory_candidate(text)
        assert candidate is not None
        assert candidate["category"] == "identity"


def test_extract_runtime_memory_candidate_filters_unicode_apostrophe_transient_identity():
    candidate = playground.extract_runtime_memory_candidate("I’m tired today")
    assert candidate is None


def test_build_memory_key_handles_unicode_apostrophe_consistently():
    key_a = playground.build_memory_key("identity", "I'm detail oriented")
    key_b = playground.build_memory_key("identity", "I’m detail oriented")
    assert key_a == key_b


def test_dedupe_memory_items_merges_legacy_step_by_step_variants():
    items = [
        {
            "memory_id": "mem_1",
            "category": "preference",
            "value": "I prefer step-by-step learning",
            "confidence": 0.75,
            "importance": 0.75,
            "evidence_count": 2,
            "memory_kind": "emerging",
            "source_refs": ["runtime"],
        },
        {
            "memory_id": "mem_2",
            "category": "preference",
            "value": "I prefer step by step learning",
            "confidence": 0.4,
            "importance": 0.7,
            "evidence_count": 1,
            "memory_kind": "tentative",
            "source_refs": ["runtime", "manual"],
        },
    ]

    deduped = playground.dedupe_memory_items(items)
    assert len(deduped) == 1
    merged = deduped[0]
    assert merged["evidence_count"] == 3
    assert merged["memory_kind"] == "emerging"
    assert merged["confidence"] == 0.75
    assert merged["importance"] == 0.75
    assert set(merged["source_refs"]) == {"runtime", "manual"}
