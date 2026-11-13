select zone, ts, psr_type, generation_mw
from {{ ref('stg_entsoe_generation') }}
