-- Deploy the self-learning pipeline stored procedures
-- Run AFTER 01_setup_infrastructure.sql
-- These go in the <YOUR_INFRA_SCHEMA> schema (shared infrastructure)

USE SCHEMA <YOUR_DB>.<YOUR_INFRA_SCHEMA>;

-- ============================================================
-- CREATE_OR_REFINE_SKILLS
-- Analyzes traces, generates skills using LLMs
-- ============================================================
CREATE OR REPLACE PROCEDURE CREATE_OR_REFINE_SKILLS(AGENT_NAME VARCHAR, LOOKBACK_DAYS NUMBER DEFAULT 7, MODEL_NAME VARCHAR DEFAULT 'claude-sonnet-4-5', TOOL_CALL_THRESHOLD NUMBER DEFAULT 3)
RETURNS VARCHAR
LANGUAGE PYTHON
RUNTIME_VERSION = '3.11'
PACKAGES = ('snowflake-snowpark-python')
HANDLER = 'run'
EXECUTE AS OWNER
AS
$$
# See infrastructure/create_or_refine_skills.py for documented source
# Copy the full function body from that file
$$;

-- ============================================================
-- VALIDATE_SKILLS
-- Replays questions, validates improvement vs baseline
-- ============================================================
CREATE OR REPLACE PROCEDURE VALIDATE_SKILLS(AGENT_NAME VARCHAR)
RETURNS VARCHAR
LANGUAGE PYTHON
RUNTIME_VERSION = '3.11'
PACKAGES = ('snowflake-snowpark-python')
HANDLER = 'run'
EXECUTE AS OWNER
AS
$$
# See infrastructure/validate_skills.py for documented source
# Copy the full function body from that file
$$;

-- ============================================================
-- PROMOTE_SKILLS
-- Deploys validated skills using agent versioning
-- ============================================================
CREATE OR REPLACE PROCEDURE PROMOTE_SKILLS(AGENT_NAME VARCHAR)
RETURNS VARCHAR
LANGUAGE PYTHON
RUNTIME_VERSION = '3.11'
PACKAGES = ('snowflake-snowpark-python')
HANDLER = 'run'
EXECUTE AS OWNER
AS
$$
# See infrastructure/promote_skills.py for documented source
# Copy the full function body from that file
$$;

-- ============================================================
-- EVOLVE_SKILLS (orchestrator)
-- Chains all 3 steps in sequence
-- LOOKBACK_DAYS: how far back to scan traces (match to your task schedule)
-- MODEL_NAME: which LLM to use for skill generation
-- TOOL_CALL_THRESHOLD: min tool calls to flag a trace as inefficient
-- ============================================================
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
