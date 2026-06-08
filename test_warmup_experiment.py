from datetime import datetime, UTC

def get_warmup_rate_limits(created_at: datetime, total_sent: int,
                           base_per_min: int, base_per_hour: int) -> tuple[int, int]:
    _age_days = (datetime.now(UTC) - created_at).days
    
    # Warmup schedule
    # Day 0-1: max 5/hr, Day 2-3: 10/hr, Day 4-7: 50/hr, Day 8-14: 100/hr, >14: Full
    # Or based on total_sent brackets
    # If total_sent < 100 and age < 2 -> severely limit
    
    # Let's say:
    # Phase 1: age <= 1 or total <= 50 -> 2/min, 10/hr
    # Phase 2: age <= 3 or total <= 200 -> 5/min, 50/hr
    # Phase 3: age <= 7 or total <= 1000 -> 10/min, 200/hr
    # Phase 4: Full capacity
    return (0, 0)

