"""
CREDIT_CHECK_API: Simulates an external credit scoring service.
The key "quirk" that drives the self-learning demo: it only accepts 
the count of COMPLETED orders, not total orders. This undocumented
requirement causes the agent to fail on first attempt and retry.

Deploy to: Your agent's schema
Signature: CREDIT_CHECK_API(CUSTOMER_ID VARCHAR, ORDER_COUNT VARCHAR) RETURNS VARCHAR
"""

def run(session, customer_id, order_count):
    import json
    
    try:
        cid = int(customer_id)
    except (ValueError, TypeError):
        return json.dumps({"status": "error", "message": "Request failed: invalid parameters"})
    
    try:
        oc = int(order_count)
    except (ValueError, TypeError):
        return json.dumps({"status": "error", "message": "Request failed: missing required context"})
    
    rows = session.sql(f"SELECT customer_id, name, current_tier FROM <YOUR_DB>.<YOUR_AGENT_SCHEMA>.CUSTOMERS WHERE customer_id = {cid}").collect()
    if not rows:
        return json.dumps({"status": "error", "message": "Request failed: resource not found"})
    
    # Only counts COMPLETED orders - the undocumented quirk
    completed_rows = session.sql(f"""
        SELECT COUNT(*) AS cnt FROM <YOUR_DB>.<YOUR_AGENT_SCHEMA>.ORDERS 
        WHERE customer_id = {cid} AND status = 'completed'
    """).collect()
    actual_completed = completed_rows[0]['CNT'] if completed_rows else 0
    
    if oc != actual_completed:
        return json.dumps({"status": "error", "message": f"Request failed: order_count verification failed. Expected count of verified/completed orders only, got {oc}"})
    
    name = rows[0]['NAME']
    tier = rows[0]['CURRENT_TIER']
    
    base_score = 500
    if tier == 'GOLD':
        base_score = 750
    elif tier == 'SILVER':
        base_score = 650
    
    score = min(850, base_score + (oc * 15))
    
    if score >= 750:
        risk = "LOW"
        limit = 50000
    elif score >= 600:
        risk = "MEDIUM"
        limit = 25000
    else:
        risk = "HIGH"
        limit = 5000
    
    return json.dumps({
        "status": "success",
        "customer_id": cid,
        "customer_name": name,
        "credit_score": score,
        "risk_level": risk,
        "credit_limit": limit
    })
