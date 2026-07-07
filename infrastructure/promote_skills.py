"""
PROMOTE_SKILLS: Deploys validated skills to production using agent versioning.
Copies skill from staging to permanent stage path, creates new agent version,
and sets PRODUCTION alias.

Deploy to: <YOUR_DB>.<YOUR_INFRA_SCHEMA>
Signature: PROMOTE_SKILLS(AGENT_NAME VARCHAR) RETURNS VARCHAR
Language: Python 3.11
Packages: snowflake-snowpark-python
Handler: run

Key design decisions:
- Reads validated skills from registry, copies from staging/ to skills/{name}/ path
- Creates new committed version with ADD LIVE VERSION FROM LAST + COMMIT
- Sets PRODUCTION alias on new version for DATA_AGENT_RUN routing
- Cleans up old validation versions
"""

def run(session, agent_name):
    import json

    parts = agent_name.split(".")
    if len(parts) != 3:
        return json.dumps({"status": "error", "message": "AGENT_NAME must be DB.SCHEMA.NAME"})
    db, schema, name = parts

    stage_base = f"@{db}.{schema}.AGENT_SKILLS"
    registry_table = f"{db}.{schema}.SKILL_REGISTRY"
    staging_table = f"{db}.{schema}.SKILL_CONTENT_STAGING"
    file_format = f"{db}.{schema}.TEXT_FORMAT"
    safe_agent = agent_name.replace("'", "''")

    validated = session.sql(f"""
        SELECT SKILL_NAME FROM {registry_table}
        WHERE STATUS = 'validated' AND AGENT_NAME = '{safe_agent}'
        ORDER BY UPDATED_AT DESC
    """).collect()

    if not validated:
        return json.dumps({"status": "nothing_to_promote"})

    versions = session.sql(f"SHOW VERSIONS IN AGENT {agent_name}").collect()
    prod_spec = None
    for v in versions:
        if v["alias"] == "PRODUCTION":
            prod_spec = v["agent_spec"]
            break
    if not prod_spec:
        for v in versions:
            if str(v["is_default"]).lower() == "true":
                prod_spec = v["agent_spec"]
                break
    if not prod_spec:
        return json.dumps({"status": "error", "reason": "no production spec"})

    spec_json = json.loads(prod_spec)
    existing_skill_names = [s["name"] for s in spec_json.get("skills", [])]
    promoted_skills = []

    for row in validated:
        skill_name = row["SKILL_NAME"]
        try:
            rows = session.sql(f"""
                SELECT $1 AS content FROM {stage_base}/staging/{skill_name}/SKILL.md 
                (FILE_FORMAT => '{file_format}')
            """).collect()
            if not rows:
                continue
            skill_content = rows[0]["CONTENT"]
        except:
            continue

        # Copy skill to permanent path
        session.sql(f"TRUNCATE TABLE {staging_table}").collect()
        safe_content = skill_content.replace("'", "''")
        session.sql(f"INSERT INTO {staging_table} (CONTENT) VALUES ('{safe_content}')").collect()
        session.sql(f"""
            COPY INTO {stage_base}/skills/{skill_name}/SKILL.md
            FROM (SELECT CONTENT FROM {staging_table})
            FILE_FORMAT = (TYPE = CSV FIELD_OPTIONALLY_ENCLOSED_BY = NONE COMPRESSION = NONE)
            OVERWRITE = TRUE SINGLE = TRUE
        """).collect()

        # Add to agent spec if not already present
        if skill_name not in existing_skill_names:
            spec_json.setdefault("skills", []).append({
                "name": skill_name,
                "source": {"type": "STAGE", "path": f"{stage_base}/skills/{skill_name}/"}
            })
            existing_skill_names.append(skill_name)
        promoted_skills.append(skill_name)

    if not promoted_skills:
        return json.dumps({"status": "error", "reason": "no skills could be read from staging"})

    session.sql(f"ALTER STAGE {db}.{schema}.AGENT_SKILLS REFRESH").collect()

    # Create new committed version
    new_spec = json.dumps(spec_json)
    safe_spec = new_spec.replace("'", "''")
    try:
        session.sql(f"ALTER AGENT {agent_name} ADD LIVE VERSION FROM LAST").collect()
    except:
        pass

    skills_list = " ".join(promoted_skills[:3])
    session.sql(f"ALTER AGENT {agent_name} MODIFY LIVE VERSION SET SPECIFICATION = '{safe_spec}'").collect()
    session.sql(f"ALTER AGENT {agent_name} COMMIT COMMENT = 'Promoted {len(promoted_skills)} skill(s): {skills_list}'").collect()

    # Set PRODUCTION alias on new version
    versions_after = session.sql(f"SHOW VERSIONS IN AGENT {agent_name}").collect()
    new_version = None
    for v in sorted(versions_after, key=lambda x: x["created_on"], reverse=True):
        if v["name"] and "Promoted" in (v["comment"] or ""):
            new_version = v["name"]
            break

    if new_version:
        session.sql(f"ALTER AGENT {agent_name} MODIFY VERSION {new_version} SET ALIAS = PRODUCTION").collect()
        session.sql(f"ALTER AGENT {agent_name} SET DEFAULT_VERSION = '{new_version}'").collect()

    # Update registry status
    session.sql(f"""
        UPDATE {registry_table} SET STATUS = 'active', UPDATED_AT = CURRENT_TIMESTAMP()
        WHERE SKILL_NAME IN ({','.join([f"'{s}'" for s in promoted_skills])})
          AND AGENT_NAME = '{safe_agent}' AND STATUS = 'validated'
    """).collect()

    # Cleanup old validation versions
    for v in versions_after:
        if "Validation" in (v["comment"] or "") and v["name"] != new_version:
            try:
                session.sql(f"ALTER AGENT {agent_name} DROP VERSION {v['name']}").collect()
            except:
                pass

    return json.dumps({"status": "promoted", "new_version": new_version, "skills_promoted": promoted_skills})
