"""
Compiler for compiling a SecDB-lite Graph to a standalone Python script.
"""

import os
import re
from typing import Dict, Any
from decimal import Decimal
from graph_engine import Graph, InputNode, FormulaNode

def compile_to_python_source(graph: Graph) -> str:
    """
    Compiles a Graph to a standalone Python script source string.
    
    Args:
        graph: The Graph instance to compile.
        
    Returns:
        A string containing the Python source code.
    """
    # 1. Sort nodes topologically
    topo_order = graph.topological_sort()
    
    # 2. Identify leaf nodes (nodes that have no dependents)
    leaf_nodes = []
    for node_id in topo_order:
        dependents = graph._dependents.get(node_id, set())
        if not dependents:
            leaf_nodes.append(node_id)
            
    lines = [
        "# Standalone Python script compiled from SecDB-lite DAG",
        "from decimal import Decimal, getcontext, ROUND_HALF_UP",
        "getcontext().rounding = ROUND_HALF_UP",
        "",
        "# Inputs"
    ]
    
    # Write inputs
    inputs_written = False
    for node_id in topo_order:
        node = graph.nodes[node_id]
        if isinstance(node, InputNode):
            val = node.value
            if isinstance(val, bool):
                repr_val = str(val)
            elif isinstance(val, (int, float, Decimal)):
                repr_val = f"Decimal('{val}')"
            elif isinstance(val, str):
                repr_val = repr(val)
            elif val is None:
                repr_val = "None"
            else:
                repr_val = repr(val)
            lines.append(f"{node_id} = {repr_val}")
            inputs_written = True
            
    if inputs_written:
        lines.append("")
        
    lines.append("# Formulas")
    formulas_written = False
    for node_id in topo_order:
        node = graph.nodes[node_id]
        if isinstance(node, FormulaNode):
            if node.formula_str:
                # Convert UPPERCASE_FUNC( to lowercase_func( for Python built-ins (e.g. MAX -> max)
                formula_py = node.formula_str
                formula_py = re.sub(r'\b([A-Z_]+)(?=\s*\()', lambda m: m.group(1).lower(), formula_py)
                lines.append(f"{node_id} = {formula_py}")
            else:
                # Fallback: if no formula_str, assign evaluated value as constant
                val = node.value
                if isinstance(val, (int, float, Decimal)):
                    repr_val = f"Decimal('{val}')"
                else:
                    repr_val = repr(val)
                lines.append(f"{node_id} = {repr_val}")
            formulas_written = True
            
    if formulas_written:
        lines.append("")
        
    lines.append("# Outputs")
    for leaf in leaf_nodes:
        lines.append(f"print({leaf})")
        
    return "\n".join(lines) + "\n"

def compile_to_python(graph: Graph, filepath: str):
    """
    Compiles the graph and writes it to a standalone Python script.
    
    Args:
        graph: The Graph instance to compile.
        filepath: The path where the compiled .py file should be saved.
    """
    source = compile_to_python_source(graph)
    dir_name = os.path.dirname(filepath)
    if dir_name:
        os.makedirs(dir_name, exist_ok=True)
    with open(filepath, "w") as f:
        f.write(source)
