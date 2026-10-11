"""The project's fixed territory map: one definition, shared by every game.

Transferred from the map of Bulgaria used by Triviador Bulgaria: its 18
territories (within the 9-21, multiple-of-3 range required by M04) with their
in-game names (`name_bg`), and neighbor pairs read off the in-game borders.
Every territory has at least 2 neighbors, the graph is connected, and several
triples of mutually non-neighboring territories exist (needed for the M05
capital assignment).
"""
import itertools

MAP_TERRITORIES = [
    # North
    {'name': 'Skalite', 'name_bg': 'Скалите', 'slug': 'skalite'},
    {'name': 'Dunavia', 'name_bg': 'Дунавия', 'slug': 'dunavia'},
    {'name': 'Zhitno Pole', 'name_bg': 'Житно поле', 'slug': 'zhitno-pole'},
    {'name': 'Leventa', 'name_bg': 'Левента', 'slug': 'leventa'},
    {'name': 'Tsarevo', 'name_bg': 'Царево', 'slug': 'tsarevo'},
    {'name': 'Balkania', 'name_bg': 'Балкания', 'slug': 'balkania'},
    # North-east and Black Sea coast
    {'name': 'Pelikania', 'name_bg': 'Пеликания', 'slug': 'pelikania'},
    {'name': 'Madara', 'name_bg': 'Мадара', 'slug': 'madara'},
    {'name': 'Kaliakra', 'name_bg': 'Калиакра', 'slug': 'kaliakra'},
    {'name': 'Slanchevo', 'name_bg': 'Слънчево', 'slug': 'slanchevo'},
    {'name': 'Kukeri', 'name_bg': 'Кукери', 'slug': 'kukeri'},
    # South and west
    {'name': 'Sredets', 'name_bg': 'Средец', 'slug': 'sredets'},
    {'name': 'Ezera', 'name_bg': 'Езера', 'slug': 'ezera'},
    {'name': 'Pirini', 'name_bg': 'Пирини', 'slug': 'pirini'},
    {'name': 'Rozova Dolina', 'name_bg': 'Розова долина', 'slug': 'rozova-dolina'},
    {'name': 'Karandila', 'name_bg': 'Карандила', 'slug': 'karandila'},
    {'name': 'Chuden Kray', 'name_bg': 'Чуден край', 'slug': 'chuden-kray'},
    {'name': 'Zlaten Grozd', 'name_bg': 'Златен грозд', 'slug': 'zlaten-grozd'},
]

MAP_NEIGHBORS = [
    ('skalite', 'dunavia'),
    ('skalite', 'sredets'),
    ('dunavia', 'zhitno-pole'),
    ('dunavia', 'sredets'),
    ('dunavia', 'balkania'),
    ('zhitno-pole', 'leventa'),
    ('zhitno-pole', 'balkania'),
    ('zhitno-pole', 'tsarevo'),
    ('leventa', 'tsarevo'),
    ('leventa', 'pelikania'),
    ('leventa', 'madara'),
    ('pelikania', 'madara'),
    ('pelikania', 'kaliakra'),
    ('madara', 'kaliakra'),
    ('madara', 'slanchevo'),
    ('madara', 'tsarevo'),
    ('kaliakra', 'slanchevo'),
    ('slanchevo', 'tsarevo'),
    ('slanchevo', 'kukeri'),
    ('tsarevo', 'balkania'),
    ('tsarevo', 'karandila'),
    ('balkania', 'sredets'),
    ('balkania', 'ezera'),
    ('balkania', 'rozova-dolina'),
    ('balkania', 'karandila'),
    ('sredets', 'ezera'),
    ('ezera', 'pirini'),
    ('ezera', 'rozova-dolina'),
    ('ezera', 'chuden-kray'),
    ('pirini', 'chuden-kray'),
    ('rozova-dolina', 'karandila'),
    ('rozova-dolina', 'chuden-kray'),
    ('rozova-dolina', 'zlaten-grozd'),
    ('karandila', 'kukeri'),
    ('karandila', 'zlaten-grozd'),
    ('kukeri', 'zlaten-grozd'),
    ('chuden-kray', 'zlaten-grozd'),
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
