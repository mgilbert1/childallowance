"""child_allowance_distributional_impact.ipynb

Automatically generated by Colaboratory.

Original file is located at
    https://colab.research.google.com/drive/15O7GKYztNVAXtS6uuo-Y_XCawjLJ3qz-

# Distributional impact of tax-funded child allowance by state

Approach:
* Calculate SPM resources, people, children (people under 18) and taxable
  income per SPM unit
* Calculate deciles of SPM resources per person, both nationally and by state
  [TODO: Adjust numbers for inflation across years.]
* Calculate taxable income per child for each state, and merge that back to
  the person dataframe
* Calculate the change in income per dollar of child allowance for each person,
using SPM columns
* Aggregate to SPM unit
"""

import microdf as mdf
import pandas as pd
import numpy as np
import us

# Load data from Nate's repo, which pulls from IPUMS.

raw = pd.read_csv(
    "https://github.com/ngpsu22/State_Child_Allowance_Income_Tax/raw/master/cps_00022.csv.gz"
)

df = raw.copy(deep=True)

# Clean up.
df.columns = df.columns.str.lower()
df.taxinc = np.where(df.taxinc == 9999999, 0, df.taxinc)
df.adjginc = np.where(df.adjginc == 99999999, 0, df.adjginc)
df.asecwt /= 3  # 3 years
df.spmwt /= 3
df["child"] = df.age < 18
df["person"] = 1
df["state"] = df.statefip.apply(
    lambda x: us.states.lookup(str(x).zfill(2)).name
).tolist()

"""Aggregate to SPM unit."""

SPMU_COLS = ["spmfamunit", "year", "state", "spmwt", "spmtotres"]
spmu = pd.DataFrame(
    df.groupby(SPMU_COLS)[["child", "person", "taxinc"]].sum()
).reset_index()
# Calculate weight that represents number of people.
# Note: no longer used.
spmu["wt"] = spmu.spmwt * spmu.person
spmu["spm_resources_pp"] = spmu.spmtotres / spmu.person
# spmu.columns = ['spm_child', 'spm_person', 'spm_taxinc']
mdf.add_weighted_quantiles(spmu, "spm_resources_pp", "spmwt")
spmu.drop(
    [
        "spm_resources_pp_percentile",
        "spm_resources_pp_2percentile",
        "spm_resources_pp_ventile",
        "spm_resources_pp_quintile",
        "spm_resources_pp_quartile",
    ],
    axis=1,
    inplace=True,
)
# Include negatives in the first decile.
# TODO: Make this an option in microdf.
spmu.spm_resources_pp_decile = np.maximum(spmu.spm_resources_pp_decile, 1)

spmu.groupby("spm_resources_pp_decile")[["wt", "spmwt"]].sum()

"""Now for state."""

states = df.state.unique()
l = []
for state in states:
    # Get row and spm_resources_pp_decile_state
    tmp = spmu[spmu.state == state].copy(deep=True)
    mdf.add_weighted_quantiles(tmp, "spm_resources_pp", "spmwt")
    l.append(tmp.spm_resources_pp_decile)
state_decile = pd.concat(l).rename("spm_resources_pp_decile_state")
state_decile = np.maximum(state_decile, 1)

spmu = spmu.join(pd.DataFrame(state_decile))

"""## Calculate necessary amount per state

NB: These are all weighted by SPM unit, not individuals.
"""

# TODO: Support multiple columns in mdf.weighted_sum, with a groupby.
taxinc_state = spmu.groupby("state").apply(
    lambda x: mdf.weighted_sum(x, "taxinc", "spmwt")
)
taxinc_state.name = "taxinc"
children_state = spmu.groupby("state").apply(
    lambda x: mdf.weighted_sum(x, "child", "spmwt")
)
children_state.name = "children"
state = taxinc_state.to_frame().join(children_state)
state["state_taxinc_per_child"] = state.taxinc / state.children
spmu2 = spmu.merge(state[["state_taxinc_per_child"]], left_on="state", right_index=True)

"""Calculate change per dollar of child allowance.

NB: These are weighted by
"""

total_taxinc = mdf.weighted_sum(spmu2, "taxinc", "spmwt")
total_children = mdf.weighted_sum(spmu2, "child", "spmwt")
fed_taxinc_per_child = total_taxinc / total_children
fed_taxinc_per_child

