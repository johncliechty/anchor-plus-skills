"""
Venture Capital Round Capitalization Analysis Template.
Implements pre-money, investment, post-money, and ownership calculations.
"""

from decimal import Decimal
from graph_engine import Graph, InputNode, FormulaNode

def create_vc_comp_graph(
    pre_money_valuation: float = 10000000.00,
    investment_amount: float = 5000000.00,
) -> Graph:
    """
    Constructs a SecDB-lite graph for a VC round capitalization analysis.
    """
    g = Graph()

    # ONE node family only (A2, 2026-07-11). The old parallel CamelCase alias
    # family silently diverged: set_input("investment_amount") updated only the
    # lowercase nodes while compile_excel/compile_python emitted BOTH families —
    # one workbook, two contradictory cap tables, in a penny-exact tool. Aliases
    # of stateful nodes are forbidden in every template.
    g.add_node(InputNode("pre_money_valuation", pre_money_valuation))
    g.add_node(InputNode("investment_amount", investment_amount))

    g.add_node(FormulaNode(
        "post_money_valuation",
        lambda pre, inv: round(pre + inv, 2),
        depends_on=["pre_money_valuation", "investment_amount"],
        formula_str="ROUND(pre_money_valuation + investment_amount, 2)"
    ))
    
    g.add_node(FormulaNode(
        "investor_ownership",
        lambda inv, post: round(inv / post, 4),
        depends_on=["investment_amount", "post_money_valuation"],
        formula_str="ROUND(investment_amount / post_money_valuation, 4)"
    ))
    
    g.add_node(FormulaNode(
        "existing_ownership",
        lambda pre, post: round(pre / post, 4),
        depends_on=["pre_money_valuation", "post_money_valuation"],
        formula_str="ROUND(pre_money_valuation / post_money_valuation, 4)"
    ))

    return g
