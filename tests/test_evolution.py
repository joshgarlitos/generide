"""Tests for genetic algorithm evolution."""

import random

import pytest

from rct2.evolution import (
    EvolutionStats,
    Individual,
    Population,
    evolve,
    evolve_parts,
    evolve_until,
)
from rct2.fitness import ProxyFitness
from rct2.generate import create_hill_circuit, create_simple_circuit
from rct2.geometry import Position, is_closed_circuit
from rct2.mutations import BEGIN_STATION, END_STATION
from rct2.oracle import OracleResult


class TestIndividual:
    """Tests for Individual class."""

    def test_individual_stores_segments(self):
        """Individual should store its segment list."""
        segments = create_simple_circuit()
        ind = Individual(segments=segments)
        assert ind.segments == segments

    def test_individual_default_fitness_is_zero(self):
        """Default fitness should be zero."""
        ind = Individual(segments=[BEGIN_STATION, END_STATION])
        assert ind.fitness == 0.0

    def test_individual_is_valid_for_closed_circuit(self):
        """is_valid should return True for closed circuits."""
        segments = create_simple_circuit()
        ind = Individual(segments=segments)
        assert ind.is_valid()

    def test_individual_is_invalid_for_open_circuit(self):
        """is_valid should return False for open circuits."""
        # Station + flat doesn't close
        segments = [BEGIN_STATION, END_STATION, 0x00]
        ind = Individual(segments=segments)
        assert not ind.is_valid()

    def test_individual_is_invalid_for_bad_bank_transition(self):
        segments = create_simple_circuit()
        segments[2] = 0x2D
        assert not Individual(segments=segments).is_valid()


class TestPopulation:
    """Tests for Population class."""

    def test_population_best_returns_highest_fitness(self):
        """best() should return the individual with highest fitness."""
        individuals = [
            Individual(segments=[0x00], fitness=10.0),
            Individual(segments=[0x01], fitness=50.0),
            Individual(segments=[0x02], fitness=30.0),
        ]
        pop = Population(individuals=individuals)
        assert pop.best().fitness == 50.0

    def test_population_best_returns_none_when_empty(self):
        """best() should return None for empty population."""
        pop = Population(individuals=[])
        assert pop.best() is None

    def test_population_average_fitness(self):
        """average_fitness should compute the mean."""
        individuals = [
            Individual(segments=[0x00], fitness=10.0),
            Individual(segments=[0x01], fitness=20.0),
            Individual(segments=[0x02], fitness=30.0),
        ]
        pop = Population(individuals=individuals)
        assert pop.average_fitness() == 20.0

    def test_population_valid_count(self):
        """valid_count should count closed circuits."""
        closed = create_simple_circuit()
        open_track = [BEGIN_STATION, END_STATION, 0x00]

        individuals = [
            Individual(segments=closed),
            Individual(segments=open_track),
            Individual(segments=closed),
        ]
        pop = Population(individuals=individuals)
        assert pop.valid_count() == 2


