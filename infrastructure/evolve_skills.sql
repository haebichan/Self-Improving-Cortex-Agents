-- EVOLVE_SKILLS: SQL Orchestrator that chains all 3 pipeline steps in sequence
-- Deploy to: <YOUR_DB>.<YOUR_INFRA_SCHEMA>
--
-- Usage:
--   CALL EVOLVE_SKILLS('DB.SCHEMA.AGENT_NAME', 7);   -- look back 7 days (default)
--   CALL EVOLVE_SKILLS('DB.SCHEMA.AGENT_NAME', 1);   -- look back 1 day (for daily tasks)
--
-- The LOOKBACK_DAYS parameter controls how far back to scan for inefficient traces.
-- Set this to match your task schedule:
--   Daily task   → LOOKBACK_DAYS = 1
--   Weekly task  → LOOKBACK_DAYS = 7
--   Monthly task → LOOKBACK_DAYS = 30

CREATE OR REPLACE PROCEDURE EVOLVE_SKILLS(AGENT_NAME VARCHAR, LOOKBACK_DAYS NUMBER DEFAULT 7)
RETURNS VARCHAR
LANGUAGE SQL
EXECUTE AS OWNER
AS
BEGIN
    LET create_result VARCHAR;
    LET validate_result VARCHAR;
    LET promote_result VARCHAR;
    
    CALL <YOUR_DB>.<YOUR_INFRA_SCHEMA>.CREATE_OR_REFINE_SKILLS(:AGENT_NAME, :LOOKBACK_DAYS) INTO :create_result;
    CALL <YOUR_DB>.<YOUR_INFRA_SCHEMA>.VALIDATE_SKILLS(:AGENT_NAME) INTO :validate_result;
    CALL <YOUR_DB>.<YOUR_INFRA_SCHEMA>.PROMOTE_SKILLS(:AGENT_NAME) INTO :promote_result;
    
    RETURN '{"create_or_refine": ' || :create_result || ', "validate": ' || :validate_result || ', "promote": ' || :promote_result || '}';
END;
