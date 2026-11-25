"""Per-city wording for the transit and safety notes in the score metadata.

CDMX keeps its historical sentences verbatim (they are part of its published
metadata). Every other city gets notes generated from its own profile, so a city
never ships CDMX/FGJ wording.
"""

from __future__ import annotations

from cdmxmap.citycontext import CDMX_CITY_ID, CRIME_MODE_CITY_STATISTICS, CityContext
from cdmxmap.scoring.crime import (
    CrimeStatisticsSettings,
    incident_crime_source,
    incident_density_buffer_m,
)

CDMX_TRANSIT_NOTE = (
    "Transit score is 70% nearest Metro/Metrobus/Trolebus and 30% nearest "
    "RTP/Corredor Concesionado."
)
CDMX_SAFETY_NOTE = (
    "Safety score is lower-is-better crime density using the latest 12 months "
    "available in the FGJ file."
)
SAFETY_NOT_SCORED_NOTE = "Safety is not scored."
CLIPPED_SCORES_NOTE = "Scores are closer-is-better and clipped at the 95th percentile per metric."
STATISTICS_CLIPPED_SCORES_NOTE = (
    "Distance, time and transit scores are closer-is-better and clipped at the 95th "
    "percentile per metric; the safety score is a within-metro ranking of municipalities "
    "(see the safety note)."
)
# When a group has no declared system the engine scores that share against all stops.
ANY_STOP_LABEL = "any transit stop"


def _plural(noun: str) -> str:
    """English plural of a unit noun ("municipality" -> "municipalities")."""
    if noun.endswith("y") and noun[-2:-1] not in set("aeiou"):
        return f"{noun[:-1]}ies"
    return f"{noun}s"


def _percent(weight: float) -> str:
    return f"{round(weight * 100, 1):g}"


def _group_labels(ctx: CityContext, group: str) -> str:
    labels = [spec.label or spec.code for spec in ctx.transit_systems if spec.group == group]
    return " / ".join(labels) or ANY_STOP_LABEL


def transit_score_note(ctx: CityContext) -> str:
    if ctx.city_id == CDMX_CITY_ID:
        return CDMX_TRANSIT_NOTE
    return (
        f"Transit score is {_percent(ctx.core_weight)}% nearest {_group_labels(ctx, 'core')} "
        f"and {_percent(ctx.surface_weight)}% nearest {_group_labels(ctx, 'surface')}."
    )


def safety_score_note(ctx: CityContext) -> str:
    if ctx.city_id == CDMX_CITY_ID:
        return CDMX_SAFETY_NOTE
    if float(ctx.weights.get("safety", 0.0)) <= 0:
        return SAFETY_NOT_SCORED_NOTE
    if ctx.crime_mode == CRIME_MODE_CITY_STATISTICS:
        settings = CrimeStatisticsSettings.from_profile(ctx.profile)
        source_label = settings.source_label or settings.source or "municipal crime statistics"
        scope = settings.scope
        return (
            f"Safety score ranks the {_plural(scope)} within the metro by "
            f"{settings.scored_label} per 100k residents ({source_label}): the lowest rate "
            f"scores 100 and the highest 0, linearly; every area in a {scope} shares its "
            f"{scope}'s score."
        )
    declared = ctx.profile.get("crime_source") or {}
    source_label = str(declared.get("source_label") or "") or (
        incident_crime_source(ctx) if declared else "configured crime-incident"
    )
    buffer_m = incident_density_buffer_m(ctx)
    if buffer_m > 0:
        return (
            "Safety score is lower-is-better incident density per km² over each area plus "
            f"a {buffer_m} m buffer, latest 12 months in the {source_label} data."
        )
    return (
        "Safety score is lower-is-better incident density per km² over the latest 12 "
        f"months in the {source_label} data."
    )


def score_scaling_note(ctx: CityContext) -> str:
    """How scores are scaled. Statistics-mode safety is min-max ranked, not p95-clipped,
    so only those cities get the qualified sentence; every other city keeps the original."""
    if ctx.crime_mode == CRIME_MODE_CITY_STATISTICS:
        return STATISTICS_CLIPPED_SCORES_NOTE
    return CLIPPED_SCORES_NOTE