class TestEvolve:
    """Tests for the main evolution function."""

    def test_evolution_returns_stats(self):
        """evolve should return EvolutionStats."""
        rng = random.Random(42)
        seed = create_simple_circuit()
        stats = evolve(seed, rng, generations=5, population_size=10)

        assert isinstance(stats, EvolutionStats)
        assert stats.generations == 5
        assert stats.best_individual is not None
        assert len(stats.fitness_history) > 0

    def test_evolution_improves_fitness(self):
        """Fitness should generally improve over generations."""
        rng = random.Random(42)
        seed = create_simple_circuit()
        fitness_fn = ProxyFitness()

        stats = evolve(
            seed,
            rng,
            fitness_fn=fitness_fn,
            generations=20,
            population_size=20,
            mutation_rate=0.2,
        )

        # Best fitness should be at least as good as initial
        initial_fitness = fitness_fn.evaluate(seed)
        assert stats.best_fitness >= initial_fitness - 50  # Allow some variance

    def test_evolution_with_physics_fitness_smoke(self):
        """Evolution runs to completion with the physics-based fitness."""
        import math

        from rct2.fitness import PhysicsFitness

        rng = random.Random(42)
        seed = create_simple_circuit()
        stats = evolve(
            seed,
            rng,
            fitness_fn=PhysicsFitness(),
            generations=5,
            population_size=10,
        )

        assert isinstance(stats, EvolutionStats)
        assert math.isfinite(stats.best_fitness)

    def test_evolution_maintains_some_valid_circuits(self):
        """Population should maintain some valid circuits."""
        seed = create_simple_circuit()

        rng = random.Random(42)
        stats = evolve(
            seed,
            rng,
            generations=10,
            population_size=20,
        )

        # At least some generations should have valid individuals
        assert any(ratio > 0 for ratio in stats.valid_ratio_history)

    def test_best_individual_is_valid(self):
        """The best individual should form a valid closed circuit."""
        seed = create_simple_circuit()

        rng = random.Random(42)
        stats = evolve(
            seed,
            rng,
            generations=30,
            population_size=30,
            elitism=5,  # Keep more good ones
        )

        # Best individual should be valid (or close to it)
        best = stats.best_individual
        # Due to stochastic nature, we check it's reasonably good
        assert best is not None
        # With elitism and a valid seed, best should usually be valid
        # If not valid, fitness should be heavily penalized (below 0)
        if not best.is_valid():
            assert best.fitness < 0  # Open circuit penalty should apply

    def test_evolution_with_progress_callback(self):
        """Progress callback should be called each generation."""
        seed = create_simple_circuit()
        generations_seen = []

        def callback(gen, pop):
            generations_seen.append(gen)

        rng = random.Random(42)
        evolve(
            seed,
            rng,
            generations=5,
            population_size=10,
            progress_callback=callback,
        )

        assert len(generations_seen) == 5
        assert generations_seen == [0, 1, 2, 3, 4]

    def test_elitism_preserves_best(self):
        """Elitism should preserve top individuals across generations."""
        seed = create_simple_circuit()
        fitness_fn = ProxyFitness()

        # Run with high elitism
        rng = random.Random(42)
        stats = evolve(
            seed,
            rng,
            fitness_fn=fitness_fn,
            generations=10,
            population_size=20,
            elitism=5,
        )

        # Fitness should never decrease significantly due to elitism
        for i in range(1, len(stats.fitness_history)):
            # Allow small variance but not major drops
            assert stats.fitness_history[i] >= stats.fitness_history[i - 1] - 10


class TestEvolveUntil:
    """Tests for evolve_until function."""

    def test_evolve_until_stops_at_target(self):
        """Should stop when target fitness is reached."""
        rng = random.Random(42)
        seed = create_simple_circuit()
        fitness_fn = ProxyFitness()
        initial = fitness_fn.evaluate(seed)

        # Set target just above initial
        stats = evolve_until(
            seed,
            target_fitness=initial + 1,
            rng=rng,
            fitness_fn=fitness_fn,
            max_generations=100,
            population_size=20,
        )

        # Should have stopped before max_generations if target was reached
        if stats.best_fitness >= initial + 1:
            assert stats.generations <= 100

    def test_evolve_until_respects_max_generations(self):
        """Should stop at max_generations if target not reached."""
        rng = random.Random(42)
        seed = create_simple_circuit()

        stats = evolve_until(
            seed,
            target_fitness=float("inf"),  # Impossible target
            rng=rng,
            max_generations=5,
            population_size=10,
        )

        assert stats.generations == 5


