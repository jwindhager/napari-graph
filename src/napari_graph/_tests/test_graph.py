import pytest
import numpy as np
import pandas as pd

from numpy.typing import ArrayLike
from typing import Tuple, Callable, List, Type

from napari_graph import UndirectedGraph, DirectedGraph
from napari_graph._base_graph import BaseGraph, _EDGE_EMPTY_PTR
from napari_graph.undirected_graph import _LL_UN_EDGE_POS, _UN_EDGE_SIZE


def make_graph_dataframe(
    size: int, sparsity: float
) -> Tuple[pd.DataFrame, np.ndarray]:
    # TODO:
    #  - move to pytest fixture

    adj_matrix = np.random.uniform(size=(size, size)) < sparsity
    np.fill_diagonal(adj_matrix, 0)

    edges = np.stack(adj_matrix.nonzero()).T
    nodes_df = pd.DataFrame(np.random.randn(size, 3), columns=["z", "y", "x"])

    return nodes_df, edges


@pytest.mark.parametrize("n_prealloc_edges", [0, 2, 5])
def test_undirected_init_from_dataframe(n_prealloc_edges: int) -> None:
    nodes_df = pd.DataFrame(
        [
            [0, 2.5],
            [4, 2.5],
            [1, 0],
            [2, 3.5],
            [3, 0],
        ],
        columns=["y", "x"],
    )

    edges = [[0, 1], [1, 2], [2, 3], [3, 4], [0, 4]]

    graph = UndirectedGraph(
        n_nodes=nodes_df.shape[0],
        ndim=nodes_df.shape[1],
        n_edges=n_prealloc_edges,
    )

    graph.init_nodes_from_dataframe(nodes_df, ["y", "x"])
    graph.add_edges(edges)

    for node_idx, node_edges in zip(
        nodes_df.index, graph.edges(nodes_df.index)
    ):
        # checking if two edges per node and connecting only two nodes
        assert node_edges.shape == (2, 2)

        # checking if the given index is the source
        assert np.all(node_edges[:, 0] == node_idx)

        # checking if the edges are corrected
        for edge in node_edges:
            assert sorted(edge) in edges


@pytest.mark.parametrize("n_prealloc_edges", [0, 2, 5])
def test_directed_init_from_dataframe(n_prealloc_edges: int) -> None:
    nodes_df = pd.DataFrame(
        [
            [0, 2.5],
            [4, 2.5],
            [1, 0],
            [2, 3.5],
            [3, 0],
        ],
        columns=["y", "x"],
    )

    edges = np.asarray([[0, 1], [1, 2], [2, 3], [3, 4], [4, 0]])

    graph = DirectedGraph(
        n_nodes=nodes_df.shape[0],
        ndim=nodes_df.shape[1],
        n_edges=n_prealloc_edges,
    )

    graph.init_nodes_from_dataframe(nodes_df, ["y", "x"])
    graph.add_edges(edges)

    source_edges = np.asarray(graph.source_edges(nodes_df.index))
    target_edges = np.asarray(graph.target_edges(np.roll(nodes_df.index, -1)))
    assert np.all(source_edges == edges[:, np.newaxis, :])
    assert np.all(target_edges == edges[:, np.newaxis, :])


@pytest.mark.parametrize("n_prealloc_nodes", [0, 3, 6, 12])
def test_node_addition(n_prealloc_nodes: int) -> None:
    size = 6
    ndim = 3

    indices = np.random.choice(range(100), size=size, replace=False)
    coords = np.random.randn(size, ndim)

    graph = DirectedGraph(n_prealloc_nodes, ndim, 0)
    for i in range(size):
        graph.add_node(indices[i], coords[i])
        assert len(graph) == i + 1

    np.testing.assert_allclose(graph._coords[: len(graph)], coords)
    np.testing.assert_array_equal(
        graph._buffer2world[: len(graph)], indices
    )
    np.testing.assert_array_equal(
        graph._map_world2buffer(indices), range(size)
    )


class TestGraph:
    _GRAPH_CLASS: Type[BaseGraph] = ...
    __test__ = False  # ignored for testing

    def setup_method(self, method: Callable) -> None:
        self.nodes_df = pd.DataFrame(
            [
                [0, 2.5],
                [4, 2.5],
                [
                    1,
                    0,
                ],
                [2, 3.5],
                [3, 0],
            ],
            columns=["y", "x"],
        )

        self.edges = np.asarray([[0, 1], [1, 2], [2, 3], [3, 4], [4, 0]])

        self.graph = self._GRAPH_CLASS(
            n_nodes=self.nodes_df.shape[0],
            ndim=self.nodes_df.shape[1],
            n_edges=len(self.edges),
        )
        self.graph.init_nodes_from_dataframe(self.nodes_df, ["y", "x"])
        self.graph.add_edges(self.edges)

    @staticmethod
    def contains(edge: ArrayLike, edges: List[ArrayLike]) -> bool:
        return any(
            np.allclose(e, edge) if len(e) > 0 else False for e in edges
        )

    def teardown_method(self, method: Callable) -> None:
        self.edges, self.nodes_df, self.graph = None, None, None

    def test_edge_buffers(self) -> None:
        # testing non-trivial case when a node already removed
        node_id = 3
        self.graph.remove_node(node_id)

        valid_edges = np.logical_not(np.any(self.edges == node_id, axis=1))

        expected_edges = self.edges[valid_edges, :]
        (expected_indices,) = np.nonzero(valid_edges)
        expected_indices *= (
            self.graph._EDGE_SIZE * self.graph._EDGE_DUPLICATION
        )

        indices, edges = self.graph.edges_buffers()

        assert np.allclose(expected_indices, indices)
        assert np.allclose(expected_edges, edges)


