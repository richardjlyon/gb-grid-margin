# Engine notes — methodology decisions and known limitations

The points below are where the published numbers depend on a choice or an external input.
Each is documented so the figures can be checked and reproduced. Resolve each before the
figure it affects goes live.

## 1. Solar is not in FUELINST

FUELINST reports transmission-metered generation. Embedded solar is netted off national demand
and does not appear in it. At a summer midday this materially affects renewables' and gas/
imports' shares. Any figure that involves solar — the capacity-share, the verdict pair, the
"solar now" card — must use a real solar outturn series first.

Candidate sources, both free:
- **NESO embedded solar/wind estimate** — the figure NESO uses to reconstruct demand.
- **Sheffield Solar PV_Live** — the standard GB solar outturn series.

Open decision: which solar source, and whether the verdict denominator is *national demand*
(embedded wind + solar inside it) or *transmission supply*. This sets every published share,
so it is decided once and stated on the methodology page.

## 2. Nameplate (installed-capacity) denominators

`data/nameplate.json` currently holds placeholders. The capacity-share, the wind stripe and
the low-output counter all divide by installed wind (and solar) capacity. These figures come
from REPD / DUKES and must be kept current and dated. No "% of capacity" figure is published
until they are sourced.

## 3. Verdict denominator definition

The engine currently uses the sum of all positive-flowing sources (generation + net imports),
excluding pumping/export load. This is reported as the share of the live grid mix. See #1:
once embedded solar is ingested, the denominator is aligned with national demand and the exact
formula is stated.

## 4. Interconnectors

Net flows are summed across all `INT*` fuel types; v1 reports the net figure. Per-country
attribution is a later addition.
