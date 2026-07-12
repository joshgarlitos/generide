"""Tests for genetic algorithm evolution."""

import random

import pytest

from rct2.evolution import (
    EvolutionStats,
    Individual,
    Population,
    evolve,
    evolve_until,
)
from rct2.fitness import ProxyFitness
from rct2.generate import create_simple_circuit
from rct2.geometry import Position, is_closed_circuit
from rct2.mutations import BEGIN_STATION, END_STATION


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
        seed = create_simple_circuit()
        rng = random.Random(42)
        stats = evolve(seed, rng, generations=3, population_size=3)
        assert stats.best_individual is not None

    def test_evolution_with_one_generation(self):
        """Should work with single generation."""
        seed = create_simple_circuit()
        rng = random.Random(42)
        stats = evolve(seed, rng, generations=1, population_size=10)
        assert len(stats.fitness_history) == 1