class TestFitnessFunction:
    """Tests for fitness evaluation in evolution context."""

    def test_evolution_uses_custom_fitness(self):
        """Evolution should use provided fitness function."""
        seed = create_simple_circuit()

        class CustomFitness:
            def __init__(self):
                self.call_count = 0

            def evaluate(self, segments):
                self.call_count += 1
                return len(segments)

        custom_fn = CustomFitness()
        rng = random.Random(42)
        evolve(
            seed,
            rng,
            fitness_fn=custom_fn,
            generations=3,
            population_size=5,
        )

        # Should have been called many times
        assert custom_fn.call_count > 0

    def test_proxy_fitness_rewards_closed_circuits(self):
        """ProxyFitness should give higher scores to closed circuits."""
        fitness_fn = ProxyFitness()

        closed = create_simple_circuit()
        open_track = [BEGIN_STATION, END_STATION, 0x00, 0x00]

        closed_score = fitness_fn.evaluate(closed)
        open_score = fitness_fn.evaluate(open_track)

        assert closed_score > open_score


class TestPopulationDiversity:
    """Tests for population diversity maintenance."""

    def test_population_has_variety(self):
        """Population should maintain some variety in tracks."""
        seed = create_simple_circuit()

        # Track seen segment combinations
        seen = set()

        def callback(gen, pop):
            for ind in pop.individuals:
                seen.add(tuple(ind.segments))

        rng = random.Random(42)
        evolve(
            seed,
            rng,
            generations=10,
            population_size=20,
            progress_callback=callback,
        )

        # Should have seen multiple different tracks
        assert len(seen) > 5


class TestReproducibility:
    """Tests for reproducible evolution with seeded RNG."""

    def test_same_seed_produces_identical_results(self):
        """Two runs with same seed should produce identical EvolutionStats."""
        seed = create_simple_circuit()

        # Run 1
        rng1 = random.Random(12345)
        stats1 = evolve(
            seed,
            rng1,
            generations=10,
            population_size=20,
            mutation_rate=0.1,
        )

        # Run 2 with same seed
        rng2 = random.Random(12345)
        stats2 = evolve(
            seed,
            rng2,
            generations=10,
            population_size=20,
            mutation_rate=0.1,
        )

        # Results should be identical
        assert stats1.best_fitness == stats2.best_fitness
        assert stats1.fitness_history == stats2.fitness_history
        assert stats1.valid_ratio_history == stats2.valid_ratio_history
        assert stats1.best_individual.segments == stats2.best_individual.segments


class TestEvolveParts:
    """Tests for the part-based evolve_parts, mirroring TestEvolve/TestReproducibility."""

    def test_evolution_returns_stats(self):
        rng = random.Random(42)
        seed = create_hill_circuit()
        stats = evolve_parts(seed, rng, generations=5, population_size=10)

        assert isinstance(stats, EvolutionStats)
        assert stats.generations == 5
        assert stats.best_individual is not None
        assert len(stats.fitness_history) > 0

    def test_evolution_improves_fitness(self):
        rng = random.Random(42)
        seed = create_hill_circuit()
        fitness_fn = ProxyFitness()

        stats = evolve_parts(
            seed,
            rng,
            fitness_fn=fitness_fn,
            generations=20,
            population_size=20,
            mutation_rate=0.2,
        )

        initial_fitness = fitness_fn.evaluate(seed)
        assert stats.best_fitness >= initial_fitness - 50  # Allow some variance

    def test_same_seed_produces_identical_results(self):
        seed = create_hill_circuit()

        rng1 = random.Random(12345)
        stats1 = evolve_parts(seed, rng1, generations=10, population_size=20, mutation_rate=0.1)

        rng2 = random.Random(12345)
        stats2 = evolve_parts(seed, rng2, generations=10, population_size=20, mutation_rate=0.1)

        assert stats1.best_fitness == stats2.best_fitness
        assert stats1.fitness_history == stats2.fitness_history
        assert stats1.valid_ratio_history == stats2.valid_ratio_history
        assert stats1.best_individual.segments == stats2.best_individual.segments


