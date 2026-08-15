"""Tests for the headless oracle's non-game-dependent parts."""

from rct2.oracle import _build_plugin_source, _parse_result


def test_parses_a_rated_result():
    result = _parse_result("'GENERIDE_RESULT|status=rated|E=652|I=498|N=310'")
    assert result.status == "rated"
    assert result.excitement == 6.52
    assert result.intensity == 4.98
    assert result.nausea == 3.10


def test_parses_a_failure_with_no_ratings():
    result = _parse_result("'GENERIDE_RESULT|status=timeout'")
    assert result.status == "timeout"
    assert result.excitement is None
    assert result.intensity is None
    assert result.nausea is None


def test_parses_a_failure_with_a_detail():
    # Real OpenRCT2 output wraps each line in quotes and an ANSI reset code,
    # e.g. "'GENERIDE_RESULT|status=placement_failed:piece_20_type_12'\x1b[0m".
    result = _parse_result(
        "'GENERIDE_RESULT|status=placement_failed:piece_20_type_12'\x1b[0m"
    )
    assert result.status == "placement_failed"
    assert result.detail == "piece_20_type_12"


def test_ignores_lines_without_a_result():
    assert _parse_result("'GENERIDE_PLACE|i=0|type=1|error=0|msg='") is None
    assert _parse_result("just some other output") is None


def test_plugin_source_embeds_the_segment_list_and_build_site():
    source = _build_plugin_source([0, 4, 4, 9], base_x_tile=100, base_y_tile=100,
                                   timeout_ticks=2000, level_radius=20)
    assert "[0, 4, 4, 9]" in source
    assert "BASE_X_TILE = 100" in source
    assert "BASE_Y_TILE = 100" in source
    assert "registerPlugin" in source
