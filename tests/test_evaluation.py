from analytics.evaluation import same_result


def test_ignores_row_order():
    assert same_result([["a", 1], ["b", 2]], [["b", 2], ["a", 1]])


def test_ignores_column_order_and_extra_columns():
    assert same_result([["Monster", 8.9]], [[74, 8.9, "Monster"]])


def test_rounds_numbers_to_two_places():
    assert same_result([["x", 8.46]], [["x", 8.4567]])
    assert same_result([[3]], [[3.0]])


def test_different_row_count_fails():
    assert not same_result([["a"]], [["a"], ["b"]])


def test_missing_value_fails():
    assert not same_result([["a", 1]], [["a", 2]])


def test_each_generated_row_is_used_once():
    assert not same_result([["a"], ["a"]], [["a"], ["b"]])


def test_lists_compare_in_order():
    assert same_result([[["A", "B", "C"]]], [[["A", "B", "C"]]])
    assert not same_result([[["A", "B", "C"]]], [[["C", "B", "A"]]])


def test_boolean_is_not_a_number():
    assert not same_result([[True]], [[1]])
