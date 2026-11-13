with observations as (
    select zone, ts, 'load' as source from {{ ref('stg_entsoe_load') }}
    union all
    select zone, ts, 'generation' from {{ ref('stg_entsoe_generation') }}
    union all
    select zone, ts, 'weather' from {{ ref('stg_openmeteo_weather') }}
    union all
    select zone, ts, 'day_ahead_price' from {{ ref('stg_entsoe_price') }}
),
zones as (
    select distinct zone from observations
),
sources(source) as (
    values ('load'), ('generation'), ('weather'), ('day_ahead_price')
),
bounds as (
    select date_trunc('hour', current_timestamp) as end_hour
)
select
    zones.zone,
    sources.source,
    bounds.end_hour as checked_through,
    max(obs.ts) as latest_observation,
    count(distinct obs.ts) filter (
        where obs.ts >= bounds.end_hour - interval '24 hours'
    ) as observed_hours_last_24h,
    24 - count(distinct obs.ts) filter (
        where obs.ts >= bounds.end_hour - interval '24 hours'
    ) as missing_hours_last_24h
from zones
cross join sources
cross join bounds
left join observations obs
    on obs.zone = zones.zone and obs.source = sources.source and obs.ts < bounds.end_hour
group by zones.zone, sources.source, bounds.end_hour
