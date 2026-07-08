-- Schedule the self-learning pipeline as a recurring task
-- Run AFTER 02_deploy_procedures.sql
--
-- ============================================================
-- CONFIGURE: Set your parameters here
-- ============================================================
-- LOOKBACK_DAYS:        How often to run (1=daily, 7=weekly, 30=monthly)
-- MODEL_NAME:           Which LLM generates skills (claude-sonnet-4-5, llama3.1-70b, etc.)
-- TOOL_CALL_THRESHOLD:  Min tool calls to flag a trace as inefficient (see README)
-- CRON:                 Must match LOOKBACK_DAYS (see reference below)

-- ============================================================
-- Task creation
-- ============================================================
CREATE OR REPLACE TASK <YOUR_DB>.<YOUR_INFRA_SCHEMA>.EVOLVE_AGENT_TASK
    WAREHOUSE = 'COMPUTE_WH'
    SCHEDULE = 'USING CRON 0 2 * * 0 UTC'  -- Weekly (matches LOOKBACK_DAYS = 7)
    COMMENT = 'Self-learning pipeline: analyzes traces, generates/validates/promotes skills'
AS
    CALL <YOUR_DB>.<YOUR_INFRA_SCHEMA>.EVOLVE_SKILLS(
        '<YOUR_DB>.<YOUR_AGENT_SCHEMA>.YOUR_AGENT_NAME',
        7,                    -- LOOKBACK_DAYS (must match CRON schedule)
        'claude-sonnet-4-5',  -- MODEL_NAME for skill generation
        3                     -- TOOL_CALL_THRESHOLD (see README for tuning guidance)
    );

-- Resume the task (created in suspended state by default)
ALTER TASK <YOUR_DB>.<YOUR_INFRA_SCHEMA>.EVOLVE_AGENT_TASK RESUME;

-- ============================================================
-- Useful commands
-- ============================================================
-- Check task status:
-- SHOW TASKS LIKE 'EVOLVE_AGENT_TASK' IN SCHEMA <YOUR_DB>.<YOUR_INFRA_SCHEMA>;

-- Suspend:
-- ALTER TASK <YOUR_DB>.<YOUR_INFRA_SCHEMA>.EVOLVE_AGENT_TASK SUSPEND;

-- Run manually (for testing):
-- EXECUTE TASK <YOUR_DB>.<YOUR_INFRA_SCHEMA>.EVOLVE_AGENT_TASK;

-- View history:
-- SELECT * FROM TABLE(INFORMATION_SCHEMA.TASK_HISTORY())
-- WHERE NAME = 'EVOLVE_AGENT_TASK' ORDER BY SCHEDULED_TIME DESC LIMIT 10;
