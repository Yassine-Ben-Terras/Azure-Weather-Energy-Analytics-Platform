select
    zone,
    (ts at time zone 'UTC')::date as day_utc,
    count(*) as demand_hours,
    count(total_generation_mw) as generation_hours,
    count(solar_mw) as solar_hours,
    count(wind_mw) as wind_hours,
    sum(load_mw) as observed_demand_mwh,
    max(load_mw) as peak_demand_mw,
    sum(total_generation_mw) as observed_generation_mwh,
    sum(solar_mw) as observed_solar_mwh,
    sum(wind_mw) as observed_wind_mwh,
    100.0 * sum(solar_mw) filter (where total_generation_mw is not null)
        / nullif(sum(total_generation_mw) filter (where solar_mw is not null), 0) as solar_share_pct,
    100.0 * sum(wind_mw) filter (where total_generation_mw is not null)
        / nullif(sum(total_generation_mw) filter (where wind_mw is not null), 0) as wind_share_pct
from {{ ref('fct_demand_weather') }}
group by zone, (ts at time zone 'UTC')::date
