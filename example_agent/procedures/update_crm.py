"""
UPDATE_CRM: Simulates updating a customer's tier in an external CRM system.
Requires tier to be EXACTLY uppercase (GOLD, SILVER, BRONZE).

Deploy to: Your agent's schema
Signature: UPDATE_CRM(CUSTOMER_ID VARCHAR, CREDIT_SCORE VARCHAR, NEW_TIER VARCHAR) RETURNS VARCHAR
"""

def run(session, customer_id, credit_score, new_tier):
    import json
    
    try:
        cid = int(customer_id)
    except (ValueError, TypeError):
        return json.dumps({"status": "error", "message": "Update failed: invalid request format"})
    
    try:
        score = int(credit_score)
    except (ValueError, TypeError):
        return json.dumps({"status": "error", "message": "Update failed: incomplete data - authorization required"})
    
    if score < 300 or score > 850:
        return json.dumps({"status": "error", "message": "Update failed: validation error"})
    
    valid_tiers = ["GOLD", "SILVER", "BRONZE"]
    if new_tier not in valid_tiers:
        return json.dumps({"status": "error", "message": "Update failed: invalid tier value - check format"})
    
    rows = session.sql(f"SELECT current_tier FROM <YOUR_DB>.<YOUR_AGENT_SCHEMA>.CUSTOMERS WHERE customer_id = {cid}").collect()
    if not rows:
        return json.dumps({"status": "error", "message": "Update failed: resource not found"})
    
    old_tier = rows[0]['CURRENT_TIER']
    
    session.sql(f"UPDATE <YOUR_DB>.<YOUR_AGENT_SCHEMA>.CUSTOMERS SET current_tier = '{new_tier}' WHERE customer_id = {cid}").collect()
    
    return json.dumps({
        "status": "success",
        "customer_id": cid,
        "previous_tier": old_tier,
        "new_tier": new_tier,
        "credit_score_used": score,
        "message": f"Customer tier updated from {old_tier} to {new_tier}"
    })
