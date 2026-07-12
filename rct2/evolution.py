"""Genetic algorithm engine for evolving coaster tracks.

Provides population management and evolution loop for optimizing
track designs according to a pluggable fitness function.
"""

import random
from dataclasses import dataclass, field
from typing import Callable, Optional

from rct2.construction import validate_construction
from rct2.fitness import FitnessFunction, ProxyFitness
from rct2.mutations import (
    BEGIN_STATION,
    END_STATION,
    crossover,
    generate_random_track,
    mutate,
    repair_circuit,
)


@dataclass
class Individual:
    """A single track design with its fitness score."""

    segments: list[int]
    fitness: float = 0.0

    def is_valid(self) -> bool:
        """Check whether this individual passes all construction rules."""
        return validate_construction(self.segments).valid


@dataclass
class Population:
    """A population of track designs."""

    individuals: list[Individual] = field(default_factory=list)

    def best(self) -> Optional[Individual]:
        """Return the individual with highest fitness."""
        if not self.individuals:
            return None
        return max(self.individuals, key=lambda ind: ind.fitness)

    def average_fitness(self) -> float:
        """Return the average fitness of the population."""
        if not self.individuals:
            return 0.0
        return sum(ind.fitness for ind in self.individuals) / len(self.individuals)

    def valid_count(self) -> int:
        """Return the number of construction-valid individuals."""
        return sum(1 for ind in self.individuals if ind.is_valid())


@dataclass
class EvolutionStats:
    """Statistics from an evolution run."""

    generations: int
    best_fitness: float
    best_individual: Individual
    fitness_history: list[float]
    valid_ratio_history: list[float]


def _ensure_station(segments: list[int]) -> list[int]:
    """Ensure segments start with station pieces."""
    result = segments.copy()
    if len(result) == 0 or result[0] != BEGIN_STATION:
        result.insert(0, BEGIN_STATION)
    if len(result) < 2 or result[1] != END_STATION:
        result.insert(1, END_STATION)
    return result


def _create_initial_population(
    seed: list[int],
    population_size: int,
    fitness_fn: FitnessFunction,
    rng: random.Random,
) -> Population:
    """Create initial population from seed and random variations."""
    individuals = []

    # Add seed individual
    seed_with_station = _ensure_station(seed)
    seed_ind = Individual(segments=seed_with_station)
    seed_ind.fitness = fitness_fn.evaluate(seed_ind.segments)
    individuals.append(seed_ind)

    # Fill rest with mutations of seed and random tracks
    while len(individuals) < population_size:
        if rng.random() < 0.7:
            # Mutate seed
            mutated = mutate(seed_with_station, rng, rate=0.3)
            mutated = _ensure_station(mutated)
        else:
            # Generate random track
            mutated = generate_random_track(rng)

        # Try to repair
        repaired = repair_circuit(mutated, rng)
        if repaired is not None:
            mutated = repaired

        ind = Individual(segments=mutated)
        ind.fitness = fitness_fn.evaluate(ind.segments)
        individuals.append(ind)

    return Population(individuals=individuals)


def _tournament_select(
    population: Population,
    rng: random.Random,
    tournament_size: int = 3,
) -> Individual:
    """Select an individual using tournament selection."""
    candidates = rng.sample(population.individuals, min(tournament_size, len(population.individuals)))
    return max(candidates, key=lambda ind: ind.fitness)


def _create_offspring(
    parent1: Individual,
    parent2: Individual,
    mutation_rate: float,
    fitness_fn: FitnessFunction,
    rng: random.Random,
) -> list[Individual]:
    """Create offspring from two parents via crossover and mutation."""
    offspring = []

    # Crossover
    child1_segs, child2_segs = crossover(parent1.segments, parent2.segments, rng)

    for child_segs in [child1_segs, child2_segs]:
        # Ensure station
        child_segs = _ensure_station(child_segs)

        # Mutate
        child_segs = mutate(child_segs, rng, rate=mutation_rate)
        child_segs = _ensure_station(child_segs)

        # Try to repair
        repaired = repair_circuit(child_segs, rng)
        if repaired is not None:
            child_segs = repaired

        child = Individual(segments=child_segs)
        child.fitness = fitness_fn.evaluate(child.segments)
        offspring.append(child)

    return offspring