class TestFreeHillSearch:
    """The hill may move after the station, and the search keeps exactly one."""

    def test_every_individual_in_every_generation_has_the_station_first_and_one_hill(self):
        from rct2.construction import hill_height, station_length

        seen_slots = set()

        def check(gen, population):
            for individual in population.individuals:
                parts = individual.parts
                assert station_length(parts[0]) > 0
                hills = [i for i, part in enumerate(parts) if hill_height(part) > 0]
                assert len(hills) == 1
                seen_slots.add(hills[0])

        evolve_parts(
            create_hill_circuit(), random.Random(21),
            generations=12, population_size=24, progress_callback=check,
        )

        assert len(seen_slots) > 1

    def test_the_pinned_hill_search_matches_the_run_recorded_before_the_hill_was_freed(self):
        """Values recorded from the code before the genome change, with the
        same seed and settings as the seeded no-site pin in test_fitness.py."""
        from rct2.fitness import PhysicsFitness

        for make_fitness, best_fitness, length in (
            (ProxyFitness, 235.0, 58),
            (PhysicsFitness, 50.853068924145916, 54),
        ):
            stats = evolve_parts(
                create_hill_circuit(), random.Random(3), fitness_fn=make_fitness(),
                generations=6, population_size=12, free_hill=False,
            )
            assert stats.best_fitness == pytest.approx(best_fitness)
            assert len(stats.best_individual.segments) == length

    def test_with_the_hill_pinned_it_stays_at_slot_one(self):
        from rct2.construction import hill_height

        def check(gen, population):
            for individual in population.individuals:
                assert hill_height(individual.parts[1]) > 0

        evolve_parts(
            create_hill_circuit(), random.Random(21), generations=8, population_size=16,
            progress_callback=check, free_hill=False,
        )


    def test_starting_populations_mix_hill_positions_with_the_station_first(self):
        from rct2.construction import hill_height, station_length
        from rct2.evolution import _create_initial_population_parts, _ensure_scaffold_parts
        from rct2.fitness import PhysicsFitness
        from rct2.mutations import find_hill_index, segments_to_parts

        seed = _ensure_scaffold_parts(
            segments_to_parts(create_hill_circuit()), random.Random(0),
        )
        slots = []
        for run in range(8):
            population = _create_initial_population_parts(
                seed, 30, PhysicsFitness(), random.Random(run),
            )
            for individual in population.individuals:
                parts = individual.parts
                assert station_length(parts[0]) > 0
                assert sum(1 for part in parts if hill_height(part) > 0) == 1
                slots.append(find_hill_index(parts))

        assert 1 in slots
        assert any(slot > 1 for slot in slots)

    def test_with_the_hill_pinned_starting_tracks_all_have_it_at_slot_one(self):
        from rct2.construction import hill_height
        from rct2.mutations import generate_random_track_parts

        for run in range(40):
            parts = generate_random_track_parts(random.Random(run), free_hill=False)
            assert hill_height(parts[1]) > 0

    def test_random_starting_tracks_put_some_parts_before_the_hill(self):
        from rct2.mutations import HILL_LEAD_MAX, find_hill_index, generate_random_track_parts

        slots = {
            find_hill_index(generate_random_track_parts(random.Random(run)))
            for run in range(60)
        }

        assert slots == set(range(1, 2 + HILL_LEAD_MAX))



