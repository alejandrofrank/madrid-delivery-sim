"""Exact assignment behavior without database, provider, or road access."""

import itertools
import random

import pytest

from delivery.dispatch_optimizer import Candidate, optimize_dispatch


def selected_pairs(candidates):
    return {(c.order_id, c.courier_id) for c in optimize_dispatch(candidates)}


def test_global_assignment_escapes_greedy_trap():
    candidates = [
        Candidate("a", "near", 1, 0),
        Candidate("a", "other", 2, 1),
        Candidate("b", "near", 2, 0),
        Candidate("b", "other", 100, 1),
    ]
    chosen = optimize_dispatch(candidates)
    assert selected_pairs(candidates) == {("a", "other"), ("b", "near")}
    assert sum(c.cost for c in chosen) == 4


def test_nearest_courier_wins_over_courier_01_label():
    assert selected_pairs(
        [Candidate("meal", "courier-01", 900, 0), Candidate("meal", "courier-99", 120, 1)]
    ) == {("meal", "courier-99")}


def test_sparse_feasibility_never_invents_edges_or_reuses_couriers():
    candidates = [
        Candidate("a", "shared", 1),
        Candidate("b", "shared", 2),
        Candidate("c", "only-c", 50, 1),
    ]
    assert selected_pairs(candidates) == {("a", "shared"), ("c", "only-c")}
    assert optimize_dispatch([]) == ()


def test_cardinality_has_priority_even_for_unbounded_integer_costs():
    candidates = [
        Candidate("a", "x", 10**100, 0),
        Candidate("a", "y", 0, 1),
        Candidate("b", "y", 10**100, 1),
    ]
    assert selected_pairs(candidates) == {("a", "x"), ("b", "y")}


def test_primary_cost_has_priority_over_arbitrarily_large_fair_ranks():
    assert selected_pairs(
        [Candidate("a", "cheap", 0, 10**100), Candidate("a", "expensive", 1, 0)]
    ) == {("a", "cheap")}


def test_ties_use_caller_fair_rank_instead_of_alphabetical_id():
    assert selected_pairs(
        [Candidate("a", "courier-01", 10, 8), Candidate("a", "courier-99", 10, 0)]
    ) == {("a", "courier-99")}


def test_tied_batch_is_stable_for_every_input_permutation():
    candidates = [
        Candidate(order, courier, 10, rank)
        for order in ("a", "b")
        for rank, courier in enumerate(("z", "x"))
    ]
    expected = optimize_dispatch(candidates)
    assert len(expected) == 2
    assert tuple(c.order_id for c in expected) == ("a", "b")
    for permutation in itertools.permutations(candidates):
        assert optimize_dispatch(iter(permutation)) == expected


def test_renaming_couriers_does_not_change_rank_assignment():
    def ranks_by_order(names):
        return {
            c.order_id: c.tie_break_rank
            for c in optimize_dispatch(
                Candidate(order, courier, 1, rank)
                for order in ("a", "b", "c")
                for rank, courier in enumerate(names)
            )
        }

    assert ranks_by_order(("z", "a", "m")) == ranks_by_order(("a", "z", "b"))


def test_duplicate_pairs_are_rejected_even_with_different_costs():
    with pytest.raises(ValueError, match="duplicate candidate pair"):
        optimize_dispatch([Candidate("a", "x", 1), Candidate("a", "x", 2)])


@pytest.mark.parametrize("value", [-1, 0.5, float("inf"), float("nan"), True, "3", None])
@pytest.mark.parametrize("field", ["cost", "tie_break_rank"])
def test_invalid_costs_and_ranks_are_rejected(field, value):
    args = {"order_id": "a", "courier_id": "x", "cost": 0, "tie_break_rank": 0}
    args[field] = value
    with pytest.raises(ValueError, match="finite nonnegative integer"):
        Candidate(**args)


@pytest.mark.parametrize("value", ["", "   ", 1, None])
@pytest.mark.parametrize("field", ["order_id", "courier_id"])
def test_invalid_identifiers_are_rejected(field, value):
    args = {"order_id": "a", "courier_id": "x", "cost": 0}
    args[field] = value
    with pytest.raises(ValueError, match="nonempty string"):
        Candidate(**args)


@pytest.mark.parametrize("limit", [0, -1, 101, True, 1.5])
@pytest.mark.parametrize("field", ["max_orders", "max_couriers"])
def test_configured_limits_cannot_bypass_hard_bounds(field, limit):
    with pytest.raises(ValueError, match="integer from 1 to 100"):
        optimize_dispatch([], **{field: limit})


def test_unique_order_and_courier_limits_are_enforced():
    with pytest.raises(ValueError, match="bounded"):
        optimize_dispatch(Candidate(str(i), "x", 0) for i in range(101))
    with pytest.raises(ValueError, match="bounded"):
        optimize_dispatch(Candidate("a", str(i), 0) for i in range(101))
    with pytest.raises(ValueError, match="bounded"):
        optimize_dispatch([Candidate("a", "x", 0), Candidate("b", "y", 0)], max_orders=1)
    with pytest.raises(ValueError, match="bounded"):
        optimize_dispatch([Candidate("a", "x", 0), Candidate("b", "y", 0)], max_couriers=1)
    with pytest.raises(TypeError, match="Candidate instances"):
        optimize_dispatch([("a", "x", 1)])


def test_hard_bound_accepts_a_complete_hundred_by_hundred_batch():
    chosen = optimize_dispatch(
        Candidate(str(order), str(courier), abs(order - courier), courier)
        for order in range(100)
        for courier in range(100)
    )
    assert len(chosen) == 100
    assert sum(c.cost for c in chosen) == 0


def test_small_random_graphs_match_exhaustive_optima():
    rng = random.Random(827)
    for _ in range(40):
        candidates = [
            Candidate(str(order), str(courier), rng.randrange(8), courier)
            for order in range(3)
            for courier in range(3)
            if rng.random() < 0.7
        ]
        feasible = []
        for size in range(4):
            for subset in itertools.combinations(candidates, size):
                if len({c.order_id for c in subset}) == size == len({c.courier_id for c in subset}):
                    feasible.append(subset)

        def objective(selection):
            return (
                -len(selection),
                sum(c.cost for c in selection),
                sum(c.tie_break_rank for c in selection),
            )

        assert objective(optimize_dispatch(candidates)) == min(map(objective, feasible))
