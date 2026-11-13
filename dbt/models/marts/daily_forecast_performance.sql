select
    zone,
    (ts at time zone 'UTC')::date as day_utc,
    target,
    model_version,
    count(*) as evaluated_forecasts,
    avg(abs_error) as mae_mw,
    avg(error) as bias_mw
from {{ ref('forecasts_vs_actuals') }}
group by zone, (ts at time zone 'UTC')::date, target, model_version