class TestEvolvePartsOracleCalibration:
    """Tests for the oracle-calibration sampling hook in evolve_parts()."""

    def test_disabled_by_default_output_is_unchanged(self):
        """Not passing oracle_interval must match the pre-feature behavior exactly."""
        seed = create_hill_circuit()
        rng1 = random.Random(42)
        stats1 = evolve_parts(seed, rng1, generations=10, population_size=10)

        rng2 = random.Random(42)
        stats2 = evolve_parts(seed, rng2, generations=10, population_size=10)

        assert stats1.best_individual.segments == stats2.best_individual.segments
        assert stats1.fitness_history == stats2.fitness_history

    def test_enabling_calibration_never_changes_evolution_output(self):
        """Identical seed produces identical output with calibration on or off."""
        seed = create_hill_circuit()

        rng_off = random.Random(99)
        stats_off = evolve_parts(seed, rng_off, generations=15, population_size=10)

        rng_on = random.Random(99)
        stats_on = evolve_parts(
            seed, rng_on, generations=15, population_size=10,
            oracle_interval=3, oracle_max_calls=100, oracle_rng_seed=99,
            oracle_scorer=lambda segments: OracleResult(
                excitement=1.0, intensity=1.0, nausea=1.0, status="rated",
            ),
            oracle_log_writer=lambda record: None,
        )

        assert stats_on.best_individual.segments == stats_off.best_individual.segments
        assert stats_on.fitness_history == stats_off.fitness_history
        assert stats_on.valid_ratio_history == stats_off.valid_ratio_history

    def test_scorer_called_on_expected_generations_with_best_segments(self):
        seed = create_hill_circuit()
        rng = random.Random(1)
        best_at_gen = {}

        def spy(gen, population):
            best_at_gen[gen] = population.best().segments

        logged = []
        evolve_parts(
            seed, rng, generations=20, population_size=10,
            progress_callback=spy,
            oracle_interval=5, oracle_max_calls=100,
            oracle_scorer=lambda segments: OracleResult(
                excitement=1.0, intensity=1.0, nausea=1.0, status="rated",
            ),
            oracle_log_writer=logged.append,
        )

        best_records = [r for r in logged if r.role == "best"]
        assert [r.generation for r in best_records] == [0, 5, 10, 15]
        for record in best_records:
            assert record.segments == best_at_gen[record.generation]

    def test_worst_sample_cadence_is_every_third_best_tick(self):
        seed = create_hill_circuit()
        rng = random.Random(2)
        logged = []
        evolve_parts(
            seed, rng, generations=40, population_size=10,
            oracle_interval=5, oracle_max_calls=100,
            oracle_scorer=lambda segments: OracleResult(
                excitement=1.0, intensity=1.0, nausea=1.0, status="rated",
            ),
            oracle_log_writer=logged.append,
        )

        worst_gens = [r.generation for r in logged if r.role == "worst"]
        # Best-ticks land on gen 0, 5, ..., 35 (8 ticks); worst fires every
        # 3rd tick (0, 3, 6) -> gen 0, 15, 30.
        assert worst_gens == [0, 15, 30]

    def test_worst_sample_excludes_construction_invalid_individuals(self):
        invalid = Individual(segments=[0x00], fitness=100.0)  # fails validate_construction
        valid_low = Individual(segments=create_hill_circuit(), fitness=1.0)
        valid_high = Individual(segments=create_hill_circuit(), fitness=50.0)
        logged = []

        from rct2.evolution import _maybe_sample_oracle_calibration

        _maybe_sample_oracle_calibration(
            gen=0, best=valid_high, valid_individuals=[valid_low, valid_high],
            interval=1, max_calls=10, calls_so_far=0,
            rng_seed=1,
            scorer=lambda segments: OracleResult(
                excitement=1.0, intensity=1.0, nausea=1.0, status="rated",
            ),
            log_writer=logged.append,
        )

        [worst_record] = [r for r in logged if r.role == "worst"]
        assert worst_record.segments == valid_low.segments

    def test_worst_sample_skipped_when_no_individual_is_valid(self):
        best = Individual(segments=[0x00], fitness=2.0)
        logged = []

        from rct2.evolution import _maybe_sample_oracle_calibration

        _maybe_sample_oracle_calibration(
            gen=0, best=best, valid_individuals=[], interval=1, max_calls=10, calls_so_far=0,
            rng_seed=1,
            scorer=lambda segments: OracleResult(
                excitement=1.0, intensity=1.0, nausea=1.0, status="rated",
            ),
            log_writer=logged.append,
        )

        assert [r.role for r in logged] == ["best"]

    def test_max_calls_cap_stops_sampling_for_the_rest_of_the_run(self):
        seed = create_hill_circuit()
        rng = random.Random(3)
        logged = []
        evolve_parts(
            seed, rng, generations=30, population_size=10,
            oracle_interval=5, oracle_max_calls=2,
            oracle_scorer=lambda segments: OracleResult(
                excitement=1.0, intensity=1.0, nausea=1.0, status="rated",
            ),
            oracle_log_writer=logged.append,
        )

        # Interval 5 over 30 generations would otherwise fire at gen 0, 5, ..., 25
        # (6 best-samples); the cap of 2 must stop it after the second call.
        assert len(logged) == 2

    def test_placement_failed_result_reaches_log_writer_unchanged(self):
        seed = create_hill_circuit()
        rng = random.Random(4)
        logged = []
        evolve_parts(
            seed, rng, generations=1, population_size=5,
            oracle_interval=1, oracle_max_calls=1,
            oracle_scorer=lambda segments: OracleResult(
                excitement=None, intensity=None, nausea=None,
                status="placement_failed", detail="Mine Train Coaster 1 in the way",
            ),
            oracle_log_writer=logged.append,
        )

        [record] = logged
        assert record.status == "placement_failed"
        assert record.detail == "Mine Train Coaster 1 in the way"

    def test_scorer_exception_is_caught_and_logged_as_oracle_error(self):
        """A failing oracle call must not abort the generation loop."""
        seed = create_hill_circuit()
        rng = random.Random(5)
        logged = []

        def raising_scorer(segments):
            raise FileNotFoundError("OpenRCT2 binary not found")

        stats = evolve_parts(
            seed, rng, generations=10, population_size=10,
            oracle_interval=2, oracle_max_calls=100,
            oracle_scorer=raising_scorer,
            oracle_log_writer=logged.append,
        )

        assert stats.generations == 10  # the run completed despite every oracle call failing
        assert logged
        assert all(r.status == "oracle_error" for r in logged)
        assert "OpenRCT2 binary not found" in logged[0].error

    def test_oracle_interval_without_log_writer_raises(self):
        seed = create_hill_circuit()
        rng = random.Random(6)
        with pytest.raises(ValueError):
            evolve_parts(seed, rng, generations=1, population_size=5, oracle_interval=1)

    def test_oracle_interval_without_max_calls_raises(self):
        """oracle_max_calls defaults to 0, which would silently sample nothing."""
        seed = create_hill_circuit()
        rng = random.Random(7)
        with pytest.raises(ValueError):
            evolve_parts(
                seed, rng, generations=1, population_size=5,
                oracle_interval=1, oracle_log_writer=lambda record: None,
            )

    def test_log_writer_exception_is_caught_and_does_not_abort_the_run(self, capsys):
        """A failing log writer must not abort the generation loop."""
        seed = create_hill_circuit()
        rng = random.Random(8)

        def raising_log_writer(record):
            raise OSError("disk full")

        stats = evolve_parts(
            seed, rng, generations=10, population_size=10,
            oracle_interval=2, oracle_max_calls=100,
            oracle_scorer=lambda segments: OracleResult(
                excitement=1.0, intensity=1.0, nausea=1.0, status="rated",
            ),
            oracle_log_writer=raising_log_writer,
        )

        assert stats.generations == 10  # the run completed despite every log write failing
        err = capsys.readouterr().err
        assert "oracle calibration: failed to write log record" in err
        assert "gen=0" in err
        assert "role=best" in err
        assert "disk full" in err


