-- EVOLVE_SKILLS: SQL Orchestrator that chains all 3 pipeline steps in sequence
-- Deploy to: <YOUR_DB>.<YOUR_INFRA_SCHEMA>
--
-- Usage:
--   CALL EVOLVE_SKILLS('DB.SCHEMA.AGENT_NAME');                              -- all defaults
--   CALL EVOLVE_SKILLS('DB.SCHEMA.AGENT_NAME', 7, 'claude-sonnet-4-5', 3);  -- explicit
--   CALL EVOLVE_SKILLS('DB.SCHEMA.AGENT_NAME', 1, 'llama3.1-70b', 5);       -- daily, different model, higher threshold
--
-- Parameters:
--   AGENT_NAME           — Fully qualified agent name (DB.SCHEMA.NAME)
--   LOOKBACK_DAYS        — How far back to scan traces. Match to your task schedule.
--   MODEL_NAME           — Which LLM to use for skill generation via CORTEX.COMPLETE
--   TOOL_CALL_THRESHOLD  — Min tool calls to flag a trace as inefficient (see README)

CREATE OR REPLACE PROCEDURE EVOLVE_SKILLS(
    AGENT_NAME VARCHAR,
    LOOKBACK_DAYS NUMBER DEFAULT 7,
    MODEL_NAME VARCHAR DEFAULT 'claude-sonnet-4-5',
    TOOL_CALL_THRESHOLD NUMBER DEFAULT 3
)
RETURNS VARCHAR
LANGUAGE SQL
EXECUTE AS OWNER
AS
BEGIN
    LET create_result VARCHAR;
    LET validate_result VARCHAR;
    LET promote_result VARCHAR;
    
    CALL <YOUR_DB>.<YOUR_INFRA_SCHEMA>.CREATE_OR_REFINE_SKILLS(:AGENT_NAME, :LOOKBACK_DAYS, :MODEL_NAME, :TOOL_CALL_THRESHOLD) INTO :create_result;
    CALL <YOUR_DB>.<YOUR_INFRA_SCHEMA>.VALIDATE_SKILLS(:AGENT_NAME) INTO :validate_result;
    CALL <YOUR_DB>.<YOUR_INFRA_SCHEMA>.PROMOTE_SKILLS(:AGENT_NAME) INTO :promote_result;
    
    RETURN '{"create_or_refine": ' || :create_result || ', "validate": ' || :validate_result || ', "promote": ' || :promote_result || '}';
END;
