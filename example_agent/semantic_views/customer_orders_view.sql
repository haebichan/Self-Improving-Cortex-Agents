-- Semantic View: CUSTOMER_ORDERS_VIEW
-- This is the Cortex Analyst tool that the agent uses for data queries.
-- Deploy to: Your agent's schema

CREATE OR REPLACE SEMANTIC VIEW CUSTOMER_ORDERS_VIEW
    TABLES (
        <YOUR_DB>.<YOUR_AGENT_SCHEMA>.CUSTOMERS PRIMARY KEY (CUSTOMER_ID) 
            COMMENT='Customer accounts with tier and contact info',
        <YOUR_DB>.<YOUR_AGENT_SCHEMA>.ORDERS PRIMARY KEY (ORDER_ID) 
            COMMENT='Customer order history'
    )
    RELATIONSHIPS (
        ORDERS_TO_CUSTOMERS AS ORDERS(CUSTOMER_ID) REFERENCES CUSTOMERS(CUSTOMER_ID)
    )
    FACTS (
        CUSTOMERS.CUSTOMER_ID_FACT AS customers.customer_id,
        ORDERS.ORDER_AMOUNT AS orders.amount
    )
    DIMENSIONS (
        CUSTOMERS.CUSTOMER_NAME AS customers.name COMMENT='Customer full name',
        CUSTOMERS.CUSTOMER_EMAIL AS customers.email COMMENT='Customer email address',
        CUSTOMERS.TIER AS customers.current_tier COMMENT='Current loyalty tier: GOLD, SILVER, or BRONZE',
        CUSTOMERS.SIGNUP_DATE_DIM AS customers.signup_date COMMENT='Date customer signed up',
        ORDERS.ORDER_DATE AS orders.order_date COMMENT='Date order was placed',
        ORDERS.ORDER_STATUS AS orders.status COMMENT='Order status: completed, pending, or cancelled'
    )
    METRICS (
        ORDERS.TOTAL_REVENUE AS SUM(orders.amount) COMMENT='Total order revenue',
        ORDERS.ORDER_COUNT AS COUNT(orders.order_id) COMMENT='Number of orders',
        ORDERS.AVG_ORDER_VALUE AS AVG(orders.amount) COMMENT='Average order amount'
    )
    COMMENT='Customer accounts and order history for credit and tier management';