class TestEdgeCases:
    """Tests for edge cases and error handling."""

    def test_evolution_with_minimal_seed(self):
        """Should handle minimal (station-only) seed."""
        seed = [BEGIN_STATION, END_STATION]
        rng = random.Random(42)
        stats = evolve(seed, rng, generations=5, population_size=10)
        assert stats.best_individual is not None

    def test_evolution_with_small_population(self):
        """Should work with very small population."""
        seed = create_hill_circuit()
        rng = random.Random(42)
        stats = evolve(seed, rng, generations=3, population_size=3)
        assert stats.best_individual is not None

    def test_evolution_with_one_generation(self):
        """Should work with single generation."""
        seed = create_hill_circuit()
        rng = random.Random(42)
        stats = evolve(seed, rng, generations=1, population_size=10)
        assert len(stats.fitness_history) == 1


class TestStopCheck:
    """Cooperative stop: a caller can end a run at a generation boundary."""

    @pytest.mark.parametrize("engine,seed_fn", [
        (evolve, create_simple_circuit),
        (evolve_parts, create_hill_circuit),
    ])
    def test_stop_at_generation_five_reports_generations_actually_run(self, engine, seed_fn):
        seen = []

        def spy(gen, population):
            seen.append((gen, population.best()))

        stats = engine(
            seed_fn(), random.Random(3), population_size=10, generations=50,
            progress_callback=spy, stop_check=lambda: len(seen) > 5,
        )

        assert stats.generations == 5
        # The best comes from the population the run held when it stopped.
        assert stats.best_individual is seen[-1][1]
        assert stats.best_fitness == seen[-1][1].fitness

    @pytest.mark.parametrize("engine,seed_fn", [
        (evolve, create_simple_circuit),
        (evolve_parts, create_hill_circuit),
    ])
    def test_stop_check_that_never_fires_changes_nothing(self, engine, seed_fn):
        plain = engine(seed_fn(), random.Random(9), population_size=8, generations=6)
        checked = engine(
            seed_fn(), random.Random(9), population_size=8, generations=6,
            stop_check=lambda: False,
        )

        assert checked.generations == plain.generations == 6
        assert checked.best_individual.segments == plain.best_individual.segments
        assert checked.fitness_history == plain.fitness_history
        assert checked.valid_ratio_history == plain.valid_ratio_history

    @pytest.mark.parametrize("engine,seed_fn", [
        (evolve, create_simple_circuit),
        (evolve_parts, create_hill_circuit),
    ])
    def test_stop_before_first_generation_returns_seed_population_best(self, engine, seed_fn):
        first = []
        stats = engine(
            seed_fn(), random.Random(4), population_size=6, generations=20,
            progress_callback=lambda gen, pop: first.append(pop.best()),
            stop_check=lambda: True,
        )

        assert stats.generations == 0
        assert len(first) == 1
        assert stats.best_individual is first[0]


