"""The project's fixed territory map: one definition, shared by every game.

Chosen for this project: 12 territories (within the 9-21, multiple-of-3 range
required by M04), arranged so every territory has at least 2 neighbors, the
graph is connected, and several triples of mutually non-neighboring
territories exist (needed for the M05 capital assignment).
"""
import itertools

MAP_TERRITORIES = [
    {'name': 'Northgate', 'slug': 'northgate'},
    {'name': 'Rivermouth', 'slug': 'rivermouth'},
    {'name': 'Stonevale', 'slug': 'stonevale'},
    {'name': 'Ashford', 'slug': 'ashford'},
    {'name': 'Oakhaven', 'slug': 'oakhaven'},
    {'name': 'Mistwood', 'slug': 'mistwood'},
    {'name': 'Sunspire', 'slug': 'sunspire'},
    {'name': 'Ironhold', 'slug': 'ironhold'},
    {'name': 'Greymoor', 'slug': 'greymoor'},
    {'name': 'Thornfield', 'slug': 'thornfield'},
    {'name': 'Brightwater', 'slug': 'brightwater'},
    {'name': 'Dunmore', 'slug': 'dunmore'},
]

MAP_NEIGHBORS = [
    ('northgate', 'rivermouth'),
    ('rivermouth', 'stonevale'),
    ('stonevale', 'ashford'),
    ('ashford', 'oakhaven'),
    ('oakhaven', 'mistwood'),
    ('mistwood', 'sunspire'),
    ('sunspire', 'ironhold'),
    ('ironhold', 'greymoor'),
    ('greymoor', 'thornfield'),
    ('thornfield', 'brightwater'),
    ('brightwater', 'dunmore'),
    ('dunmore', 'northgate'),
    ('northgate', 'stonevale'),
    ('ashford', 'mistwood'),
    ('sunspire', 'greymoor'),
    ('thornfield', 'dunmore'),
]

MIN_TERRITORY_COUNT = 9
MAX_TERRITORY_COUNT = 21
TERRITORY_COUNT_STEP = 3
MIN_NEIGHBORS_PER_TERRITORY = 2
CAPITAL_TRIPLE_SIZE = 3


class InvalidMapDefinitionError(Exception):
    """The project's map definition breaks one of the M04 graph rules."""


def build_adjacency(territories, neighbor_pairs):
    slugs = {entry['slug'] for entry in territories}
    adjacency = {slug: set() for slug in slugs}
    for slug_a, slug_b in neighbor_pairs:
        if slug_a not in slugs or slug_b not in slugs:
            raise InvalidMapDefinitionError(f'Unknown territory in neighbor pair ({slug_a}, {slug_b}).')
        if slug_a == slug_b:
            raise InvalidMapDefinitionError(f'A territory cannot be its own neighbor: {slug_a}.')
        adjacency[slug_a].add(slug_b)
        adjacency[slug_b].add(slug_a)
    return adjacency


def is_connected(adjacency):
    if not adjacency:
        return False
    start = next(iter(adjacency))
    visited = {start}
    stack = [start]
    while stack:
        current = stack.pop()
        for neighbor in adjacency[current]:
            if neighbor not in visited:
                visited.add(neighbor)
                stack.append(neighbor)
    return visited == set(adjacency)


def find_capital_triples(adjacency):
    """All slug triples that are mutually non-neighboring, per the adjacency map."""
    return [
        combo
        for combo in itertools.combinations(adjacency, CAPITAL_TRIPLE_SIZE)
        if all(b not in adjacency[a] for a, b in itertools.combinations(combo, 2))
    ]


def validate_map_definition(territories, neighbor_pairs):
    """Check the M04 graph rules and return the resulting adjacency map."""
    count = len(territories)
    if count < MIN_TERRITORY_COUNT or count > MAX_TERRITORY_COUNT or count % TERRITORY_COUNT_STEP != 0:
        raise InvalidMapDefinitionError(
            f'A map must have between {MIN_TERRITORY_COUNT} and {MAX_TERRITORY_COUNT} territories, '
            f'in multiples of {TERRITORY_COUNT_STEP}.'
        )

    names = [entry['name'] for entry in territories]
    slugs = [entry['slug'] for entry in territories]
    if len(set(names)) != len(names):
        raise InvalidMapDefinitionError('Territory names must be unique.')
    if len(set(slugs)) != len(slugs):
        raise InvalidMapDefinitionError('Territory slugs must be unique.')

    adjacency = build_adjacency(territories, neighbor_pairs)

    if not is_connected(adjacency):
        raise InvalidMapDefinitionError('The map must be connected: every territory must be reachable from any other.')

    for slug, neighbors in adjacency.items():
        if len(neighbors) < MIN_NEIGHBORS_PER_TERRITORY:
            raise InvalidMapDefinitionError(
                f'Territory "{slug}" has fewer than {MIN_NEIGHBORS_PER_TERRITORY} neighbors.'
            )

    if not find_capital_triples(adjacency):
        raise InvalidMapDefinitionError(
            'The map must contain at least one set of three mutually non-neighboring territories.'
        )

    return adjacency


_validated_adjacency = None


def get_map_definition():
    """The project's map, validated once and cached: territories, neighbor pairs, adjacency."""
    global _validated_adjacency
    if _validated_adjacency is None:
        _validated_adjacency = validate_map_definition(MAP_TERRITORIES, MAP_NEIGHBORS)
    return {
        'territories': MAP_TERRITORIES,
        'neighbors': MAP_NEIGHBORS,
        'adjacency': _validated_adjacency,
    }
