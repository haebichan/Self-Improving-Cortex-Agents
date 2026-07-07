"""
CREATE_OR_REFINE_SKILLS: Analyzes agent observability traces, detects inefficient 
orchestration patterns, and generates operational skills using LLMs.

Deploy to: <YOUR_DB>.<YOUR_INFRA_SCHEMA>
Signature: CREATE_OR_REFINE_SKILLS(AGENT_NAME VARCHAR, LOOKBACK_DAYS NUMBER DEFAULT 7) RETURNS VARCHAR
Language: Python 3.11
Packages: snowflake-snowpark-python
Handler: run

Key design decisions:
- Uses correct observability trace attribute paths:
  - snow.ai.observability.agent.tool.custom_tool.argument.value (not ai.tool.input)
  - snow.ai.observability.agent.tool.custom_tool.results (not ai.tool.output)
- Dynamically resolves stage/registry/format paths from AGENT_NAME (DB.SCHEMA.NAME)
- Detects traces with >3 tool calls as candidates for skill generation
- Reads existing skills to support REFINEMENT (updating existing skills for new patterns)
- Uses SNOWFLAKE.CORTEX.COMPLETE with model='auto' for skill generation
"""

def run(session, agent_name, lookback_days=7):
    import json
    import re

    TOOL_CALL_THRESHOLD = 3
    lookback_days = int(lookback_days)

    parts = agent_name.split('.')
    if len(parts) != 3:
        return json.dumps({"status": "error", "message": "AGENT_NAME must be fully qualified: DB.SCHEMA.NAME"})
    db, schema, name = parts

    stage_base = f"@{db}.{schema}.AGENT_SKILLS"
    registry_table = f"{db}.{schema}.SKILL_REGISTRY"
    staging_table = f"{db}.{schema}.SKILL_CONTENT_STAGING"
    file_format = f"{db}.{schema}.TEXT_FORMAT"

    # Track already-processed traces to avoid duplicates
    processed_traces = set()
    try:
        rows = session.sql(f"SELECT TRACE_ID FROM {registry_table} WHERE TRACE_ID IS NOT NULL AND AGENT_NAME = '{agent_name}'").collect()
        processed_traces = {r['TRACE_ID'] for r in rows}
    except:
        pass

    # Find traces with excessive tool calls (indicating retries/failures)
    try:
        retry_traces = session.sql(f"""
            SELECT 
                TRACE['trace_id']::STRING AS trace_id,
                COUNT(CASE WHEN RECORD:name::STRING LIKE 'SystemExecuteSQLTool%' OR RECORD:name::STRING LIKE 'ToolCall%' THEN 1 END) AS tool_executions,
                TIMESTAMPDIFF('second', MIN(TIMESTAMP), MAX(TIMESTAMP)) AS duration_seconds
            FROM TABLE(SNOWFLAKE.LOCAL.GET_AI_OBSERVABILITY_EVENTS(
                '{db}', '{schema}', '{name}', 'CORTEX AGENT'
            ))
            WHERE TRACE['trace_id']::STRING IS NOT NULL
              AND TIMESTAMP > DATEADD('day', -{lookback_days}, CURRENT_TIMESTAMP())
            GROUP BY trace_id
            HAVING tool_executions > {TOOL_CALL_THRESHOLD}
            ORDER BY MAX(TIMESTAMP) DESC
            LIMIT 10
        """).collect()
    except Exception as e:
        return json.dumps({"status": "error", "message": str(e)[:200]})

    if not retry_traces:
        return json.dumps({"status": "no_retries_found"})

    retry_traces = [t for t in retry_traces if t['TRACE_ID'] not in processed_traces]
    if not retry_traces:
        return json.dumps({"status": "all_traces_already_processed", "processed_count": len(processed_traces)})

    # Extract the user question from each trace
    trace_questions = {}
    try:
        trace_ids_list = "','".join([t['TRACE_ID'] for t in retry_traces])
        question_rows = session.sql(f"""
            SELECT TRACE['trace_id']::STRING AS trace_id,
                RECORD_ATTRIBUTES:"ai.observability.record_root.input"::STRING AS user_question
            FROM TABLE(SNOWFLAKE.LOCAL.GET_AI_OBSERVABILITY_EVENTS(
                '{db}', '{schema}', '{name}', 'CORTEX AGENT'
            ))
            WHERE RECORD:"name"::STRING = 'AgentV2RequestResponseInfo'
              AND TRACE['trace_id']::STRING IN ('{trace_ids_list}')
        """).collect()
        for qr in question_rows:
            if qr['USER_QUESTION']:
                trace_questions[qr['TRACE_ID']] = qr['USER_QUESTION'][:500]
    except:
        pass

    # Load existing skills for refinement context
    existing_skills = []
    try:
        rows = session.sql(f"SELECT SKILL_NAME, DESCRIPTION FROM {registry_table} WHERE STATUS = 'active' AND AGENT_NAME = '{agent_name}'").collect()
        for r in rows:
            skill_info = {"name": r['SKILL_NAME'], "desc": r['DESCRIPTION'], "content": "", "questions": []}
            try:
                content_rows = session.sql(f"""
                    SELECT $1 AS content FROM {stage_base}/skills/{r['SKILL_NAME']}/SKILL.md
                    (FILE_FORMAT => '{file_format}')
                """).collect()
                if content_rows:
                    skill_info["content"] = content_rows[0]['CONTENT'][:2000]
            except:
                pass
            try:
                q_rows = session.sql(f"SELECT ORIGINAL_QUESTION FROM {registry_table} WHERE SKILL_NAME = '{r['SKILL_NAME']}' AND STATUS = 'active' AND AGENT_NAME = '{agent_name}'").collect()
                skill_info["questions"] = [q['ORIGINAL_QUESTION'] for q in q_rows if q['ORIGINAL_QUESTION']]
            except:
                pass
            existing_skills.append(skill_info)
    except:
        pass

    # Get detailed trace data using CORRECT attribute paths
    all_trace_data = []
    traces_summary = ""
    for t in retry_traces:
        trace_data = {"trace_id": t['TRACE_ID'], "tool_executions": t['TOOL_EXECUTIONS'], "duration": t['DURATION_SECONDS'], "question": trace_questions.get(t['TRACE_ID'], 'unknown')}
        all_trace_data.append(trace_data)
        try:
            detail_rows = session.sql(f"""
                SELECT RECORD:name::STRING AS span_name,
                    RECORD_ATTRIBUTES:"snow.ai.observability.agent.tool.custom_tool.name"::STRING AS tool_name,
                    RECORD_ATTRIBUTES:"snow.ai.observability.agent.tool.custom_tool.argument.name"::STRING AS arg_names,
                    RECORD_ATTRIBUTES:"snow.ai.observability.agent.tool.custom_tool.argument.value"::STRING AS arg_values,
                    RECORD_ATTRIBUTES:"snow.ai.observability.agent.tool.custom_tool.results"::STRING AS tool_results
                FROM TABLE(SNOWFLAKE.LOCAL.GET_AI_OBSERVABILITY_EVENTS(
                    '{db}', '{schema}', '{name}', 'CORTEX AGENT'
                ))
                WHERE TRACE['trace_id']::STRING = '{t['TRACE_ID']}'
                  AND (RECORD:name::STRING LIKE 'SystemExecuteSQLTool%' OR RECORD:name::STRING LIKE 'ToolCall%')
                ORDER BY TIMESTAMP ASC
            """).collect()
            trace_detail = f"\n--- TRACE: {trace_data['question'][:80]} ({t['TOOL_EXECUTIONS']} calls, {t['DURATION_SECONDS']}s) ---\n"
            for dr in detail_rows:
                tool_name = dr['TOOL_NAME'] or dr['SPAN_NAME']
                args = ""
                if dr['ARG_NAMES'] and dr['ARG_VALUES']:
                    args = f"args({dr['ARG_NAMES']}={dr['ARG_VALUES']})"
                result = dr['TOOL_RESULTS'][:300] if dr['TOOL_RESULTS'] else ''
                trace_detail += f"  {tool_name}: {args} -> {result}\n"
            traces_summary += trace_detail
        except:
            pass

    new_questions = "\n".join([f"- {t['question']}" for t in all_trace_data])
    existing_skills_text = "None (creating first skill)" if not existing_skills else ""
    for s in existing_skills:
        existing_skills_text += f"\nSkill '{s['name']}': {s['desc']}\nContent: {s['content'][:500]}\nHistorical questions: {s['questions']}\n"

    prompt = f"""You are generating a SKILL.md for a Cortex Agent. The agent struggled with these questions (too many tool calls due to retries/errors). Your skill must teach the agent the CORRECT pattern to avoid errors on the FIRST try.

RULES:
- Reference the agent's tools by their actual names from the traces
- Be SPECIFIC about what causes errors and how to avoid them
- MAX 8 lines after frontmatter
- Skill name must use keywords from the questions

EXISTING SKILLS:
{existing_skills_text}

FAILED QUESTIONS:
{new_questions}

TRACES:
{traces_summary[:4000]}

Return ONLY the SKILL.md content:
---
name: <kebab-case-with-question-keywords>
description: <trigger words from questions>
---
<5-8 specific lines>"""

    safe_prompt = prompt.replace("'", "''")
    try:
        result_row = session.sql(f"SELECT SNOWFLAKE.CORTEX.COMPLETE('auto', '{safe_prompt}') AS result").collect()
        skill_content = result_row[0]['RESULT'] if result_row else None
    except Exception as e:
        return json.dumps({"status": "error", "message": f"AI_COMPLETE failed: {str(e)[:100]}"})

    if not skill_content:
        return json.dumps({"status": "error", "message": "empty skill content"})

    # Extract skill name from generated content
    skill_name = None
    lines = re.split(r'[\n\\n]+', skill_content)
    for line in lines:
        line = line.strip()
        if line.startswith('name:'):
            extracted = line.replace('name:', '').strip().strip('"').strip("'")
            if extracted and len(extracted) > 3 and not extracted.startswith('auto-'):
                skill_name = extracted
            break
    if not skill_name:
        match = re.search(r'name:\s*([a-z][a-z0-9-]+)', skill_content)
        if match:
            skill_name = match.group(1)
    if not skill_name:
        skill_name = 'learned-pattern'

    # Write skill to staging path
    session.sql(f"TRUNCATE TABLE {staging_table}").collect()
    safe_content = skill_content.replace("'", "''")
    session.sql(f"INSERT INTO {staging_table} (CONTENT) VALUES ('{safe_content}')").collect()
    session.sql(f"""
        COPY INTO {stage_base}/staging/{skill_name}/SKILL.md
        FROM (SELECT CONTENT FROM {staging_table})
        FILE_FORMAT = (TYPE = CSV FIELD_OPTIONALLY_ENCLOSED_BY = NONE COMPRESSION = NONE)
        OVERWRITE = TRUE SINGLE = TRUE
    """).collect()

    # Register in skill registry
    desc_line = ""
    for line in lines:
        line = line.strip()
        if line.startswith('description:'):
            desc_line = line.replace('description:', '').strip().strip('"').strip("'")[:100]
            break
    safe_desc = desc_line.replace("'", "''")

    for t in all_trace_data:
        safe_question = t['question'].replace("'", "''")
        session.sql(f"""
            MERGE INTO {registry_table} AS tgt
            USING (SELECT '{t['trace_id']}' AS trace_id, '{agent_name}' AS agent_name) AS src
            ON tgt.TRACE_ID = src.trace_id AND tgt.AGENT_NAME = src.agent_name
            WHEN MATCHED THEN UPDATE SET 
                SKILL_NAME = '{skill_name}', STATUS = 'draft', DESCRIPTION = '{safe_desc}',
                ORIGINAL_QUESTION = '{safe_question}', ORIGINAL_TOOL_CALLS = {t['tool_executions']},
                ORIGINAL_DURATION_SECONDS = {t['duration']}, UPDATED_AT = CURRENT_TIMESTAMP()
            WHEN NOT MATCHED THEN INSERT (SKILL_NAME, STATUS, DESCRIPTION, ORIGINAL_QUESTION, ORIGINAL_TOOL_CALLS, ORIGINAL_DURATION_SECONDS, TRACE_ID, AGENT_NAME, CREATED_AT, UPDATED_AT)
                VALUES ('{skill_name}', 'draft', '{safe_desc}', '{safe_question}', {t['tool_executions']}, {t['duration']}, '{t['trace_id']}', '{agent_name}', CURRENT_TIMESTAMP(), CURRENT_TIMESTAMP())
        """).collect()

    session.sql(f"ALTER STAGE {db}.{schema}.AGENT_SKILLS REFRESH").collect()
    return json.dumps({"status": "success", "skills_created": [skill_name], "traces_analyzed": len(all_trace_data)})
