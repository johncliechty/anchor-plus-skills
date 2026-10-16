"""
Report Generator for financial-analyst.
Generates grounded Markdown and PDF reports from evaluated graphs.
Ensures that all quantitative claims cite specific graph node IDs.
"""

import json
from decimal import Decimal
from graph_engine import Graph

def generate_llm_prompt(graph: Graph) -> str:
    """
    Constructs the system/user prompt for the LLM, containing the read-only JSON graph state.
    """
    graph.evaluate()
    
    data = {}
    for node_id, node in graph.nodes.items():
        val = node.value
        if isinstance(val, Decimal):
            data[node_id] = str(val)
        else:
            data[node_id] = val
            
    json_export = json.dumps(data, indent=2)
    
    prompt = f"""SYSTEM INSTRUCTIONS:
You are a financial analyst generating a markdown report grounded strictly in the provided evaluated graph data.
You must only state facts present in the graph data.
For every quantitative claim, you must explicitly cite the node ID using the format: [Node: node_id].
Do not hallucinate or make qualitative claims that cannot be traced to the graph.

GRAPH DATA:
{json_export}
"""
    return prompt

def generate_report(graph: Graph) -> str:
    """
    Generates a Markdown report that is strictly grounded in the graph data and
    includes node citations for all quantitative claims.
    """
    graph.evaluate()
    
    # Check if this is a VC Comp graph
    is_vc_comp = ("pre_money_valuation" in graph.nodes or "PreMoneyValuation" in graph.nodes)
    # Check if this is a Real Estate Waterfall graph
    is_waterfall = ("lp_contribution" in graph.nodes or "gp_contribution" in graph.nodes)
    
    if is_vc_comp:
        # Retrieve values with defaults/fallbacks
        pre_val = graph.nodes.get("pre_money_valuation") or graph.nodes.get("PreMoneyValuation")
        inv_amt = graph.nodes.get("investment_amount") or graph.nodes.get("InvestmentAmount")
        post_val = graph.nodes.get("post_money_valuation") or graph.nodes.get("PostMoneyValuation")
        inv_own = graph.nodes.get("investor_ownership") or graph.nodes.get("InvestorOwnership")
        ex_own = graph.nodes.get("existing_ownership") or graph.nodes.get("ExistingOwnership")
        
        pre_val_str = f"${pre_val.value:,.2f}" if pre_val and pre_val.value is not None else "N/A"
        inv_amt_str = f"${inv_amt.value:,.2f}" if inv_amt and inv_amt.value is not None else "N/A"
        post_val_str = f"${post_val.value:,.2f}" if post_val and post_val.value is not None else "N/A"
        
        inv_own_pct = f"{float(inv_own.value) * 100:.2f}%" if inv_own and inv_own.value is not None else "N/A"
        ex_own_pct = f"{float(ex_own.value) * 100:.2f}%" if ex_own and ex_own.value is not None else "N/A"
        
        pre_citation = "pre_money_valuation" if "pre_money_valuation" in graph.nodes else "PreMoneyValuation"
        inv_citation = "investment_amount" if "investment_amount" in graph.nodes else "InvestmentAmount"
        post_citation = "post_money_valuation" if "post_money_valuation" in graph.nodes else "PostMoneyValuation"
        inv_own_citation = "investor_ownership" if "investor_ownership" in graph.nodes else "InvestorOwnership"
        ex_own_citation = "existing_ownership" if "existing_ownership" in graph.nodes else "ExistingOwnership"
        
        report = f"""# Venture Capital Round Cap Table Analysis Report

This report is grounded in the evaluated computational graph.

## Valuation and Investment Summary
- **Pre-Money Valuation:** {pre_val_str} [Node: {pre_citation}]
- **Investment Amount:** {inv_amt_str} [Node: {inv_citation}]
- **Post-Money Valuation:** {post_val_str} [Node: {post_citation}]

## Ownership Splits
- **Existing Shareholders Ownership:** {ex_own_pct} [Node: {ex_own_citation}]
- **New Investor Ownership:** {inv_own_pct} [Node: {inv_own_citation}]
"""
        return report
        
    elif is_waterfall:
        init_eq = graph.nodes.get("initial_equity")
        lp_sh = graph.nodes.get("lp_share")
        gp_sh = graph.nodes.get("gp_share")
        h1 = graph.nodes.get("hurdle_1_rate")
        h2 = graph.nodes.get("hurdle_2_rate")
        lp_contrib = graph.nodes.get("lp_contribution")
        gp_contrib = graph.nodes.get("gp_contribution")
        
        report_lines = [
            "# Real Estate Waterfall Distribution Report",
            "",
            "This report summarizes the Brueggeman waterfall distribution cash flows based on the evaluated graph.",
            "",
            "## Initial Assumptions"
        ]
        
        if init_eq and init_eq.value is not None:
            report_lines.append(f"- **Initial Equity:** ${init_eq.value:,.2f} [Node: initial_equity]")
        if lp_sh and lp_sh.value is not None:
            report_lines.append(f"- **LP Share:** {float(lp_sh.value)*100:.2f}% [Node: lp_share]")
        if gp_sh and gp_sh.value is not None:
            report_lines.append(f"- **GP Share:** {float(gp_sh.value)*100:.2f}% [Node: gp_share]")
        if h1 and h1.value is not None:
            report_lines.append(f"- **Hurdle 1 (Pref Return):** {float(h1.value)*100:.2f}% [Node: hurdle_1_rate]")
        if h2 and h2.value is not None:
            report_lines.append(f"- **Hurdle 2:** {float(h2.value)*100:.2f}% [Node: hurdle_2_rate]")
            
        report_lines.append("")
        report_lines.append("## Capital Contributions")
        if lp_contrib and lp_contrib.value is not None:
            report_lines.append(f"- **LP Contribution:** ${lp_contrib.value:,.2f} [Node: lp_contribution]")
        if gp_contrib and gp_contrib.value is not None:
            report_lines.append(f"- **GP Contribution:** ${gp_contrib.value:,.2f} [Node: gp_contribution]")
            
        # Add years
        t = 1
        while True:
            cf_node = graph.nodes.get(f"cf_{t}")
            if not cf_node:
                break
            report_lines.append("")
            report_lines.append(f"## Year {t} Distribution Summary")
            report_lines.append(f"- **Total Cash Flow:** ${cf_node.value:,.2f} [Node: cf_{t}]")
            
            lp_dist = graph.nodes.get(f"lp_total_dist_{t}")
            gp_dist = graph.nodes.get(f"gp_total_dist_{t}")
            total_dist = graph.nodes.get(f"total_dist_{t}")
            
            if lp_dist and lp_dist.value is not None:
                report_lines.append(f"- **LP Total Distribution:** ${lp_dist.value:,.2f} [Node: lp_total_dist_{t}]")
            if gp_dist and gp_dist.value is not None:
                report_lines.append(f"- **GP Total Distribution:** ${gp_dist.value:,.2f} [Node: gp_total_dist_{t}]")
            if total_dist and total_dist.value is not None:
                report_lines.append(f"- **Total Distribution:** ${total_dist.value:,.2f} [Node: total_dist_{t}]")
            t += 1
            
        return "\n".join(report_lines) + "\n"
        
    else:
        # Generic graph summary
        report_lines = [
            "# Financial Graph Evaluation Report",
            "",
            "This report lists the evaluated nodes from the dependency graph.",
            "",
            "## Node Details"
        ]
        for node_id in graph.topological_sort():
            node = graph.nodes[node_id]
            val = node.value
            val_str = str(val) if val is not None else "None"
            report_lines.append(f"- **{node_id}:** {val_str} [Node: {node_id}]")
            
        return "\n".join(report_lines) + "\n"

def generate_pdf_report(graph: Graph, filepath: str) -> None:
    """
    Generates a PDF report containing the text of the markdown report, via fpdf.

    W3 (2026-07-11): ONE code path. The old triple fallback (fpdf -> reportlab ->
    hand-rolled bytes) shipped a corrupt path — the hand-rolled xref table had only
    the free entry and startxref carried no offset, emitting a malformed file. A
    missing dependency now fails LOUDLY with the fix, never silently writes a
    broken deliverable.
    """
    markdown_content = generate_report(graph)
    try:
        from fpdf import FPDF
        from fpdf.enums import XPos, YPos
    except ImportError as e:
        raise RuntimeError(
            "generate_pdf_report requires fpdf2 (`pip install fpdf2`). "
            "No fallback is attempted — the old hand-rolled fallback produced corrupt PDFs."
        ) from e
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("helvetica", size=12)
    for line in markdown_content.split('\n'):
        pdf.cell(200, 10, text=line, new_x=XPos.LMARGIN, new_y=YPos.NEXT, align="L")
    pdf.output(filepath)
