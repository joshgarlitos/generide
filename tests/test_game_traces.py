"""What the recorded game traces say, before any model is compared to them.

These pin the facts the drag model is built on. If a trace is re-recorded and
one of these breaks, the model's assumptions changed with it.
"""

import pytest

from tests import game_traces

NAMES = ["seed_circuit", "evolved_80_pieces", "simple_circuit"]


@pytest.mark.parametrize("name", NAMES)
def test_every_sample_is_matched_to_a_piece_of_the_track(name):
    trace = game_traces.load(name)
    indices = [s["piece_index"] for s in trace["samples"]]

    assert trace["status"] == "rated"
    assert all(i is not None for i in indices)
    assert all(0 <= i < len(trace["segments"]) for i in indices)


@pytest.mark.parametrize("name", NAMES)
def test_the_game_runs_one_train_of_seven_cars_each_weighing_500(name):
    trace = game_traces.load(name)

    assert {s["mass"] for s in trace["samples"]} == {500}
    assert (trace["num_trains"], trace["cars_per_train"]) == (1, 7)


def test_the_flat_coast_after_the_seed_drop_loses_the_speed_the_drag_formula_says():
    """The game's own deceleration at 783k velocity units on flat track.

    OpenRCT2's UpdateTrackMotion subtracts v/4096 and ((v>>8)^2>>4)/mass each
    tick. With the 7 cars the game ran, that is 191 + 166 = 357 units, and the
    log read 357. This is the measurement the simulator's old constant
    friction contradicted.
    """
    samples = game_traces.load("seed_circuit")["samples"]
    flat_coast = [s for s in samples if s["track_type"] == 0 and 770000 < s["velocity"] < 790000]

    assert flat_coast, "the seed trace should coast on flat track after its drop"
    for s in flat_coast:
        v = s["velocity"]
        linear = v // 4096
        squared = ((v >> 8) ** 2 >> 4) / (7 * 500)
        assert -s["acceleration"] == pytest.approx(linear + squared, rel=0.03)
