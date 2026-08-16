"""
Cancer Working-Age Productivity (Human-Capital) Template.

Built for the RBS2418 economic model, L7 leg: the market-productivity value of
working life lost to cancer death, and the value of deferring or preventing it.

STRUCTURE
---------
1.  A per-single-year-of-age lattice (ages 0..90) carrying, for each age:
      we_age_a   = earnings index (relative to average compensation) x employment rate
      d_age_a    = discount/growth factor from age 0 to age a, k = (1+g)/(1+r)
      cpv_age_a  = cumulative discounted effective compensation-years to age a
2.  From the lattice, PV of ALL remaining working life at any age a:
      pv_years_age_a = (cpv_age_END - cpv_age_a) / d_age_a
    expressed in "effective compensation-years", discounted to age a.
3.  Weighted across the observed age-at-cancer-death distribution -> per-death and
    aggregate human-capital loss.
4.  Friction-cost alternative, and the ratio between the two methods.
5.  The three model tiers (BASE / MID / UPSIDE).
6.  The VLY (value-of-life-year) comparator, computed SEPARATELY and never summed
    with the human-capital figures - they are mutually exclusive frames.

Every number in the deliverable must be a node value read off this graph.
"""

from decimal import Decimal
from graph_engine import Graph, InputNode, FormulaNode

# Single-year-of-age lattice bounds
AGE_MIN = 0
AGE_END = 91          # terminal boundary; cpv_age_91 is the "all working life" cap

# Labour-profile bands: (label, first_age, last_age)
LABOUR_BANDS = [
    ("1524", 15, 24),
    ("2534", 25, 34),
    ("3544", 35, 44),
    ("4554", 45, 54),
    ("5564", 55, 64),
    ("6569", 65, 69),
]

# Age-at-death bands used to weight the distribution: (label, midpoint_age)
DEATH_BANDS = [
    ("u20", 12),
    ("2034", 27),
    ("3544", 40),
    ("4554", 50),
    ("5564", 60),
    ("6574", 69),
    ("7584", 79),
    ("85p", 88),
]


def _band_for_age(age: int):
    for label, lo, hi in LABOUR_BANDS:
        if lo <= age <= hi:
            return label
    return None


