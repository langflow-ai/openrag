# CS4750 Final Report - JobTracker Database System

**Group Members:** Kaden Nguyen, Leo Lee, Jason Dong, Nathan Suh
**Database Design & Architecture Overview:**
The JobTracker application is a full-stack job application lifecycle tracking portal. The backend is designed around a 3NF normalized MySQL database with strict foreign key constraints and transactional integrity.

## Table Schema Definitions
- `applications(application_id, role_title, status, company_id, city_id, cycle_id, created_at)`
  - FK: `company_id` references `companies(company_id)`
  - FK: `city_id` references `cities(city_id)`
- `application_documents(application_id, doc_id)`
- `users(user_id, email, password, first_name, last_name, created_at)`

## Application Security & Authentication
Passwords are never stored in plaintext format. On user registration, the system invokes PHP's native `password_hash()` implementing strong salted bcrypt key derivation functions. During authentication, `password_verify()` ensures constant-time verification.

Database queries use prepared statements with `bind_param` to completely eliminate SQL injection attack vectors. Session state is managed via secure cookie parameters with `HttpOnly` and `SameSite` flags.

## Stored Procedures and Integrity Constraints
The database incorporates an explicit check constraint `chk_application_status` enforcing that status values only contain:
- `Draft`
- `Submitted`
- `Interview`
- `Offer`
- `Rejected`
- `Withdrawn`

All status modifications are mediated through the `update_application_status` stored procedure, guaranteeing enterprise-level business logic consistency.
