-- Setup Script: Creates supporting infrastructure for the self-learning pipeline
-- Run this ONCE before deploying the stored procedures
--
-- This script creates ONLY the infrastructure needed by the pipeline.
-- Your agent and domain objects (tables, views, procedures) should already exist.
-- The pipeline works with ANY existing Cortex Agent.
--
-- Architecture:
--   <YOUR_INFRA_SCHEMA> = shared pipeline procs (EVOLVE_SKILLS, etc.)
--   <YOUR_AGENT_SCHEMA> = YOUR existing agent schema (where your agent lives)
--     The pipeline creates these objects IN your agent's schema:
--     - AGENT_SKILLS stage, SKILL_REGISTRY table, SKILL_CONTENT_STAGING table, TEXT_FORMAT

-- ============================================================
-- Step 1: Create infrastructure schema
-- ============================================================
CREATE SCHEMA IF NOT EXISTS <YOUR_DB>.<YOUR_INFRA_SCHEMA>;

-- ============================================================
-- Step 2: Create supporting objects in your agent's schema
-- These are needed by the pipeline to store/track skills
-- ============================================================
USE SCHEMA <YOUR_DB>.<YOUR_AGENT_SCHEMA>;

-- Internal stage for skill file storage
CREATE STAGE IF NOT EXISTS AGENT_SKILLS
    DIRECTORY = (ENABLE = TRUE)
    COMMENT = 'Stores generated skill .md files';

-- Skill registry for lifecycle tracking
CREATE OR REPLACE TABLE SKILL_REGISTRY (
    SKILL_NAME VARCHAR,
    STATUS VARCHAR,           -- draft | validated | active | failed_validation
    DESCRIPTION VARCHAR,
    TRACE_ID VARCHAR,
    AGENT_NAME VARCHAR,
    ORIGINAL_QUESTION VARCHAR,
    ORIGINAL_TOOL_CALLS NUMBER(38,0),
    ORIGINAL_DURATION_SECONDS NUMBER(38,0),
    CREATED_AT TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP(),
    UPDATED_AT TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP()
);

-- Staging table for COPY INTO operations
CREATE OR REPLACE TABLE SKILL_CONTENT_STAGING (
    CONTENT VARCHAR
);

-- File format for reading skill files from stage
CREATE OR REPLACE FILE FORMAT TEXT_FORMAT
    TYPE = CSV
    FIELD_DELIMITER = NONE
    RECORD_DELIMITER = NONE
    SKIP_HEADER = 0;

-- ============================================================
-- Done! Now deploy the pipeline procedures (02_deploy_procedures.sql)
-- Then call EVOLVE_SKILLS with your agent's fully-qualified name.
-- ============================================================