class TestDirectedGraph(TestGraph):
    _GRAPH_CLASS = DirectedGraph
    __test__ = True

    def test_edge_removal(self) -> None:
        self.graph.remove_edges([0, 1])
        assert self.graph.n_edges == 4
        assert self.graph.n_empty_edges == 1
        assert not self.contains((0, 1), self.graph.source_edges())
        assert not self.contains((1, 0), self.graph.target_edges())

        self.graph.remove_edges([[1, 2], [2, 3]])
        assert self.graph.n_edges == 2
        assert self.graph.n_empty_edges == 3
        assert not self.contains((1, 2), self.graph.source_edges())
        assert not self.contains((2, 3), self.graph.source_edges())

        assert self.graph.n_allocated_edges == 5

    def test_node_removal(self) -> None:
        nodes = [3, 4, 1]
        original_size = len(self.graph)

        for i in range(len(nodes)):
            node = nodes[i]
            self.graph.remove_node(node)

            for edge in self.graph.source_edges():
                assert node not in edge

            for edge in self.graph.target_edges():
                assert node not in edge

            assert node not in self.graph.nodes()
            assert len(self.graph) == original_size - i - 1

    def test_edge_coordinates(self) -> None:
        coords = self.nodes_df.values[self.edges]

        source_edge_coords = np.concatenate(
            self.graph.source_edges(mode='coords'), axis=0
        )
        assert np.allclose(coords, source_edge_coords)

        target_edges_coords = np.concatenate(
            self.graph.target_edges(mode='coords'), axis=0
        )
        rolled_coords = np.roll(coords, shift=1, axis=0)
        assert np.allclose(rolled_coords, target_edges_coords)


class TestUndirectedGraph(TestGraph):
    _GRAPH_CLASS = UndirectedGraph
    __test__ = True

    def test_edge_removal(self) -> None:
        self.graph.remove_edges([0, 1])
        assert self.graph.n_edges == 4
        assert self.graph.n_empty_edges == 1
        assert not self.contains((0, 1), self.graph.edges())
        assert not self.contains((1, 0), self.graph.edges())

        self.graph.remove_edges([[1, 2], [2, 3]])
        assert self.graph.n_edges == 2
        assert self.graph.n_empty_edges == 3
        assert not self.contains((1, 2), self.graph.edges())
        assert not self.contains((2, 3), self.graph.edges())

        assert self.graph.n_allocated_edges == 5

        self.assert_empty_linked_list_pairs_are_neighbors()

    def test_node_removal(self) -> None:
        nodes = [3, 4, 1]
        original_size = len(self.graph)

        for i in range(len(nodes)):
            node = nodes[i]
            self.graph.remove_node(node)

            for edge in self.graph.edges():
                assert node not in edge

            assert node not in self.graph.nodes()
            assert len(self.graph) == original_size - i - 1

        self.assert_empty_linked_list_pairs_are_neighbors()

    def test_edge_coordinates(self) -> None:
        edge_coords = self.graph.edges(mode='coords')

        for node, coords in zip(self.graph.nodes(), edge_coords):
            for i, edge in enumerate(self.graph.edges(node)):
                assert np.allclose(
                    self.nodes_df.loc[edge, ["y", "x"]].values, coords[i]
                )

    def assert_empty_linked_list_pairs_are_neighbors(self) -> None:
        # testing if empty edges linked list pairs are neighbors
        empty_idx = self.graph._empty_edge_idx
        while empty_idx != _EDGE_EMPTY_PTR:
            next_empty_idx = self.graph._edges_buffer[
                empty_idx * _UN_EDGE_SIZE + _LL_UN_EDGE_POS
            ]
            assert empty_idx + 1 == next_empty_idx
            # skipping one
            empty_idx = self.graph._edges_buffer[
                next_empty_idx * _UN_EDGE_SIZE + _LL_UN_EDGE_POS
            ]


def test_benchmark_construction_speed() -> None:
    # FIXME: remove this, maybe create an airspeed velocity CI
    from timeit import default_timer
    import networkx as nx

    nodes_df, edges = make_graph_dataframe(50000, 0.001)

    print('# edges', len(edges))

    start = default_timer()
    graph = UndirectedGraph(
        n_nodes=nodes_df.shape[0], ndim=nodes_df.shape[1], n_edges=len(edges)
    )
    graph.init_nodes_from_dataframe(nodes_df, ["z", "y", "x"])

    alloc_time = default_timer()
    print('our alloc time', alloc_time - start)

    graph.add_edges(edges)
    end = default_timer()

    print('our add edge time', end - alloc_time)
    print('our total time', end - start)

    start = default_timer()

    graph = nx.Graph()
    graph.add_nodes_from(nodes_df.to_dict('index').items())
    graph.add_edges_from(edges)

    print('networkx init time', default_timer() - start)