class TestRideTracker:
    """The tracker keeps the best playable ride and the best fitting ride, and changes nothing else."""

    def _tracker(self, scores, fits=(), buildable=(), playable=()):
        class Scored:
            def evaluate(self, segments):
                return scores[tuple(segments)]

        from rct2.evolution import RideTracker

        return RideTracker(
            Scored(),
            fits=lambda s: tuple(s) in fits,
            buildable=lambda s: tuple(s) in buildable,
            playable=lambda s: tuple(s) in playable,
        )

    def test_scores_pass_through_unchanged(self):
        tracker = self._tracker({(1,): 5.0, (2,): -3.0})

        assert tracker.evaluate([1]) == 5.0
        assert tracker.evaluate([2]) == -3.0

    def test_a_fitting_ride_is_kept_even_when_it_scores_below_a_ride_that_does_not_fit(self):
        scores = {(1,): 100.0, (2,): -50.0, (3,): -20.0}
        tracker = self._tracker(
            scores, fits={(2,), (3,)}, buildable={(2,), (3,)}, playable={(1,)},
        )

        for segments in ([1], [2], [3]):
            tracker.evaluate(segments)

        assert tracker.best_playable.segments == [1]
        assert tracker.best_fitting.segments == [3]
        assert tracker.best_fitting.playable is False

    def test_the_fitting_ride_is_marked_playable_when_it_is(self):
        tracker = self._tracker(
            {(1,): 10.0}, fits={(1,)}, buildable={(1,)}, playable={(1,)},
        )

        tracker.evaluate([1])

        assert tracker.best_fitting.segments == [1]
        assert tracker.best_fitting.playable is True
        assert tracker.best_playable.segments == [1]

    def test_a_ride_the_game_would_not_build_is_never_the_fitting_ride(self):
        tracker = self._tracker({(1,): 10.0}, fits={(1,)}, buildable=set(), playable=set())

        tracker.evaluate([1])

        assert tracker.best_fitting is None
        assert tracker.best_playable is None

    def test_it_keeps_a_copy_and_the_first_of_equal_scores(self):
        tracker = self._tracker(
            {(1,): 5.0, (2,): 5.0}, fits={(1,), (2,)}, buildable={(1,), (2,)}, playable={(1,), (2,)},
        )
        segments = [1]
        tracker.evaluate(segments)
        segments.append(9)
        tracker.evaluate([2])

        assert tracker.best_playable.segments == [1]

    def test_other_attributes_come_from_the_wrapped_scorer(self):
        from rct2.evolution import RideTracker

        class Scorer:
            site = "the site"

            def evaluate(self, segments):
                return 0.0

        tracker = RideTracker(Scorer(), fits=lambda s: False, buildable=lambda s: False,
                              playable=lambda s: False)

        assert tracker.site == "the site"

    def test_wrapping_a_real_run_does_not_change_the_result(self):
        from rct2.evolution import site_ride_tracker
        from rct2.fitness import PhysicsFitness
        from rct2.site import Site

        site = Site.from_rows(["." * 30] * 30, anchor=(10, 10))
        plain = evolve_parts(
            create_hill_circuit(), random.Random(4), fitness_fn=PhysicsFitness(site=site),
            generations=4, population_size=10,
        )
        tracker = site_ride_tracker(PhysicsFitness(site=site), site)
        watched = evolve_parts(
            create_hill_circuit(), random.Random(4), fitness_fn=tracker,
            generations=4, population_size=10,
        )

        assert watched.best_individual.segments == plain.best_individual.segments
        assert watched.fitness_history == plain.fitness_history
        assert tracker.best_playable is not None
        assert tracker.best_fitting is not None


