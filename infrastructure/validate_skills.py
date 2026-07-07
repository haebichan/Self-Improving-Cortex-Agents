"""
VALIDATE_SKILLS: Replays original questions against a test version of the agent
with the new skill loaded, then compares tool calls and latency vs baseline.

Deploy to: <YOUR_DB>.<YOUR_INFRA_SCHEMA>
Signature: VALIDATE_SKILLS(AGENT_NAME VARCHAR) RETURNS VARCHAR
Language: Python 3.11
Packages: snowflake-snowpark-python
Handler: run

Key design decisions:
- Moves PRODUCTION alias to test version during validation (DATA_AGENT_RUN routes to PRODUCTION alias)
- Uses 60s sleep for observability event flush (events take ~60s to appear)
- Restores original PRODUCTION alias after validation regardless of outcome
- Validation gate: new_calls < original_calls AND new_duration < original_duration
"""

def run(session, agent_name):
    import json
    import time

    parts = agent_name.split(".")
    if len(parts) != 3:
        return json.dumps({"status": "error", "message": "AGENT_NAME must be DB.SCHEMA.NAME"})
    db, schema, name = parts

    stage_base = f"@{db}.{schema}.AGENT_SKILLS"
    registry_table = f"{db}.{schema}.SKILL_REGISTRY"
    staging_table = f"{db}.{schema}.SKILL_CONTENT_STAGING"
    file_format = f"{db}.{schema}.TEXT_FORMAT"
    safe_agent = agent_name.replace("'", "''")

    skill_names = session.sql(f"""
        SELECT DISTINCT SKILL_NAME FROM {registry_table}
        WHERE STATUS = 'draft' AND AGENT_NAME = '{safe_agent}'
        AND ORIGINAL_QUESTION IS NOT NULL AND ORIGINAL_QUESTION NOT LIKE '[Could not extract%'
    """).collect()

    if not skill_names:
        return json.dumps({"status": "no_drafts_to_validate"})

    results = []

    for skill_row in skill_names:
        skill_name = skill_row["SKILL_NAME"]

        all_questions = session.sql(f"""
            SELECT DISTINCT ORIGINAL_QUESTION, ORIGINAL_TOOL_CALLS, ORIGINAL_DURATION_SECONDS, STATUS
            FROM {registry_table}
            WHERE SKILL_NAME = '{skill_name}' AND AGENT_NAME = '{safe_agent}'
            AND ORIGINAL_QUESTION IS NOT NULL AND ORIGINAL_QUESTION NOT LIKE '[Could not extract%'
            AND STATUS IN ('draft', 'active')
            ORDER BY ORIGINAL_TOOL_CALLS DESC
            LIMIT 5
        """).collect()

        if not all_questions:
            continue

        # Step 1: Read skill from staging path
        try:
            rows = session.sql(f"""
                SELECT $1 AS content FROM {stage_base}/staging/{skill_name}/SKILL.md 
                (FILE_FORMAT => '{file_format}')
            """).collect()
            if not rows:
                results.append({"skill": skill_name, "status": "error", "reason": "no staging file"})
                continue
            skill_content = rows[0]["CONTENT"]
        except Exception as e:
            results.append({"skill": skill_name, "status": "error", "reason": str(e)[:100]})
            continue

        # Copy to test path
        session.sql(f"TRUNCATE TABLE {staging_table}").collect()
        safe_content = skill_content.replace("'", "''")
        session.sql(f"INSERT INTO {staging_table} (CONTENT) VALUES ('{safe_content}')").collect()
        session.sql(f"""
            COPY INTO {stage_base}/skills/test/SKILL.md
            FROM (SELECT CONTENT FROM {staging_table})
            FILE_FORMAT = (TYPE = CSV FIELD_OPTIONALLY_ENCLOSED_BY = NONE COMPRESSION = NONE)
            OVERWRITE = TRUE
            SINGLE = TRUE
        """).collect()
        session.sql(f"ALTER STAGE {db}.{schema}.AGENT_SKILLS REFRESH").collect()

        # Step 2: Create candidate version with skill pointing to test path
        versions = session.sql(f"SHOW VERSIONS IN AGENT {agent_name}").collect()
        prod_spec = None
        prod_version_name = None
        for v in versions:
            if v["alias"] == "PRODUCTION":
                prod_spec = v["agent_spec"]
                prod_version_name = v["name"]
                break
        if not prod_spec:
            for v in versions:
                if str(v["is_default"]).lower() == "true":
                    prod_spec = v["agent_spec"]
                    prod_version_name = v["name"]
                    break
        if not prod_spec:
            results.append({"skill": skill_name, "status": "error", "reason": "no prod spec"})
            continue

        try:
            spec_json = json.loads(prod_spec)
            spec_json["skills"] = [{"name": skill_name, "source": {"type": "STAGE", "path": f"{stage_base}/skills/test/"}}]
            test_spec = json.dumps(spec_json)
        except:
            results.append({"skill": skill_name, "status": "error", "reason": "spec parse failed"})
            continue

        try:
            session.sql(f"ALTER AGENT {agent_name} ADD LIVE VERSION FROM LAST").collect()
        except:
            pass

        safe_spec = test_spec.replace("'", "''")
        try:
            session.sql(f"ALTER AGENT {agent_name} MODIFY LIVE VERSION SET SPECIFICATION = '{safe_spec}'").collect()
            session.sql(f"ALTER AGENT {agent_name} COMMIT COMMENT = 'Validation: {skill_name}'").collect()
        except Exception as e:
            results.append({"skill": skill_name, "status": "error", "reason": f"commit: {str(e)[:100]}"})
            continue

        versions_after = session.sql(f"SHOW VERSIONS IN AGENT {agent_name}").collect()
        test_version = None
        for v in sorted(versions_after, key=lambda x: x["created_on"], reverse=True):
            if v["name"] and "Validation" in (v["comment"] or ""):
                test_version = v["name"]
                break
        if not test_version:
            results.append({"skill": skill_name, "status": "error", "reason": "no test version"})
            continue

        # Move PRODUCTION alias to test version (critical: DATA_AGENT_RUN routes to PRODUCTION)
        session.sql(f"ALTER AGENT {agent_name} MODIFY VERSION {test_version} SET ALIAS = PRODUCTION").collect()
        session.sql(f"ALTER AGENT {agent_name} SET DEFAULT_VERSION = '{test_version}'").collect()

        # Step 3: Test ALL questions
        all_passed = True
        test_results = []

        for q_row in all_questions:
            original_question = q_row["ORIGINAL_QUESTION"]
            original_tool_calls = q_row["ORIGINAL_TOOL_CALLS"]
            original_duration = q_row["ORIGINAL_DURATION_SECONDS"]
            q_status = q_row["STATUS"]

            test_question = f"Using the {skill_name} skill, {original_question}"
            request_body = json.dumps({
                "messages": [{"role": "user", "content": [{"type": "text", "text": test_question}]}]
            }).replace("'", "''")

            try:
                session.sql(f"SELECT SNOWFLAKE.CORTEX.DATA_AGENT_RUN('{agent_name}', '{request_body}')").collect()
            except Exception as e:
                all_passed = False
                test_results.append({"question": original_question[:50], "from": q_status, "status": "error"})
                continue

            # Wait for observability events to flush (~60s latency)
            time.sleep(60)
            
            try:
                metrics = session.sql(f"""
                    SELECT 
                        COUNT(CASE WHEN RECORD:name::STRING LIKE 'SystemExecuteSQLTool%' OR RECORD:name::STRING LIKE 'ToolCall%' THEN 1 END) AS tool_executions,
                        TIMESTAMPDIFF('second', MIN(TIMESTAMP), MAX(TIMESTAMP)) AS duration_seconds
                    FROM TABLE(SNOWFLAKE.LOCAL.GET_AI_OBSERVABILITY_EVENTS(
                        '{db}', '{schema}', '{name}', 'CORTEX AGENT'
                    ))
                    WHERE TRACE['trace_id']::STRING IS NOT NULL
                    GROUP BY TRACE['trace_id']::STRING
                    ORDER BY MAX(TIMESTAMP) DESC
                    LIMIT 1
                """).collect()
            except Exception as e:
                all_passed = False
                test_results.append({"question": original_question[:50], "from": q_status, "status": "error"})
                continue

            if not metrics:
                all_passed = False
                test_results.append({"question": original_question[:50], "from": q_status, "status": "error"})
                continue

            new_calls = metrics[0]["TOOL_EXECUTIONS"]
            new_duration = metrics[0]["DURATION_SECONDS"]

            passed = (new_calls < original_tool_calls) and (new_duration < original_duration)
            test_results.append({
                "question": original_question[:50],
                "from": q_status,
                "status": "passed" if passed else "failed",
                "calls": f"{original_tool_calls}->{new_calls}",
                "duration": f"{original_duration}s->{new_duration}s"
            })
            if not passed:
                all_passed = False

        # Restore PRODUCTION alias to original version
        if prod_version_name:
            session.sql(f"ALTER AGENT {agent_name} MODIFY VERSION {prod_version_name} SET ALIAS = PRODUCTION").collect()
            session.sql(f"ALTER AGENT {agent_name} SET DEFAULT_VERSION = '{prod_version_name}'").collect()

        # Step 4: Pass or fail
        if all_passed:
            session.sql(f"""
                UPDATE {registry_table}
                SET STATUS = 'validated', UPDATED_AT = CURRENT_TIMESTAMP()
                WHERE SKILL_NAME = '{skill_name}' AND AGENT_NAME = '{safe_agent}' AND STATUS = 'draft'
            """).collect()
            results.append({"skill": skill_name, "status": "passed_all", "tests": test_results, "test_version": test_version})
        else:
            try:
                session.sql(f"ALTER AGENT {agent_name} DROP VERSION {test_version}").collect()
            except:
                pass
            session.sql(f"""
                UPDATE {registry_table}
                SET STATUS = 'failed_validation', UPDATED_AT = CURRENT_TIMESTAMP()
                WHERE SKILL_NAME = '{skill_name}' AND AGENT_NAME = '{safe_agent}' AND STATUS = 'draft'
            """).collect()
            results.append({"skill": skill_name, "status": "failed", "tests": test_results})

    try:
        session.sql(f"ALTER AGENT {agent_name} ADD LIVE VERSION FROM LAST").collect()
    except:
        pass

    return json.dumps({"status": "complete", "results": results})
