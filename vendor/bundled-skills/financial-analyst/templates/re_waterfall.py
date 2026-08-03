"""
Real Estate Waterfall Template.
Implements the William B. Brueggeman joint venture distribution waterfall.
"""

from decimal import Decimal
from typing import List
from graph_engine import Graph, InputNode, FormulaNode

def create_waterfall_graph(
    initial_equity: float = 1000000.00,
    lp_share: float = 0.90,
    gp_share: float = 0.10,
    hurdle_1_rate: float = 0.08,
    hurdle_2_rate: float = 0.12,
    tier1_lp_split: float = 0.90,
    tier1_gp_split: float = 0.10,
    tier2_lp_split: float = 0.70,
    tier2_gp_split: float = 0.30,
    tier3_lp_split: float = 0.50,
    tier3_gp_split: float = 0.50,
    cash_flows: List[float] = None
) -> Graph:
    """
    Constructs a SecDB-lite graph for a multi-tier real estate joint venture waterfall.
    
    Tiers:
    - Tier 1: Preferred return (hurdle 1, e.g. 8%) split according to tier1 splits (typically pari passu).
    - Tier 2: Hurdle 2 (e.g. 12%) split according to tier2 splits (e.g. 70/30, containing GP promote).
    - Tier 3: Above hurdle 2 split according to tier3 splits (e.g. 50/50, containing larger GP promote).
    """
    if cash_flows is None:
        cash_flows = [120000.00, 150000.00, 180000.00, 250000.00, 1200000.00]
        
    num_years = len(cash_flows)
    g = Graph()
    
    # 1. Add assumptions/inputs
    g.add_node(InputNode("initial_equity", initial_equity))
    g.add_node(InputNode("lp_share", lp_share))
    g.add_node(InputNode("gp_share", gp_share))
    g.add_node(InputNode("hurdle_1_rate", hurdle_1_rate))
    g.add_node(InputNode("hurdle_2_rate", hurdle_2_rate))
    g.add_node(InputNode("tier1_lp_split", tier1_lp_split))
    g.add_node(InputNode("tier1_gp_split", tier1_gp_split))
    g.add_node(InputNode("tier2_lp_split", tier2_lp_split))
    g.add_node(InputNode("tier2_gp_split", tier2_gp_split))
    g.add_node(InputNode("tier3_lp_split", tier3_lp_split))
    g.add_node(InputNode("tier3_gp_split", tier3_gp_split))
    
    # Capital contributions
    g.add_node(FormulaNode(
        "lp_contribution",
        lambda eq, sh: round(eq * sh, 2),
        depends_on=["initial_equity", "lp_share"],
        formula_str="ROUND(initial_equity * lp_share, 2)"
    ))
    g.add_node(FormulaNode(
        "gp_contribution",
        lambda eq, sh: round(eq * sh, 2),
        depends_on=["initial_equity", "gp_share"],
        formula_str="ROUND(initial_equity * gp_share, 2)"
    ))
    
    # Loop over each year to build the tiered calculations
    for t in range(1, num_years + 1):
        # Year t Cash Flow Input
        g.add_node(InputNode(f"cf_{t}", cash_flows[t - 1]))
        
        # --- Tier 1 (Hurdle 1 / 8% Pref Return) ---
        if t == 1:
            g.add_node(FormulaNode(
                f"lp_beg_bal_8_{t}",
                lambda contrib: contrib,
                depends_on=["lp_contribution"],
                formula_str="lp_contribution"
            ))
        else:
            g.add_node(FormulaNode(
                f"lp_beg_bal_8_{t}",
                lambda prev_bal: prev_bal,
                depends_on=[f"lp_end_bal_8_{t-1}"],
                formula_str=f"lp_end_bal_8_{t-1}"
            ))
            
        g.add_node(FormulaNode(
            f"lp_pref_8_{t}",
            lambda bal, rate: round(bal * rate, 2),
            depends_on=[f"lp_beg_bal_8_{t}", "hurdle_1_rate"],
            formula_str=f"ROUND(lp_beg_bal_8_{t} * hurdle_1_rate, 2)"
        ))
        
        g.add_node(FormulaNode(
            f"lp_target_8_{t}",
            lambda bal, pref: round(bal + pref, 2),
            depends_on=[f"lp_beg_bal_8_{t}", f"lp_pref_8_{t}"],
            formula_str=f"ROUND(lp_beg_bal_8_{t} + lp_pref_8_{t}, 2)"
        ))
        
        # Tier 1 distributions
        g.add_node(FormulaNode(
            f"total_dist_1_{t}",
            lambda cf, target, split: min(cf, round(target / split, 2)),
            depends_on=[f"cf_{t}", f"lp_target_8_{t}", "tier1_lp_split"],
            formula_str=f"MIN(cf_{t}, ROUND(lp_target_8_{t} / tier1_lp_split, 2))"
        ))
        
        g.add_node(FormulaNode(
            f"lp_dist_1_{t}",
            lambda target, total, split: min(target, round(total * split, 2)),
            depends_on=[f"lp_target_8_{t}", f"total_dist_1_{t}", "tier1_lp_split"],
            formula_str=f"MIN(lp_target_8_{t}, ROUND(total_dist_1_{t} * tier1_lp_split, 2))"
        ))
        
        g.add_node(FormulaNode(
            f"gp_dist_1_{t}",
            lambda total, lp: round(total - lp, 2),
            depends_on=[f"total_dist_1_{t}", f"lp_dist_1_{t}"],
            formula_str=f"ROUND(total_dist_1_{t} - lp_dist_1_{t}, 2)"
        ))
        
        g.add_node(FormulaNode(
            f"rem_cf_1_{t}",
            lambda cf, total: round(cf - total, 2),
            depends_on=[f"cf_{t}", f"total_dist_1_{t}"],
            formula_str=f"ROUND(cf_{t} - total_dist_1_{t}, 2)"
        ))
        
        # --- Tier 2 (Hurdle 2 / 12% IRR) ---
        if t == 1:
            g.add_node(FormulaNode(
                f"lp_beg_bal_12_{t}",
                lambda contrib: contrib,
                depends_on=["lp_contribution"],
                formula_str="lp_contribution"
            ))
        else:
            g.add_node(FormulaNode(
                f"lp_beg_bal_12_{t}",
                lambda prev_bal: prev_bal,
                depends_on=[f"lp_end_bal_12_{t-1}"],
                formula_str=f"lp_end_bal_12_{t-1}"
            ))
            
        g.add_node(FormulaNode(
            f"lp_pref_12_{t}",
            lambda bal, rate: round(bal * rate, 2),
            depends_on=[f"lp_beg_bal_12_{t}", "hurdle_2_rate"],
            formula_str=f"ROUND(lp_beg_bal_12_{t} * hurdle_2_rate, 2)"
        ))
        
        g.add_node(FormulaNode(
            f"lp_target_12_{t}",
            lambda bal, pref: round(bal + pref, 2),
            depends_on=[f"lp_beg_bal_12_{t}", f"lp_pref_12_{t}"],
            formula_str=f"ROUND(lp_beg_bal_12_{t} + lp_pref_12_{t}, 2)"
        ))
        
        # Tier 2 distributions
        g.add_node(FormulaNode(
            f"lp_target_12_rem_{t}",
            lambda target, lp_dist1: max(Decimal("0"), round(target - lp_dist1, 2)),
            depends_on=[f"lp_target_12_{t}", f"lp_dist_1_{t}"],
            formula_str=f"MAX(0, ROUND(lp_target_12_{t} - lp_dist_1_{t}, 2))"
        ))
        
        g.add_node(FormulaNode(
            f"total_dist_2_{t}",
            lambda rem_cf, lp_rem, split: min(rem_cf, round(lp_rem / split, 2)),
            depends_on=[f"rem_cf_1_{t}", f"lp_target_12_rem_{t}", "tier2_lp_split"],
            formula_str=f"MIN(rem_cf_1_{t}, ROUND(lp_target_12_rem_{t} / tier2_lp_split, 2))"
        ))
        
        g.add_node(FormulaNode(
            f"lp_dist_2_{t}",
            lambda lp_rem, total, split: min(lp_rem, round(total * split, 2)),
            depends_on=[f"lp_target_12_rem_{t}", f"total_dist_2_{t}", "tier2_lp_split"],
            formula_str=f"MIN(lp_target_12_rem_{t}, ROUND(total_dist_2_{t} * tier2_lp_split, 2))"
        ))
        
        g.add_node(FormulaNode(
            f"gp_dist_2_{t}",
            lambda total, lp: round(total - lp, 2),
            depends_on=[f"total_dist_2_{t}", f"lp_dist_2_{t}"],
            formula_str=f"ROUND(total_dist_2_{t} - lp_dist_2_{t}, 2)"
        ))
        
        g.add_node(FormulaNode(
            f"rem_cf_2_{t}",
            lambda rem_cf, total: round(rem_cf - total, 2),
            depends_on=[f"rem_cf_1_{t}", f"total_dist_2_{t}"],
            formula_str=f"ROUND(rem_cf_1_{t} - total_dist_2_{t}, 2)"
        ))
        
        # --- Tier 3 (Above 12% IRR) ---
        g.add_node(FormulaNode(
            f"total_dist_3_{t}",
            lambda rem_cf: rem_cf,
            depends_on=[f"rem_cf_2_{t}"],
            formula_str=f"rem_cf_2_{t}"
        ))
        
        g.add_node(FormulaNode(
            f"lp_dist_3_{t}",
            lambda total, split: round(total * split, 2),
            depends_on=[f"total_dist_3_{t}", "tier3_lp_split"],
            formula_str=f"ROUND(total_dist_3_{t} * tier3_lp_split, 2)"
        ))
        
        g.add_node(FormulaNode(
            f"gp_dist_3_{t}",
            lambda total, lp: round(total - lp, 2),
            depends_on=[f"total_dist_3_{t}", f"lp_dist_3_{t}"],
            formula_str=f"ROUND(total_dist_3_{t} - lp_dist_3_{t}, 2)"
        ))
        
        # --- Totals for Year t ---
        g.add_node(FormulaNode(
            f"lp_total_dist_{t}",
            lambda lp1, lp2, lp3: round(lp1 + lp2 + lp3, 2),
            depends_on=[f"lp_dist_1_{t}", f"lp_dist_2_{t}", f"lp_dist_3_{t}"],
            formula_str=f"ROUND(lp_dist_1_{t} + lp_dist_2_{t} + lp_dist_3_{t}, 2)"
        ))
        
        g.add_node(FormulaNode(
            f"gp_total_dist_{t}",
            lambda gp1, gp2, gp3: round(gp1 + gp2 + gp3, 2),
            depends_on=[f"gp_dist_1_{t}", f"gp_dist_2_{t}", f"gp_dist_3_{t}"],
            formula_str=f"ROUND(gp_dist_1_{t} + gp_dist_2_{t} + gp_dist_3_{t}, 2)"
        ))
        
        g.add_node(FormulaNode(
            f"total_dist_{t}",
            lambda t1, t2, t3: round(t1 + t2 + t3, 2),
            depends_on=[f"total_dist_1_{t}", f"total_dist_2_{t}", f"total_dist_3_{t}"],
            formula_str=f"ROUND(total_dist_1_{t} + total_dist_2_{t} + total_dist_3_{t}, 2)"
        ))
        
        # --- Ending Balances ---
        g.add_node(FormulaNode(
            f"lp_end_bal_8_{t}",
            lambda target, lp_dist1: round(target - lp_dist1, 2),
            depends_on=[f"lp_target_8_{t}", f"lp_dist_1_{t}"],
            formula_str=f"ROUND(lp_target_8_{t} - lp_dist_1_{t}, 2)"
        ))
        
        g.add_node(FormulaNode(
            f"lp_end_bal_12_{t}",
            lambda target, lp_dist1, lp_dist2: round(target - lp_dist1 - lp_dist2, 2),
            depends_on=[f"lp_target_12_{t}", f"lp_dist_1_{t}", f"lp_dist_2_{t}"],
            formula_str=f"ROUND(lp_target_12_{t} - lp_dist_1_{t} - lp_dist_2_{t}, 2)"
        ))
        
    return g
