"""
Compiler for compiling a SecDB-lite Graph to an Excel (.xlsx) spreadsheet.
"""

import os
import re
import openpyxl
from typing import Dict, Any
from decimal import Decimal
from graph_engine import Graph, InputNode, FormulaNode

def get_column_letter(col_idx: int) -> str:
    """
    Convert a 1-based column index to Excel column letters (e.g. 1 -> 'A', 28 -> 'AB').
    """
    letters = []
    while col_idx > 0:
        col_idx, remainder = divmod(col_idx - 1, 26)
        letters.append(chr(65 + remainder))
    return "".join(reversed(letters))

def compile_to_excel(graph: Graph, filepath: str, cell_mapping: Dict[str, str] = None) -> Dict[str, str]:
    """
    Compiles a Graph to an Excel file (.xlsx) with formulas matching the graph.
    
    Args:
        graph: The Graph instance to compile.
        filepath: The path where the compiled .xlsx file should be saved.
        cell_mapping: An optional dictionary mapping node_id to cell coordinates (e.g. 'A1', 'B1').
                      If not provided or incomplete, coordinates will be auto-assigned sequentially.
                      
    Returns:
        A dictionary containing the final cell mapping (node_id -> cell coordinate).
    """
    # 1. Sort nodes topologically to establish evaluation/layout order
    topo_order = graph.topological_sort()
    
    # 2. Establish cell mapping.
    # W3 (2026-07-11): the auto layout is now LABELED AND VERTICAL — node label in
    # column A, value/formula in column B, one node per row under a header. The old
    # auto-assignment put every node in row 1, one unlabeled column each: a 5-year
    # waterfall compiled to ~130 anonymous cells in a strip — technically a
    # "synchronized Excel model", practically unusable for a counterparty. An
    # explicit cell_mapping still wins verbatim (no labels are written into a
    # caller-designed layout).
    auto_layout = cell_mapping is None
    if cell_mapping is None:
        cell_mapping = {}
    else:
        cell_mapping = dict(cell_mapping) # Copy to avoid mutating original

    auto_labels = {}  # cell for the label of each auto-assigned node
    if auto_layout:
        row = 2  # row 1 is the header
        for node_id in topo_order:
            cell_mapping[node_id] = f"B{row}"
            auto_labels[node_id] = f"A{row}"
            row += 1
    else:
        # Partial mappings: fill gaps in row 1 columns (legacy behavior, unlabeled)
        col_idx = 1
        for node_id in topo_order:
            if node_id not in cell_mapping:
                while True:
                    candidate = f"{get_column_letter(col_idx)}1"
                    if candidate not in cell_mapping.values():
                        cell_mapping[node_id] = candidate
                        col_idx += 1
                        break
                    col_idx += 1

    # Ensure target directory exists
    dir_name = os.path.dirname(filepath)
    if dir_name:
        os.makedirs(dir_name, exist_ok=True)

    # Create the workbook
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Sheet1"

    # Labeled auto layout: header + one label per node row, readable widths.
    if auto_layout:
        ws["A1"] = "Node"
        ws["B1"] = "Value / Formula"
        ws["A1"].font = openpyxl.styles.Font(bold=True)
        ws["B1"].font = openpyxl.styles.Font(bold=True)
        ws.column_dimensions["A"].width = 34
        ws.column_dimensions["B"].width = 22
        for node_id, label_cell in auto_labels.items():
            ws[label_cell] = node_id

    # Evaluate the graph first to make sure we have cached values in the nodes
    graph.evaluate()
    
    # Compile formula logic: match identifiers while skipping string literals
    pattern = re.compile(r'"[^"]*"|\'[^\']*\'|[a-zA-Z_][a-zA-Z0-9_]*')
    def replace_match(match):
        token = match.group(0)
        if token.startswith('"') or token.startswith("'"):
            return token
        return cell_mapping.get(token, token)

    # Write each node to the sheet
    for node_id in topo_order:
        node = graph.nodes[node_id]
        cell_coord = cell_mapping[node_id]
        
        if isinstance(node, InputNode):
            val = node.value
            if isinstance(val, Decimal):
                ws[cell_coord] = float(val)
            else:
                ws[cell_coord] = val
        elif isinstance(node, FormulaNode):
            if node.formula_str:
                # Replace node IDs in formula with cell references
                excel_formula = pattern.sub(replace_match, node.formula_str)
                # Ensure it starts with '='
                if not excel_formula.startswith('='):
                    excel_formula = f"={excel_formula}"
                ws[cell_coord] = excel_formula
            else:
                # Fallback: if no formula_str, write evaluated value as constant
                val = node.value
                if isinstance(val, Decimal):
                    ws[cell_coord] = float(val)
                else:
                    ws[cell_coord] = val
                    
    wb.save(filepath)
    return cell_mapping
