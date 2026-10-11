import itertools

from django.test import SimpleTestCase

from territories.map_definition import (
    MAP_NEIGHBORS,
    MAP_TERRITORIES,
    InvalidMapDefinitionError,
    build_adjacency,
    find_capital_triples,
    get_map_definition,
    is_connected,
    validate_map_definition,
)


class ProjectMapTests(SimpleTestCase):
    def test_project_map_is_valid(self):
        definition = get_map_definition()
        self.assertEqual(len(definition['territories']), len(MAP_TERRITORIES))
        self.assertEqual(definition['neighbors'], MAP_NEIGHBORS)

    def test_project_map_size_is_within_allowed_range_and_a_multiple_of_three(self):
        count = len(MAP_TERRITORIES)
        self.assertGreaterEqual(count, 9)
        self.assertLessEqual(count, 21)
        self.assertEqual(count % 3, 0)

    def test_project_map_has_a_capital_triple(self):
        definition = get_map_definition()
        self.assertTrue(find_capital_triples(definition['adjacency']))


class ValidateMapDefinitionTests(SimpleTestCase):
    def _territories(self, count):
        return [{'name': f'Territory {i}', 'slug': f'territory-{i}'} for i in range(count)]

    def _ring(self, count):
        """A connected ring where every node has exactly 2 neighbors."""
        territories = self._territories(count)
        slugs = [entry['slug'] for entry in territories]
        neighbors = [(slugs[i], slugs[(i + 1) % count]) for i in range(count)]
        return territories, neighbors

    def test_rejects_too_few_territories(self):
        territories, neighbors = self._ring(6)
        with self.assertRaises(InvalidMapDefinitionError):
            validate_map_definition(territories, neighbors)

    def test_rejects_count_not_a_multiple_of_three(self):
        territories, neighbors = self._ring(10)
        with self.assertRaises(InvalidMapDefinitionError):
            validate_map_definition(territories, neighbors)

    def test_rejects_duplicate_names(self):
        territories, neighbors = self._ring(9)
        territories[1]['name'] = territories[0]['name']
        with self.assertRaises(InvalidMapDefinitionError):
            validate_map_definition(territories, neighbors)

    def test_rejects_duplicate_slugs(self):
        territories, neighbors = self._ring(9)
        territories[1]['slug'] = territories[0]['slug']
        with self.assertRaises(InvalidMapDefinitionError):
            validate_map_definition(territories, neighbors)

    def test_rejects_self_neighbor(self):
        territories, neighbors = self._ring(9)
        neighbors.append((territories[0]['slug'], territories[0]['slug']))
        with self.assertRaises(InvalidMapDefinitionError):
            validate_map_definition(territories, neighbors)

    def test_rejects_unknown_territory_in_neighbor_pair(self):
        territories, neighbors = self._ring(9)
        neighbors.append((territories[0]['slug'], 'does-not-exist'))
        with self.assertRaises(InvalidMapDefinitionError):
            validate_map_definition(territories, neighbors)

    def test_rejects_disconnected_graph(self):
        territories, _ = self._ring(9)
        slugs = [entry['slug'] for entry in territories]
        # Two separate triangles instead of one connected ring.
        neighbors = [
            (slugs[0], slugs[1]), (slugs[1], slugs[2]), (slugs[2], slugs[0]),
            (slugs[3], slugs[4]), (slugs[4], slugs[5]), (slugs[5], slugs[3]),
            (slugs[6], slugs[7]), (slugs[7], slugs[8]), (slugs[8], slugs[6]),
        ]
        with self.assertRaises(InvalidMapDefinitionError):
            validate_map_definition(territories, neighbors)

    def test_rejects_territory_with_fewer_than_two_neighbors(self):
        territories, neighbors = self._ring(9)
        slugs = [entry['slug'] for entry in territories]
        # Drop one of the ring edges, leaving a node with a single neighbor.
        neighbors.remove((slugs[0], slugs[1]))
        with self.assertRaises(InvalidMapDefinitionError):
            validate_map_definition(territories, neighbors)

    def test_rejects_map_without_a_mutually_non_adjacent_triple(self):
        # A complete graph: every pair of territories is adjacent, so no three
        # of them can be mutually non-adjacent.
        territories = self._territories(9)
        slugs = [entry['slug'] for entry in territories]
        neighbors = [(a, b) for a, b in itertools.combinations(slugs, 2)]
        with self.assertRaises(InvalidMapDefinitionError):
            validate_map_definition(territories, neighbors)

    def test_accepts_a_valid_ring(self):
        territories, neighbors = self._ring(9)
        adjacency = validate_map_definition(territories, neighbors)
        self.assertEqual(len(adjacency), 9)


class GraphHelperTests(SimpleTestCase):
    def test_build_adjacency_is_symmetric(self):
        territories = [{'name': 'A', 'slug': 'a'}, {'name': 'B', 'slug': 'b'}]
        adjacency = build_adjacency(territories, [('a', 'b')])
        self.assertIn('b', adjacency['a'])
        self.assertIn('a', adjacency['b'])

    def test_is_connected_detects_a_split_graph(self):
        adjacency = {'a': {'b'}, 'b': {'a'}, 'c': set()}
        self.assertFalse(is_connected(adjacency))

    def test_find_capital_triples_excludes_adjacent_pairs(self):
        # A triangle a-b-c plus an isolated-from-them node d: only triples
        # including d alongside two of a/b/c are valid, since a, b, c are
        # mutually adjacent.
        adjacency = {
            'a': {'b', 'c'},
            'b': {'a', 'c'},
            'c': {'a', 'b'},
            'd': set(),
        }
        triples = find_capital_triples(adjacency)
        self.assertEqual(triples, [])