def evolve(
    seed: list[int],
    rng: random.Random,
    fitness_fn: Optional[FitnessFunction] = None,
    population_size: int = 50,
    generations: int = 100,
    mutation_rate: float = 0.1,
    elitism: int = 2,
    tournament_size: int = 3,
    progress_callback: Optional[Callable[[int, Population], None]] = None,
) -> EvolutionStats:
    """Run genetic algorithm to evolve optimal tracks.

    Args:
        seed: Initial track segment list to evolve from
        rng: Random number generator for reproducible runs
        fitness_fn: Fitness evaluation function (defaults to ProxyFitness)
        population_size: Number of individuals in population
        generations: Number of evolution generations
        mutation_rate: Probability of mutation per segment
        elitism: Number of best individuals to preserve each generation
        tournament_size: Number of candidates for tournament selection
        progress_callback: Optional callback(generation, population) for progress

    Returns:
        EvolutionStats with best individual and history
    """
    if fitness_fn is None:
        fitness_fn = ProxyFitness()

    # Initialize population
    population = _create_initial_population(seed, population_size, fitness_fn, rng)

    fitness_history = []
    valid_ratio_history = []

    for gen in range(generations):
        # Record statistics
        best = population.best()
        if best:
            fitness_history.append(best.fitness)
        valid_ratio_history.append(
            population.valid_count() / len(population.individuals)
            if population.individuals else 0.0
        )

        # Progress callback
        if progress_callback:
            progress_callback(gen, population)

        # Sort by fitness (descending)
        population.individuals.sort(key=lambda ind: ind.fitness, reverse=True)

        # Create next generation
        next_gen = []

        # Elitism: keep best individuals
        next_gen.extend(population.individuals[:elitism])

        # Fill rest with offspring
        while len(next_gen) < population_size:
            parent1 = _tournament_select(population, rng, tournament_size)
            parent2 = _tournament_select(population, rng, tournament_size)
            offspring = _create_offspring(parent1, parent2, mutation_rate, fitness_fn, rng)
            next_gen.extend(offspring)

        # Trim to population size
        next_gen = next_gen[:population_size]
        population = Population(individuals=next_gen)

    # Final statistics
    best = population.best()
    return EvolutionStats(
        generations=generations,
        best_fitness=best.fitness if best else 0.0,
        best_individual=best if best else Individual(segments=seed),
        fitness_history=fitness_history,
        valid_ratio_history=valid_ratio_history,
    )


def evolve_until(
    seed: list[int],
    target_fitness: float,
    rng: random.Random,
    fitness_fn: Optional[FitnessFunction] = None,
    max_generations: int = 1000,
    population_size: int = 50,
    mutation_rate: float = 0.1,
) -> EvolutionStats:
    """Evolve until reaching a target fitness or max generations.

    Args:
        seed: Initial track segment list
        target_fitness: Stop when fitness reaches this value
        rng: Random number generator for reproducible runs
        fitness_fn: Fitness evaluation function
        max_generations: Maximum generations to run
        population_size: Number of individuals in population
        mutation_rate: Probability of mutation

    Returns:
        EvolutionStats with best individual
    """
    if fitness_fn is None:
        fitness_fn = ProxyFitness()

    population = _create_initial_population(seed, population_size, fitness_fn, rng)
    fitness_history = []
    valid_ratio_history = []

    for gen in range(max_generations):
        best = population.best()
        if best:
            fitness_history.append(best.fitness)
            if best.fitness >= target_fitness:
                break

        valid_ratio_history.append(
            population.valid_count() / len(population.individuals)
            if population.individuals else 0.0
        )

        population.individuals.sort(key=lambda ind: ind.fitness, reverse=True)
        next_gen = population.individuals[:2]  # Elitism

        while len(next_gen) < population_size:
            parent1 = _tournament_select(population, rng)
            parent2 = _tournament_select(population, rng)
            offspring = _create_offspring(parent1, parent2, mutation_rate, fitness_fn, rng)
            next_gen.extend(offspring)

        population = Population(individuals=next_gen[:population_size])

    best = population.best()
    return EvolutionStats(
        generations=gen + 1,
        best_fitness=best.fitness if best else 0.0,
        best_individual=best if best else Individual(segments=seed),
        fitness_history=fitness_history,
        valid_ratio_history=valid_ratio_history,
    )
