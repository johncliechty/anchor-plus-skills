"""
Agent-facing Python interface optimized for inter-agent sharing.
Allows other agents to query valuation results programmatically, load templates,
set inputs, evaluate graphs, and generate reports.
"""

from typing import Dict, Any, List
from graph_engine import Graph
from templates.re_waterfall import create_waterfall_graph
from templates.vc_comp import create_vc_comp_graph
from report_generator import generate_report, generate_pdf_report, generate_llm_prompt
from compiler_excel import compile_to_excel
from compiler_python import compile_to_python

class FinancialAnalystAgent:
    """
    Programmatic interface for inter-agent coordination and evaluation of deal flows.
    """
    def __init__(self):
        self.graph: Graph = None
        self.template_name: str = None

    def load_template(self, template_name: str, **kwargs) -> Graph:
        """
        Loads one of the pre-defined financial templates.
        
        Args:
            template_name: 'vc_comp' or 're_waterfall'
            **kwargs: Initial input values for the template
            
        Returns:
            The loaded Graph instance.
            
        Raises:
            ValueError: If the template is unknown.
        """
        self.template_name = template_name
        if template_name == "vc_comp":
            self.graph = create_vc_comp_graph(**kwargs)
        elif template_name == "re_waterfall":
            self.graph = create_waterfall_graph(**kwargs)
        else:
            raise ValueError(f"Unknown template: {template_name}")
        return self.graph

    def set_input(self, node_id: str, value: Any) -> None:
        """
        Updates an input or assumption in the active graph.
        """
        if self.graph is None:
            raise ValueError("No template loaded. Use load_template() first.")
        self.graph.set_input(node_id, value)

    def get_value(self, node_id: str) -> Any:
        """
        Evaluates and returns the computed value of a specific node.
        """
        if self.graph is None:
            raise ValueError("No template loaded. Use load_template() first.")
        return self.graph.evaluate_node(node_id)

    def evaluate(self) -> Dict[str, Any]:
        """
        Evaluates the entire dependency graph and returns all node values.
        """
        if self.graph is None:
            raise ValueError("No template loaded. Use load_template() first.")
        return self.graph.evaluate()

    def generate_report(self, filepath: str = None) -> str:
        """
        Generates a grounded markdown report for the loaded graph.
        Optionally writes it to a file.
        """
        if self.graph is None:
            raise ValueError("No template loaded. Use load_template() first.")
        report = generate_report(self.graph)
        if filepath:
            with open(filepath, "w", encoding="utf-8") as f:
                f.write(report)
        return report

    def generate_pdf_report(self, filepath: str) -> None:
        """
        Generates a PDF report for the loaded graph.
        """
        if self.graph is None:
            raise ValueError("No template loaded. Use load_template() first.")
        generate_pdf_report(self.graph, filepath)

    def generate_prompt(self) -> str:
        """
        Generates the LLM system prompt including the JSON graph representation.
        """
        if self.graph is None:
            raise ValueError("No template loaded. Use load_template() first.")
        return generate_llm_prompt(self.graph)

    def compile_excel(self, filepath: str, cell_mapping: Dict[str, str] = None) -> Dict[str, str]:
        """
        Compiles the active graph to an Excel spreadsheet with working formulas.
        """
        if self.graph is None:
            raise ValueError("No template loaded. Use load_template() first.")
        return compile_to_excel(self.graph, filepath, cell_mapping)

    def compile_python(self, filepath: str) -> None:
        """
        Compiles the active graph to a standalone executable Python script.
        """
        if self.graph is None:
            raise ValueError("No template loaded. Use load_template() first.")
        compile_to_python(self.graph, filepath)

    def tie_out(self) -> Dict[str, Any]:
        """
        The penny-exact tie-out, MACHINE-CHECKED (W3, 2026-07-11). SKILL.md has
        always mandated reporting "tie-out: N nodes compared, max delta 0.00" but
        no code produced it — the signature guarantee was hand-rolled per run.

        Compiles the standalone Python model, executes it in a subprocess, and
        compares EVERY leaf node's printed value against the live graph's exact
        Decimal values.

        Returns:
            {'ok': bool, 'nodes_compared': int, 'max_delta': Decimal,
             'mismatches': [(node_id, graph_value, compiled_value)],
             'line': the mandated report line}
        """
        if self.graph is None:
            raise ValueError("No template loaded. Use load_template() first.")
        import os
        import subprocess
        import sys
        import tempfile
        from decimal import Decimal

        self.graph.evaluate()
        with tempfile.TemporaryDirectory() as td:
            py_path = os.path.join(td, "tieout_model.py")
            compile_to_python(self.graph, py_path)
            # No console window on Windows (host rule: background spawns never pop shells).
            flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if sys.platform == "win32" else 0
            res = subprocess.run([sys.executable, py_path], capture_output=True,
                                 text=True, check=True, creationflags=flags)
        outputs = [Decimal(line.strip()) for line in res.stdout.strip().split("\n") if line.strip()]

        topo = self.graph.topological_sort()
        leaves = [nid for nid in topo if not self.graph._dependents.get(nid, set())]
        if len(outputs) != len(leaves):
            raise ValueError(
                f"tie-out FAILED structurally: compiled model printed {len(outputs)} value(s) "
                f"but the graph has {len(leaves)} leaf node(s) — the compiled model diverges"
            )
        mismatches = []
        max_delta = Decimal(0)
        for leaf_id, compiled_val in zip(leaves, outputs):
            graph_val = self.graph.nodes[leaf_id].value
            delta = abs(Decimal(graph_val) - compiled_val)
            if delta > max_delta:
                max_delta = delta
            if delta != 0:
                mismatches.append((leaf_id, graph_val, compiled_val))
        ok = max_delta == 0
        line = f"tie-out: {len(leaves)} nodes compared, max delta {max_delta}"
        return {"ok": ok, "nodes_compared": len(leaves), "max_delta": max_delta,
                "mismatches": mismatches, "line": line}

def create_agent() -> FinancialAnalystAgent:
    """
    Factory function to instantiate a new FinancialAnalystAgent.
    """
    return FinancialAnalystAgent()
