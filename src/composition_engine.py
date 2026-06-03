from typing import List
from pydantic import BaseModel, Field
import src.calibration as calibration

class CompositionPlan(BaseModel):
    """
    Structured breakdown of question allocation for a generated test.
    """
    target_total: int
    floor_count: int
    static_today: int
    static_backlog: int
    ca_today: int
    ca_backlog: int
    floor_topics: List[str] = Field(default_factory=list)
    backlog_topics: List[str] = Field(default_factory=list)
    mode: str = "DAILY_SPRINT"
    system_intent_header: str = ""


import math

def solve_composition(
    target_total: int = 30,
    available_static_backlog: int = 0,
    available_ca_backlog: int = 0,
    enforce_floor: bool = True,
    enforce_backlog: bool = True,
    mode: str = "DAILY_SPRINT"
) -> CompositionPlan:
    """
    Executes the pure-logic constraint solver for the test blueprint.
    
    Implements a 4-step 'remainder-absorb' allocation pipeline utilizing math.floor() 
    to guarantee invariants regardless of edge-case targets (e.g. N=1, N=15).
    """
    config = calibration.get_config()
    
    # Ratios (Defaults: floor=0.20, static=0.60, backlog=0.35)
    floor_ratio = config.curricular_floor["random_syllabus_allocation"]
    static_ratio = config.composition.static_ratio
    backlog_ratio = config.composition.backlog_ratio

    # ---------------------------------------------------------
    # STEP 1: FLOOR GUARANTEE
    # ---------------------------------------------------------
    # Random syllabus coverage. Always calculated first.
    if enforce_floor:
        floor_count = max(0, math.floor(target_total * floor_ratio))
    else:
        floor_count = 0
    
    # ---------------------------------------------------------
    # STEP 2: DYNAMIC QUOTA CALCULATION
    # ---------------------------------------------------------
    remaining_quota = target_total - floor_count

    # ---------------------------------------------------------
    # STEP 3: CONTENT TYPE SPLIT
    # ---------------------------------------------------------
    # Split the remaining quota into Static (Core) and CA (Current Affairs).
    # We floor the static calculation, then let CA absorb the remainder.
    static_count = max(0, math.floor(remaining_quota * static_ratio))
    ca_count = max(0, remaining_quota - static_count)

    # ---------------------------------------------------------
    # STEP 4: BACKLOG RULE (Within Category)
    # ---------------------------------------------------------
    # For both categories, calculate the desired backlog using math.floor().
    # If the desired backlog exceeds what's available, min() caps it.
    # The 'today' allocation then absorbs whatever static/ca quota remains.
    # This explicit subtraction guarantees that any unfilled backlog quota 
    # automatically rolls back into the 'today' allocation for that category.
    
    # Static Category
    if enforce_backlog:
        desired_static_backlog = math.floor(static_count * backlog_ratio)
        static_backlog = min(available_static_backlog, desired_static_backlog)
    else:
        static_backlog = 0
    static_today = max(0, static_count - static_backlog)

    # CA Category
    if enforce_backlog:
        desired_ca_backlog = math.floor(ca_count * backlog_ratio)
        ca_backlog = min(available_ca_backlog, desired_ca_backlog)
    else:
        ca_backlog = 0
    ca_today = max(0, ca_count - ca_backlog)

    return CompositionPlan(
        target_total=target_total,
        floor_count=floor_count,
        static_today=static_today,
        static_backlog=static_backlog,
        ca_today=ca_today,
        ca_backlog=ca_backlog,
        mode=mode
    )
