# SQL Query Guide

Use covering indexes so queries are answered from the index alone, without touching the table. Run EXPLAIN to inspect the query plan before tuning. Avoid SELECT * and name the columns you need. Use parameterised queries, e.g. cursor.execute("SELECT id FROM users WHERE email = ?", (email,)), to prevent injection. Consider partitioning for very large tables so scans touch fewer rows.

Common errors: ERROR 1062 duplicate entry; ERROR 1452 foreign key constraint failure; ORA-00942 table or view not found.

Version notes: PostgreSQL 14 adds parallel query improvements; MySQL 8.0 introduced hash joins; SQLite has no RIGHT JOIN.
