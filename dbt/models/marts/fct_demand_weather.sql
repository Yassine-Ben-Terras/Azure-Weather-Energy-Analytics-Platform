with load as (
    select * from {{ ref('stg_entsoe_load') }}
),

-- Missing measurements remain NULL; absence does not establish zero production.
generation_pivot as (
    select
        zone,
        ts,
        sum(generation_mw) filter (where psr_type = 'B16') as solar_mw,
        sum(generation_mw) filter (where psr_type in ('B18', 'B19')) as wind_mw,
        sum(generation_mw) as total_generation_mw
    from {{ ref('stg_entsoe_generation') }}
    group by zone, ts
),

price as (
    select * from {{ ref('stg_entsoe_price') }}
),

weather as (
    select * from {{ ref('stg_openmeteo_weather') }}
)

select
    load.zone || '_' || load.ts::text as row_key,
    load.zone,
    load.ts,
    load.load_mw,
    generation_pivot.solar_mw as solar_mw,
    generation_pivot.wind_mw as wind_mw,
    generation_pivot.total_generation_mw,
    price.day_ahead_price,
    weather.temperature_2m,
    weather.wind_speed_10m,
    weather.shortwave_radiation
from load
left join generation_pivot
    on load.zone = generation_pivot.zone and load.ts = generation_pivot.ts
left join price
    on load.zone = price.zone and load.ts = price.ts
left join weather
    on load.zone = weather.zone and load.ts = weather.ts