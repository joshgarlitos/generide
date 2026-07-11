#!/usr/bin/env python3
"""CLI tool for evolving coaster tracks using genetic algorithm.

Usage:
    python evolve_coaster.py --output evolved.td6
    python evolve_coaster.py --generations 200 --population 100 --output best.td6
"""

import argparse
import sys
from pathlib import Path

from rct2 import td6
from rct2.evolution import evolve
from rct2.fitness import ProxyFitness
from rct2.generate import (
    BEGIN_STATION,
    END_STATION,
    calculate_entrance_positions,
    calculate_space_required,
    create_simple_circuit,
)
from rct2.geometry import Position, is_closed_circuit, validate_track
from rct2.td6 import Entrance, Ride, TrackElement


# Slope segments that can have chain lift
CHAIN_LIFT_SEGMENTS = {
    0x04,  # 25_deg_up
    0x05,  # 60_deg_up
    0x06,  # flat_to_25_deg_up
    0x07,  # 25_deg_up_to_60_deg_up
    0x08,  # 60_deg_up_to_25_deg_up
    0x09,  # 25_deg_up_to_flat
}


def _find_first_hill_indices(segments: list[int]) -> set[int]:
    """Find indices of the first uphill sequence after the station."""
    in_hill = False
    hill_indices = set()

    for i, seg in enumerate(segments):
        if seg in CHAIN_LIFT_SEGMENTS:
            in_hill = True
            hill_indices.add(i)
        elif in_hill:
            # We've exited the first hill
            break

    return hill_indices


def create_ride_from_segments(
    segments: list[int],
    template_path: Path,
) -> Ride:
    """Create a Ride object from evolved segments."""
    template = td6.load(template_path)

    # Find the first hill to add chain lift
    first_hill = _find_first_hill_indices(segments)

    # Create track elements with chain lift on first hill
    elements = [
        TrackElement(
            segment_type=seg,
            chain_lift=(seg == BEGIN_STATION or i in first_hill),
            inverted=False,
            colour_scheme=0,
            cable_lift=False,
        )
        for i, seg in enumerate(segments)
    ]

    # Calculate positions
    entrance, exit_ = calculate_entrance_positions(segments)
    x_space, y_space = calculate_space_required(segments)

    return Ride(
        ride_type=template.ride_type,
        operating_mode=template.operating_mode,
        color_scheme=template.color_scheme,
        control_flags=template.control_flags,
        num_trains=1,
        cars_per_train=2,
        min_wait_time=template.min_wait_time,
        max_wait_time=template.max_wait_time,
        max_speed=template.max_speed,
        average_speed=template.average_speed,
        excitement=0,
        intensity=0,
        nausea=0,
        dat_data=template.dat_data,
        x_space_required=x_space,
        y_space_required=y_space,
        circuits_and_lift_speed=template.circuits_and_lift_speed,
        header=template.header,
        elements=elements,
        entrances=[entrance, exit_],
        scenery=b"\xff",
    )


def main():
    parser = argparse.ArgumentParser(
        description="Evolve coaster tracks using genetic algorithm"
    )
    parser.add_argument(
        "--output", "-o",
        type=Path,
        default=Path("evolved.td6"),
        help="Output TD6 file path (default: evolved.td6)",
    )
    parser.add_argument(
        "--generations", "-g",
        type=int,
        default=100,
        help="Number of generations to evolve (default: 100)",
    )
    parser.add_argument(
        "--population", "-p",
        type=int,
        default=50,
        help="Population size (default: 50)",
    )
    parser.add_argument(
        "--mutation-rate", "-m",
        type=float,
        default=0.1,
        help="Mutation rate (default: 0.1)",
    )
    parser.add_argument(
        "--seed",
        type=str,
        default=None,
        help="Seed track: 'simple' for simple circuit, or path to TD6 file",
    )
    parser.add_argument(
        "--template",
        type=Path,
        default=None,
        help="Template TD6 file for ride header data",
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Print progress during evolution",
    )

    args = parser.parse_args()

    # Determine template path
    template_path = args.template
    if template_path is None:
        template_path = (
            Path(__file__).parent / "data" / "sample_rides" / "manic_miner_test.td6"
        )

    if not template_path.exists():
        print(f"Error: Template file not found: {template_path}", file=sys.stderr)
        sys.exit(1)

    # Determine seed track
    if args.seed is None or args.seed == "simple":
        seed = create_simple_circuit()
        print("Using simple circuit as seed")
    else:
        seed_path = Path(args.seed)
        if not seed_path.exists():
            print(f"Error: Seed file not found: {seed_path}", file=sys.stderr)
            sys.exit(1)
        seed_ride = td6.load(seed_path)
        seed = [e.segment_type for e in seed_ride.elements]
        print(f"Using {seed_path} as seed ({len(seed)} segments)")

    # Create fitness function
    fitness_fn = ProxyFitness()

    # Progress callback
    def progress(gen, pop):
        if args.verbose:
            best = pop.best()
            valid = pop.valid_count()
            total = len(pop.individuals)
            if best:
                print(
                    f"Gen {gen:4d}: best={best.fitness:7.1f}, "
                    f"avg={pop.average_fitness():7.1f}, "
                    f"valid={valid}/{total}"
                )

    print(f"Evolving for {args.generations} generations with population {args.population}")
    print(f"Mutation rate: {args.mutation_rate}")
    print()

    # Run evolution
    stats = evolve(
        seed=seed,
        fitness_fn=fitness_fn,
        population_size=args.population,
        generations=args.generations,
        mutation_rate=args.mutation_rate,
        progress_callback=progress if args.verbose else None,
    )

    print()
    print("Evolution complete!")
    print(f"  Final best fitness: {stats.best_fitness:.1f}")
    print(f"  Generations run: {stats.generations}")

    best = stats.best_individual
    print(f"  Best track length: {len(best.segments)} segments")
    print(f"  Best track valid: {best.is_valid()}")

    # Validate the best track
    result = validate_track(Position(), best.segments)
    if result.valid:
        print("  Validation: PASSED")
    else:
        print("  Validation issues:")
        for issue in result.issues:
            print(f"    - {issue.code}: {issue.message}")

    # Save if valid
    if best.is_valid():
        ride = create_ride_from_segments(best.segments, template_path)
        td6.save(ride, args.output)
        print(f"\nSaved evolved track to: {args.output}")
    else:
        print("\nWarning: Best track is not a valid closed circuit.")
        print("Attempting to save anyway (may not load in OpenRCT2)...")
        try:
            ride = create_ride_from_segments(best.segments, template_path)
            td6.save(ride, args.output)
            print(f"Saved to: {args.output}")
        except Exception as e:
            print(f"Failed to save: {e}", file=sys.stderr)
            sys.exit(1)


if __name__ == "__main__":
    main()
