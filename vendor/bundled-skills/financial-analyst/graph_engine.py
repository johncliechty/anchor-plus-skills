"""
SecDB-lite DAG Core Engine.
Represents financial assumptions, inputs, and formulas in a directed acyclic graph (DAG) using exact decimal math.
"""

from decimal import Decimal, getcontext, ROUND_HALF_UP
getcontext().rounding = ROUND_HALF_UP
from typing import List, Callable, Union, Dict, Set, Any


class Node:
    """
    Base class representing a node in the dependency graph.
    """
    def __init__(self, node_id: str):
        self.node_id: str = node_id
        self.dependencies: List[Union['Node', str]] = []
        self._value: Any = None
        self._evaluated: bool = False

    @property
    def value(self) -> Any:
        """
        Returns the evaluated value of the node.
        """
        return self._value

    @property
    def dependency_ids(self) -> List[str]:
        """
        Returns a list of dependency node IDs.
        """
        return [dep.node_id if isinstance(dep, Node) else dep for dep in self.dependencies]

    def evaluate(self, memo: Dict[str, Any] = None, visiting: Set[str] = None, graph: Any = None) -> Any:
        """
        Evaluates the node. Must be implemented by subclasses.
        """
        raise NotImplementedError("Subclasses must implement evaluate()")


class InputNode(Node):
    """
    Represents an input or assumption in the dependency graph.
    """
    def __init__(self, node_id: str, value: Any = None):
        super().__init__(node_id)
        self.dependencies = []
        self._value = self._coerce_value(value)
        self._evaluated = True

    def _coerce_value(self, val: Any) -> Any:
        if val is None:
            return None
        if isinstance(val, bool):
            return val
        if isinstance(val, (int, float, str, Decimal)):
            try:
                if isinstance(val, float):
                    return Decimal(str(val))
                return Decimal(val)
            except Exception:
                return val
        return val

    def set_value(self, value: Any):
        """
        Sets a new value for the input node.
        """
        self._value = self._coerce_value(value)
        self._evaluated = True

    def evaluate(self, memo: Dict[str, Any] = None, visiting: Set[str] = None, graph: Any = None) -> Any:
        if memo is None:
            memo = {}
        memo[self.node_id] = self._value
        return self._value


class FormulaNode(Node):
    """
    Represents a derived node computed from dependencies via a formula.
    """
    def __init__(self, node_id: str, compute_fn: Callable, depends_on: List[Union[Node, str]], formula_str: str = None):
        super().__init__(node_id)
        self.compute_fn: Callable = compute_fn
        self.dependencies = depends_on
        self.formula_str: Union[str, None] = formula_str

    def reset_cache(self):
        """
        Resets the cached evaluation results.
        """
        self._value = None
        self._evaluated = False

    def evaluate(self, memo: Dict[str, Any] = None, visiting: Set[str] = None, graph: Any = None) -> Any:
        if memo is None:
            memo = {}
        if visiting is None:
            visiting = set()

        if self.node_id in memo:
            return memo[self.node_id]
        if self.node_id in visiting:
            raise ValueError(f"Cycle detected involving node {self.node_id}")

        if self._evaluated:
            memo[self.node_id] = self._value
            return self._value

        visiting.add(self.node_id)

        dep_values = []
        for dep in self.dependencies:
            if isinstance(dep, Node):
                val = dep.evaluate(memo, visiting, graph)
            elif isinstance(dep, str):
                if graph is None:
                    raise ValueError(f"Cannot resolve string dependency '{dep}' without a graph context.")
                if dep not in graph.nodes:
                    raise KeyError(f"Dependency '{dep}' not found in graph.")
                val = graph.nodes[dep].evaluate(memo, visiting, graph)
            else:
                raise TypeError(f"Invalid dependency type: {type(dep)}")
            dep_values.append(val)

        # Call the formula function
        val = self.compute_fn(*dep_values)

        # Coerce output to Decimal if applicable
        if isinstance(val, bool):
            pass
        elif isinstance(val, (int, float, str, Decimal)):
            try:
                if isinstance(val, float):
                    val = Decimal(str(val))
                else:
                    val = Decimal(val)
            except Exception:
                pass

        self._value = val
        self._evaluated = True
        visiting.remove(self.node_id)
        memo[self.node_id] = self._value
        return self._value


class Graph:
    """
    Represents the dependency graph container.
    """
    def __init__(self):
        self.nodes: Dict[str, Node] = {}
        self._dependents: Dict[str, Set[str]] = {}

    def add_node(self, node: Node) -> Node:
        """
        Adds a node to the graph.
        """
        self.nodes[node.node_id] = node
        if node.node_id not in self._dependents:
            self._dependents[node.node_id] = set()
        
        for dep in node.dependencies:
            dep_id = dep.node_id if isinstance(dep, Node) else dep
            if dep_id not in self._dependents:
                self._dependents[dep_id] = set()
            self._dependents[dep_id].add(node.node_id)
        return node

    def set_input(self, node_id: str, value: Any):
        """
        Updates the value of an InputNode and invalidates downstream caches.
        """
        if node_id not in self.nodes:
            raise KeyError(f"Node {node_id} not found in graph")
        node = self.nodes[node_id]
        if not isinstance(node, InputNode):
            raise TypeError(f"Node {node_id} is not an InputNode")
        node.set_value(value)
        self._invalidate_cache(node_id)

    def _invalidate_cache(self, node_id: str):
        visited = set()
        queue = [node_id]
        while queue:
            curr = queue.pop(0)
            if curr in visited:
                continue
            visited.add(curr)

            curr_node = self.nodes.get(curr)
            if curr_node and curr != node_id:
                if isinstance(curr_node, FormulaNode):
                    curr_node.reset_cache()

            if curr in self._dependents:
                for dep in self._dependents[curr]:
                    queue.append(dep)

    def evaluate_node(self, node_id: str) -> Any:
        """
        Evaluates a specific node in the graph.
        """
        if node_id not in self.nodes:
            raise KeyError(f"Node {node_id} not found in graph")
        memo = {}
        visiting = set()
        return self.nodes[node_id].evaluate(memo, visiting, self)

    def evaluate(self) -> Dict[str, Any]:
        """
        Evaluates all nodes in the graph and returns their values.
        """
        memo = {}
        visiting = set()
        results = {}
        for node_id, node in self.nodes.items():
            results[node_id] = node.evaluate(memo, visiting, self)
        return results

    def topological_sort(self) -> List[str]:
        """
        Returns node IDs in topological order.
        Raises ValueError if a cycle is detected.
        """
        visited = {}  # 0: unvisited, 1: visiting, 2: visited
        order = []

        def dfs(node_id):
            status = visited.get(node_id, 0)
            if status == 1:
                raise ValueError(f"Cycle detected involving node {node_id}")
            if status == 2:
                return

            visited[node_id] = 1
            node = self.nodes.get(node_id)
            if node:
                for dep in node.dependencies:
                    dep_id = dep.node_id if isinstance(dep, Node) else dep
                    dfs(dep_id)
            visited[node_id] = 2
            order.append(node_id)

        for node_id in self.nodes:
            if node_id not in visited:
                dfs(node_id)
        return order
