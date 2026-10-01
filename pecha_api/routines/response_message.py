ROUTINE_ALREADY_EXISTS = "Routine already exists for this user"
INVALID_TIME_FORMAT = "Time must be in HH:MM 24-hour format (00:00 to 23:59)"
SESSIONS_REQUIRED = "At least one session is required"
DUPLICATE_PLAN = "A plan can only appear once in a time block"
DUPLICATE_SERIES = "A series can only appear once in a time block"
DUPLICATE_RECITATION_COLLECTION = "A recitation collection can only appear once across the entire routine"
DUPLICATE_GROUP_RECITATION_COLLECTION = (
    "A group recitation collection can only appear once across the entire routine"
)
DUPLICATE_ACCUMULATOR = "An accumulator can only appear once in a time block"
DUPLICATE_GROUP_ACCUMULATOR = (
    "A group accumulation can only appear once in a time block"
)
ROUTINE_NOT_FOUND = "Routine not found"
ROUTINE_FORBIDDEN = "Routine does not belong to this user"
TIME_ALREADY_EXISTS = "A time block with this time already exists in the routine"
TIME_BLOCK_NOT_FOUND = "Time block not found"
TIME_BLOCK_TIME_CONFLICT = "Time block with this time already exists"
NO_ROUTINE_CREATED_FOR_USER = "No routine created for this user"
SERIES_NOT_FOUND = "Series not found"
SOURCE_ID_REQUIRED = (
    "source_id is required for PLAN, SERIES, RECITATION, RECITATION_COLLECTION, "
    "GROUP_RECITATION_COLLECTION, ACCUMULATOR, and GROUP_ACCUMULATOR sessions"
)
ACCUMULATOR_ID_REQUIRED = "accumulator_id is required for ACCUMULATOR sessions"
PRESET_ACCUMULATOR_NOT_FOUND = "Preset accumulator not found"
GROUP_ACCUMULATOR_ID_REQUIRED = (
    "group_accumulator_id is required for GROUP_ACCUMULATOR sessions"
)
GROUP_ACCUMULATOR_NOT_FOUND = "Group accumulator not found"
GROUP_ACCUMULATOR_NOT_JOINED = (
    "Join this group accumulation before adding it to your routine"
)
INVALID_TIMER_DURATION = "A TIMER session requires a positive duration_ms"