def create_cancer_human_capital_graph(**overrides) -> Graph:
    """
    Constructs the working-age productivity graph.

    All defaults below are PLACEHOLDERS overwritten by set_input() with sourced
    values before the model is run. A default is never a finding.
    """
    g = Graph()

    def I(node_id, value):
        g.add_node(InputNode(node_id, overrides.get(node_id, value)))

    def F(node_id, fn, deps, fstr):
        g.add_node(FormulaNode(node_id, fn, depends_on=deps, formula_str=fstr))

    # ------------------------------------------------------------------
    # 1. Macro / methodological inputs
    # ------------------------------------------------------------------
    I("discount_rate", 0.03)
    I("productivity_growth", 0.01)
    I("retirement_age", 65)
    I("avg_annual_compensation", 0)     # money per employed worker-year, currency+year stated in report
    I("gdp_per_capita", 0)

    F("k_factor",
      lambda gr, r: (Decimal(1) + gr) / (Decimal(1) + r),
      ["productivity_growth", "discount_rate"],
      "(1 + productivity_growth) / (1 + discount_rate)")

    # ------------------------------------------------------------------
    # 2. Labour profile by band (the ONLY stateful source for we_age_*)
    # ------------------------------------------------------------------
    for label, _lo, _hi in LABOUR_BANDS:
        I(f"earn_index_{label}", 0)     # earnings relative to avg_annual_compensation
        I(f"emp_rate_{label}", 0)       # employment-to-population ratio in band

    # ------------------------------------------------------------------
    # 3. Per-age lattice
    # ------------------------------------------------------------------
    for age in range(AGE_MIN, AGE_END):
        label = _band_for_age(age)
        if label is None:
            I(f"we_age_{age}", 0)       # outside working ages by construction
        else:
            F(f"we_age_{age}",
              lambda e, m: e * m,
              [f"earn_index_{label}", f"emp_rate_{label}"],
              f"earn_index_{label} * emp_rate_{label}")

    I("d_age_0", 1)
    for age in range(AGE_MIN + 1, AGE_END + 1):
        F(f"d_age_{age}",
          lambda prev, k: prev * k,
          [f"d_age_{age-1}", "k_factor"],
          f"d_age_{age-1} * k_factor")

    # SURVIVAL LATTICE. The human-capital method values EXPECTED earnings, so
    # each future working year must be weighted by the probability of living to
    # earn it. Defaults are 1.0 on purpose: with the defaults the model returns
    # the NO-MORTALITY-WEIGHTING UPPER BOUND, and any correction has to be
    # entered as an explicit, sourced (or explicitly assumed) survival schedule
    # rather than smuggled in as a template default.
    for age in range(AGE_MIN, AGE_END):
        I(f"psurv_age_{age}", 1)      # p(x) = 1 - q(x), single year of age

    I("s_age_0", 1)
    for age in range(AGE_MIN + 1, AGE_END + 1):
        F(f"s_age_{age}",
          lambda prev, p: prev * p,
          [f"s_age_{age-1}", f"psurv_age_{age-1}"],
          f"s_age_{age-1} * psurv_age_{age-1}")

    I("cpv_age_0", 0)
    for age in range(AGE_MIN + 1, AGE_END + 1):
        F(f"cpv_age_{age}",
          lambda prev, we, d, s: prev + we * d * s,
          [f"cpv_age_{age-1}", f"we_age_{age-1}", f"d_age_{age-1}", f"s_age_{age-1}"],
          f"cpv_age_{age-1} + we_age_{age-1} * d_age_{age-1} * s_age_{age-1}")

    # ------------------------------------------------------------------
    # 4. PV of remaining working life at each death-band midpoint
    #    (units: effective compensation-years, discounted to the age of death)
    # ------------------------------------------------------------------
    for label, mid in DEATH_BANDS:
        F(f"pv_years_{label}",
          lambda tot, at, d, s: (tot - at) / (d * s),
          [f"cpv_age_{AGE_END}", f"cpv_age_{mid}", f"d_age_{mid}", f"s_age_{mid}"],
          f"(cpv_age_{AGE_END} - cpv_age_{mid}) / (d_age_{mid} * s_age_{mid})")

        F(f"pv_money_{label}",
          lambda py, comp: py * comp,
          [f"pv_years_{label}", "avg_annual_compensation"],
          f"pv_years_{label} * avg_annual_compensation")

        # Years of Potential Working Life Lost: raw years to retirement, no
        # employment or discount weighting (this is the published metric).
        F(f"ypwll_{label}",
          lambda R, m=mid: max(R - Decimal(m), Decimal(0)),
          ["retirement_age"],
          f"MAX(retirement_age - {mid}, 0)")

    # ------------------------------------------------------------------
    # 5. Age-at-death distribution and the weighted per-death figures
    # ------------------------------------------------------------------
    for label, _mid in DEATH_BANDS:
        I(f"share_deaths_{label}", 0)

    share_terms = " + ".join(f"share_deaths_{l}" for l, _ in DEATH_BANDS)
    F("share_deaths_total",
      lambda *s: sum(s),
      [f"share_deaths_{l}" for l, _ in DEATH_BANDS],
      share_terms)

    pv_terms = " + ".join(f"share_deaths_{l} * pv_money_{l}" for l, _ in DEATH_BANDS)
    F("hc_pv_per_cancer_death",
      lambda *v: sum(v[i] * v[i + len(DEATH_BANDS)] for i in range(len(DEATH_BANDS))),
      [f"share_deaths_{l}" for l, _ in DEATH_BANDS] + [f"pv_money_{l}" for l, _ in DEATH_BANDS],
      pv_terms)

    ypwll_terms = " + ".join(f"share_deaths_{l} * ypwll_{l}" for l, _ in DEATH_BANDS)
    F("ypwll_per_cancer_death",
      lambda *v: sum(v[i] * v[i + len(DEATH_BANDS)] for i in range(len(DEATH_BANDS))),
      [f"share_deaths_{l}" for l, _ in DEATH_BANDS] + [f"ypwll_{l}" for l, _ in DEATH_BANDS],
      ypwll_terms)

    # Working-age share of deaths (below the retirement age used)
    F("share_deaths_under_65",
      lambda a, b, c, d, e: a + b + c + d + e,
      ["share_deaths_u20", "share_deaths_2034", "share_deaths_3544",
       "share_deaths_4554", "share_deaths_5564"],
      "share_deaths_u20 + share_deaths_2034 + share_deaths_3544 + "
      "share_deaths_4554 + share_deaths_5564")

    # Working-age-only cuts. The published YPWLL metric and the "working-age
    # death" headline are defined over deaths BELOW the cutoff only, so the
    # per-death averages over the whole cohort must not be quoted as if they
    # described a working-age decedent.
    UNDER65 = ["u20", "2034", "3544", "4554", "5564"]

    F("ypwll_per_working_age_death",
      lambda tot, sh: tot / sh,
      ["ypwll_per_cancer_death", "share_deaths_under_65"],
      "ypwll_per_cancer_death / share_deaths_under_65")

    n_u65 = len(UNDER65)
    F("hc_pv_under65_weighted",
      lambda *v, _n=n_u65: sum(v[i] * v[i + _n] for i in range(_n)),
      [f"share_deaths_{l}" for l in UNDER65] + [f"pv_money_{l}" for l in UNDER65],
      " + ".join(f"share_deaths_{l} * pv_money_{l}" for l in UNDER65))

    F("hc_pv_per_working_age_death",
      lambda tot, sh: tot / sh,
      ["hc_pv_under65_weighted", "share_deaths_under_65"],
      "hc_pv_under65_weighted / share_deaths_under_65")

    F("share_of_hc_loss_from_under65",
      lambda part, whole: part / whole,
      ["hc_pv_under65_weighted", "hc_pv_per_cancer_death"],
      "hc_pv_under65_weighted / hc_pv_per_cancer_death")

    # ------------------------------------------------------------------
    # 6. Aggregates
    # ------------------------------------------------------------------
    I("cancer_deaths_annual", 0)
    I("cancer_cases_annual", 0)

    F("working_age_deaths_annual",
      lambda n, sh: n * sh,
      ["cancer_deaths_annual", "share_deaths_under_65"],
      "cancer_deaths_annual * share_deaths_under_65")

    F("hc_loss_annual_total",
      lambda n, pv: n * pv,
      ["cancer_deaths_annual", "hc_pv_per_cancer_death"],
      "cancer_deaths_annual * hc_pv_per_cancer_death")

    F("ypwll_annual_total",
      lambda n, y: n * y,
      ["cancer_deaths_annual", "ypwll_per_cancer_death"],
      "cancer_deaths_annual * ypwll_per_cancer_death")

    # ------------------------------------------------------------------
    # 7. Friction-cost alternative
    # ------------------------------------------------------------------
    I("friction_period_months", 3)
    I("recruitment_training_uplift", 0.25)

    emp_terms = " + ".join(
        f"share_deaths_{l} * emp_rate_{_band_for_age(m) or '1524'}"
        for l, m in DEATH_BANDS if _band_for_age(m)
    )
    emp_deps = [f"share_deaths_{l}" for l, m in DEATH_BANDS if _band_for_age(m)] + \
               [f"emp_rate_{_band_for_age(m)}" for l, m in DEATH_BANDS if _band_for_age(m)]
    n_emp = len(emp_deps) // 2
    F("employed_share_at_cancer_death",
      lambda *v: sum(v[i] * v[i + n_emp] for i in range(n_emp)),
      emp_deps,
      emp_terms)

    F("friction_cost_per_cancer_death",
      lambda es, comp, mo, up: es * comp * (mo / Decimal(12)) * (Decimal(1) + up),
      ["employed_share_at_cancer_death", "avg_annual_compensation",
       "friction_period_months", "recruitment_training_uplift"],
      "employed_share_at_cancer_death * avg_annual_compensation * "
      "(friction_period_months / 12) * (1 + recruitment_training_uplift)")

    F("friction_loss_annual_total",
      lambda n, fc: n * fc,
      ["cancer_deaths_annual", "friction_cost_per_cancer_death"],
      "cancer_deaths_annual * friction_cost_per_cancer_death")

    F("friction_to_human_capital_ratio",
      lambda fc, hc: fc / hc,
      ["friction_cost_per_cancer_death", "hc_pv_per_cancer_death"],
      "friction_cost_per_cancer_death / hc_pv_per_cancer_death")

    # ------------------------------------------------------------------
    # 8. SURVIVAL-EXTENSION WINDOWS.
    #    A gain of G extra years of life at age a produces market output equal to
    #    the lattice window [a, a+G), discounted to a. Retirement truncation is
    #    handled exactly by the lattice, not by an averaging assumption.
    #    Each window is then weighted across the observed age-at-death distribution,
    #    so no single band stands in for the whole cohort.
    # ------------------------------------------------------------------
    for horizon in (1, 5, 10):
        for label, mid in DEATH_BANDS:
            end = min(mid + horizon, AGE_END)
            F(f"pvw{horizon}_{label}",
              lambda ce, cs, d, s: (ce - cs) / (d * s),
              [f"cpv_age_{end}", f"cpv_age_{mid}", f"d_age_{mid}", f"s_age_{mid}"],
              f"(cpv_age_{end} - cpv_age_{mid}) / (d_age_{mid} * s_age_{mid})")

        terms = " + ".join(f"share_deaths_{l} * pvw{horizon}_{l}" for l, _ in DEATH_BANDS)
        nb = len(DEATH_BANDS)
        F(f"pvw{horizon}_per_patient_years",
          lambda *v, _n=nb: sum(v[i] * v[i + _n] for i in range(_n)),
          [f"share_deaths_{l}" for l, _ in DEATH_BANDS] +
          [f"pvw{horizon}_{l}" for l, _ in DEATH_BANDS],
          terms)

    # ------------------------------------------------------------------
    # 9. TIER 1 - BASE. ~50% of patients gain ~1 year, at end of life.
    #    Market production in that year is earned only by the working-age subset
    #    who are actually able to work while on late-line therapy.
    # ------------------------------------------------------------------
    I("base_patients_annual", 0)
    I("terminal_productive_fraction", 0)   # fraction of normal output while on late-line therapy

    F("base_value_per_patient",
      lambda py, comp, tp: py * comp * tp,
      ["pvw1_per_patient_years", "avg_annual_compensation", "terminal_productive_fraction"],
      "pvw1_per_patient_years * avg_annual_compensation * terminal_productive_fraction")

    F("base_tier_value_annual",
      lambda n, v: n * v,
      ["base_patients_annual", "base_value_per_patient"],
      "base_patients_annual * base_value_per_patient")

    # ------------------------------------------------------------------
    # 10. TIER 2 - MID. Frontline. Multiplier parameterised, NOT invented:
    #     L5 parameter F-1 (incremental benefit vs contemporaneous SOC).
    # ------------------------------------------------------------------
    I("frontline_multiplier", 1)
    I("mid_productive_fraction", 0)   # earlier-line patients work more than late-line patients

    F("mid_gain_years",
      lambda m: Decimal(1) * m,
      ["frontline_multiplier"],
      "1 * frontline_multiplier")

    # Multiplier applied to the 1-year window (benefit scales, age mix does not)
    F("mid_value_per_patient",
      lambda py, comp, mp, m: py * comp * mp * m,
      ["pvw1_per_patient_years", "avg_annual_compensation",
       "mid_productive_fraction", "frontline_multiplier"],
      "pvw1_per_patient_years * avg_annual_compensation * mid_productive_fraction * "
      "frontline_multiplier")

    F("mid_tier_value_annual",
      lambda n, v: n * v,
      ["base_patients_annual", "mid_value_per_patient"],
      "base_patients_annual * mid_value_per_patient")

    # Scenario rungs the principal named explicitly (+5 / +10 years frontline)
    F("mid_rung5_value_per_patient",
      lambda py, comp, mp: py * comp * mp,
      ["pvw5_per_patient_years", "avg_annual_compensation", "mid_productive_fraction"],
      "pvw5_per_patient_years * avg_annual_compensation * mid_productive_fraction")

    F("mid_rung5_value_annual",
      lambda n, v: n * v,
      ["base_patients_annual", "mid_rung5_value_per_patient"],
      "base_patients_annual * mid_rung5_value_per_patient")

    F("mid_rung10_value_per_patient",
      lambda py, comp, mp: py * comp * mp,
      ["pvw10_per_patient_years", "avg_annual_compensation", "mid_productive_fraction"],
      "pvw10_per_patient_years * avg_annual_compensation * mid_productive_fraction")

    F("mid_rung10_value_annual",
      lambda n, v: n * v,
      ["base_patients_annual", "mid_rung10_value_per_patient"],
      "base_patients_annual * mid_rung10_value_per_patient")

    # ------------------------------------------------------------------
    # 11. TIER 3 - UPSIDE. Prevention: the cancer never occurs, so the whole
    #     remaining working life is retained.
    # ------------------------------------------------------------------
    I("upside_cases_prevented_annual", 0)
    I("case_fatality_rate", 0)

    F("upside_deaths_averted_annual",
      lambda c, cf: c * cf,
      ["upside_cases_prevented_annual", "case_fatality_rate"],
      "upside_cases_prevented_annual * case_fatality_rate")

    I("frailty_correction", 1)   # L5 parameter L-6

    F("upside_tier_value_annual",
      lambda n, pv, fr: n * pv * fr,
      ["upside_deaths_averted_annual", "hc_pv_per_cancer_death", "frailty_correction"],
      "upside_deaths_averted_annual * hc_pv_per_cancer_death * frailty_correction")

    # Morbidity productivity retained by survivors who never get the disease
    I("upside_morbidity_workdays_lost_per_case", 0)
    F("upside_morbidity_value_annual",
      lambda c, days, comp, emp: c * (days / Decimal(250)) * comp * emp,
      ["upside_cases_prevented_annual", "upside_morbidity_workdays_lost_per_case",
       "avg_annual_compensation", "emp_rate_4554"],
      "upside_cases_prevented_annual * (upside_morbidity_workdays_lost_per_case / 250) * "
      "avg_annual_compensation * emp_rate_4554")

    # ------------------------------------------------------------------
    # 12. VLY COMPARATOR - COMPUTED SEPARATELY, NEVER SUMMED WITH THE ABOVE.
    #     The wage sits inside the VLY (Scott/Ellison/Sinclair v_t contains w(t)),
    #     so VLY and human capital are ALTERNATIVE frames on the same hours.
    # ------------------------------------------------------------------
    I("vly_multiple_of_gdp", 0)     # L4 parameter N20: 2.3-3.0x
    I("life_years_per_averted_death", 0)   # L5 parameter L-7

    F("vly_per_life_year",
      lambda m, gdp: m * gdp,
      ["vly_multiple_of_gdp", "gdp_per_capita"],
      "vly_multiple_of_gdp * gdp_per_capita")

    F("vly_value_per_averted_death",
      lambda v, ly, fr: v * ly * fr,
      ["vly_per_life_year", "life_years_per_averted_death", "frailty_correction"],
      "vly_per_life_year * life_years_per_averted_death * frailty_correction")

    F("hc_as_share_of_vly_per_death",
      lambda hc, vly: hc / vly,
      ["hc_pv_per_cancer_death", "vly_value_per_averted_death"],
      "hc_pv_per_cancer_death / vly_value_per_averted_death")

    F("vly_upside_tier_value_annual",
      lambda n, v: n * v,
      ["upside_deaths_averted_annual", "vly_value_per_averted_death"],
      "upside_deaths_averted_annual * vly_value_per_averted_death")

    F("vly_base_tier_value_annual",
      lambda n, v: n * v,
      ["base_patients_annual", "vly_per_life_year"],
      "base_patients_annual * vly_per_life_year")

    F("vly_mid_tier_value_annual",
      lambda n, gy, v: n * gy * v,
      ["base_patients_annual", "mid_gain_years", "vly_per_life_year"],
      "base_patients_annual * mid_gain_years * vly_per_life_year")

    F("hc_as_share_of_vly_base_tier",
      lambda hc, vly: hc / vly,
      ["base_tier_value_annual", "vly_base_tier_value_annual"],
      "base_tier_value_annual / vly_base_tier_value_annual")

    F("hc_as_share_of_vly_mid_tier",
      lambda hc, vly: hc / vly,
      ["mid_tier_value_annual", "vly_mid_tier_value_annual"],
      "mid_tier_value_annual / vly_mid_tier_value_annual")

    F("hc_as_share_of_vly_upside_tier",
      lambda hc, vly: hc / vly,
      ["upside_tier_value_annual", "vly_upside_tier_value_annual"],
      "upside_tier_value_annual / vly_upside_tier_value_annual")

    # ------------------------------------------------------------------
    # 13. GROSS-OUTPUT (GDP-per-worker) VARIANT.
    #     The human-capital convention prices a lost working year at the
    #     worker's own COMPENSATION. Pricing it at GDP per worker instead adds
    #     capital's share of output. Reported as the upper bound of the
    #     market-productivity frame, never as the base.
    # ------------------------------------------------------------------
    I("gdp_per_worker", 0)

    F("output_basis_uplift",
      lambda gw, comp: gw / comp,
      ["gdp_per_worker", "avg_annual_compensation"],
      "gdp_per_worker / avg_annual_compensation")

    F("hc_pv_per_cancer_death_output_basis",
      lambda hc, up: hc * up,
      ["hc_pv_per_cancer_death", "output_basis_uplift"],
      "hc_pv_per_cancer_death * output_basis_uplift")

    F("hc_loss_annual_total_output_basis",
      lambda tot, up: tot * up,
      ["hc_loss_annual_total", "output_basis_uplift"],
      "hc_loss_annual_total * output_basis_uplift")

    # ------------------------------------------------------------------
    # 14. Observed age-cut shares carried as sourced inputs (not derived from
    #     the band lattice, which cannot split 55-64 or 65-74).
    # ------------------------------------------------------------------
    I("share_deaths_under_60_observed", 0)
    I("share_deaths_under_70_observed", 0)

    return g