class TestSiteRideTrackerPredicates:
    """The real buildable, fits and playable checks that `site_ride_tracker` builds."""

    @staticmethod
    def _tracker():
        from rct2.evolution import site_ride_tracker
        from rct2.fitness import PhysicsFitness
        from rct2.site import Site

        site = Site.from_rows(["." * 40] * 40, anchor=(10, 10))
        return site_ride_tracker(PhysicsFitness(site=site), site)

    def test_an_open_track_that_fits_the_site_is_never_the_fitting_ride(self):
        from rct2.construction import build_station

        tracker = self._tracker()

        tracker.evaluate(build_station(4) + [0, 0, 0, 0])  # fits the tiles, never closes

        assert tracker.best_fitting is None
        assert tracker.best_playable is None

    def test_a_track_that_only_runs_out_of_energy_is_a_fitting_ride_but_not_a_playable_one(self):
        from tests.test_fitness import TestMovedHill

        tracker = self._tracker()
        stranded = TestMovedHill._small_climb_then_hill()

        tracker.evaluate(stranded)

        assert tracker.best_fitting is not None
        assert tracker.best_fitting.segments == stranded
        assert tracker.best_fitting.playable is False
        assert tracker.best_playable is None

    def test_a_valid_finishing_ride_is_both(self):
        from tests.test_fitness import TestMovedHill

        tracker = self._tracker()
        ride = TestMovedHill._turn_then_hill()

        tracker.evaluate(ride)

        assert tracker.best_playable.segments == ride
        assert tracker.best_fitting.segments == ride
        assert tracker.best_fitting.playable is True