"""
Since each dollar of child allowance equals the number of children,
a SPM unit's tax per dollar of child allowance equals their taxable income
divided by the overall taxable income per child.

For example, a SPM unit with average income within the country or state will
pay that average amount, and any deviations from that will be in proportion
to income.
"""

spmu2["tax_per_dollar_ca_fed"] = spmu2.taxinc / fed_taxinc_per_child
spmu2["net_per_dollar_ca_fed"] = spmu2.child - spmu2.tax_per_dollar_ca_fed
spmu2["tax_per_dollar_ca_state"] = spmu2.taxinc / spmu2.state_taxinc_per_child
spmu2["net_per_dollar_ca_state"] = spmu2.child - spmu2.tax_per_dollar_ca_state
spmu2["tax_per_dollar_ca_deficit"] = 0
spmu2["net_per_dollar_ca_deficit"] = spmu2.child


# Check that it nets out, both overall and by decile.
assert np.allclose(0, mdf.weighted_mean(spmu2, "net_per_dollar_ca_fed", "spmwt"))
assert np.allclose(
    0,
    spmu2.groupby("spm_resources_pp_decile")
    .apply(lambda x: mdf.weighted_mean(x, "net_per_dollar_ca_fed", "spmwt"))
    .mean(),
    atol=1e-5,
)


# Calculate data for each state x funding cross.
def decile_maker(funding: str, state: bool):
    """
    Args:
        funding: Column representing funding (net_per_dollar_ca_*).
        state: Whether to group by state.

    Returns:
        DataFrame with the columns:
        * decile
        * net_per_dollar_ca
        * state ('US' if state is False)
        * funding
    """
    # Use state decile for state-level calculation.
    decile = "spm_resources_pp_decile"
    groupby = decile
    if state:
        decile += "_state"
        groupby = [decile, "state"]
    # Set column for net change.
    net = "net_per_dollar_ca_" + funding
    # Run grouped calculation.
    res = (
        spmu2.groupby(groupby)
        .apply(lambda x: mdf.weighted_mean(x, net, "spmwt"))
        .reset_index()
    )
    # Rename and set columns for returning.
    res.rename({decile: "decile", 0: "net_per_dollar_ca"}, axis=1, inplace=True)
    res["funding"] = funding
    if not state:
        res["state"] = "US"
    return res


all_deciles = pd.concat(
    [
        decile_maker("deficit", True),
        decile_maker("deficit", False),
        decile_maker("fed", True),
        decile_maker("fed", False),
        decile_maker("state", True),
        decile_maker("state", False),
    ]
)


# Calculate children for deficit-funded amount and
# current resources for percentage differences.
def avg_res(x):
    resources = mdf.weighted_sum(x, "spmtotres", "spmwt")
    spmus = x.spmwt.sum()
    return resources / spmus


state_decile_resources = (
    spmu2.groupby(["spm_resources_pp_decile_state", "state"])
    .apply(avg_res)
    .reset_index()
)
state_decile_resources.rename(
    {"spm_resources_pp_decile_state": "decile"}, axis=1, inplace=True
)
fed_decile_resources = (
    spmu2.groupby("spm_resources_pp_decile").apply(avg_res).reset_index()
)
fed_decile_resources.rename({"spm_resources_pp_decile": "decile"}, axis=1, inplace=True)
fed_decile_resources["state"] = "US"
decile_resources = pd.concat([state_decile_resources, fed_decile_resources])
decile_resources.rename({0: "current_resources"}, axis=1, inplace=True)

all_deciles2 = all_deciles.merge(decile_resources, on=["decile", "state"])

# Replicate for each monthly child allowance amount.
l = []
for i in np.arange(0, 501, 25):
    tmp = all_deciles2.copy(deep=True)
    tmp["monthly_ca"] = i
    tmp["net_chg"] = i * 12 * tmp.net_per_dollar_ca
    l.append(tmp)
ca_state_decile = pd.concat(l)

ca_state_decile["pct_chg"] = (
    100 * ca_state_decile.net_chg / ca_state_decile.current_resources
)

ca_state_decile.to_csv("deciles.csv", index=False)
