# TindaTrack

An inventory, sales, and utang (credit) management system for sari-sari store owners.
IM2 project by Prince Kenn P. Sorita (CSIT327-G5).

**Stack:** Python · Django 5.2 (full stack, Django templates) · PostgreSQL on Supabase

## Core feature (PD2): Inventory — products and stock in/out

TindaTrack replaces the store's notebook. The first thing it has to do is know
what the store sells and how many of each item are on the shelf. This vertical slice covers
SDD features **F-02 Product and Category Management**, **F-03 Restock and Stock Adjustment**,
and **F-04 Low-Stock Alerts**.

### The flow
1. The owner adds **categories** (Canned goods, Drinks, Rice…).
2. The owner adds **products** with a unique code, unit, cost price, selling price and reorder level.
   New products start with 0 in stock.
3. The owner or a helper records a **stock change**:
   - **Restock**: a delivery arrived. Always adds units.
   - **Adjustment**: damaged, expired or miscounted items. Adds or removes units, and needs a reason.
4. The product's stock updates right away, and the change is saved in the **stock log** with the user who made it.
5. Products at or below their reorder level are flagged **Low** (or **Out** at 0) on the product list
   and both dashboards.

### Who can do what
| | Store owner | Store helper |
|---|---|---|
| View products and categories | ✓ | ✓ (cost price hidden) |
| Add, edit, delete categories | ✓ | — |
| Add, edit (incl. prices), deactivate, delete products | ✓ | — |
| Record restocks and adjustments | ✓ | ✓ |
| See the stock log | Everyone's entries | Only their own |
| Edit or delete a stock entry | Any entry | Only their own (others' return 404) |

### CRUD
| | Create | Read | Update | Delete |
|---|---|---|---|---|
| Category | ✓ | ✓ | ✓ | ✓ (blocked if it has products — BR-04) |
| Product | ✓ | ✓ list, search, filter, detail | ✓ | ✓ if no stock history; otherwise deactivate (BR-08) |
| Stock movement | ✓ | ✓ log with filters | ✓ quantity and reason; stock follows the difference | ✓ undoes the change, blocked if stock would go below 0 |

### Business rules enforced (from the SDD)
- Unique category names and product codes (BR-04, BR-05) — form check + `UNIQUE` in PostgreSQL.
- Selling price > 0, cost price ≥ 0, stock ≥ 0, reorder level ≥ 0 (BR-06, BR-07) — form check + `CHECK` constraints.
- Categories with products and products with history can't be deleted (BR-04, BR-08) — `ON DELETE RESTRICT` (Django `PROTECT`).
- Movement type is `RESTOCK` or `ADJUSTMENT`; quantity is never 0; restocks are positive (BR-10, BR-11) — form check + `CHECK` constraints.
- An adjustment can't push stock below zero (BR-12) — checked in the form and again in `inventory/services.py`,
  which locks the product row (`SELECT … FOR UPDATE`) inside a transaction.
- Only owners change prices or remove products (BR-03) — `role_required("OWNER")` on those views.

### Database tables (PostgreSQL)
`users` (PD1), `categories`, `products`, `stock_movements`.
`products.category_id → categories`, `stock_movements.product_id → products`,
`stock_movements.user_id → users`. Categories and products also store `created_by → users`.

## Standard features (PD1)
Registration (validated, hashed passwords), login/logout, protected pages, role-based dashboards
(Owner and Helper, cross-role URLs return 403), and profile view/edit with photo.

## Setup

```bash
git clone <this-repo-url>
cd <repo-folder>
python -m venv venv
# Windows: venv\Scripts\activate     macOS/Linux: source venv/bin/activate
pip install -r requirements.txt
copy .env.example .env      # macOS/Linux: cp .env.example .env
```

Edit `.env`:
1. **SECRET_KEY** — generate one:
   `python -c "from django.core.management.utils import get_random_secret_key as g; print(g())"`
2. **DATABASE_URL** — in Supabase open your project, click **Connect**, and copy the
   **Session pooler** URI. Replace `[YOUR-PASSWORD]` with your database password.

Then:

```bash
python manage.py migrate
python manage.py seed_demo           # demo accounts + sample products and stock
python manage.py runserver
```

Open http://127.0.0.1:8000/ and log in.

New sign-ups: the **first** account registered becomes the store owner; everyone after joins as a
helper. Owners change roles on the **Team** page.

### Test accounts (created by `seed_demo`)
| Role | Email | Password |
|---|---|---|
| Store owner | owner@tindatrack.test | TindaDemo2026! |
| Store helper | helper@tindatrack.test | TindaDemo2026! |

## Running the tests

The tests use your PostgreSQL / Supabase connection from `.env`. Django creates a separate
temporary database named `test_<your database>` and deletes it afterwards, so your real data is not touched.

```bash
# with your virtual environment active, from the folder that has manage.py
python manage.py test                      # everything (85 tests)
python manage.py test accounts             # account feature only
python manage.py test inventory            # core feature only
python manage.py test inventory.tests.test_hardening   # PD3 hardening tests only
python manage.py test -v 2                 # show each test's name
```

A passing run ends with `OK`. Expected warnings (403, 404, the simulated 500) are hidden while tests run.

> **Supabase note:** the database user needs permission to create a database for the test run.
> If you see `permission denied to create database`, run the tests against a local PostgreSQL
> by pointing `DATABASE_URL` in `.env` at it (and `DB_SSL_REQUIRE=False`).

| Test file | What it covers |
|---|---|
| `accounts/tests.py` | Registration validation, hashed passwords, login/logout, role dashboards, profile, helper-only sign-up, Team page, protected photo serving |
| `inventory/tests/test_catalog.py` | Category and product CRUD, validation, owner-only actions, search and filters |
| `inventory/tests/test_stock.py` | Restocks, adjustments, stock arithmetic, own-records-only rules, pagination |
| `inventory/tests/test_hardening.py` | Valid and invalid input, login required on every page, blocked access to other users' records, POST-only actions, CSRF, custom 404/500 pages, database constraints, query counts |

## Hardening (PD3)
- **Validation:** every form validates on the server; business rules (no negative stock, restocks must add,
  adjustments need a reason, unique names and codes, prices > 0) are also PostgreSQL `CHECK`/`UNIQUE` constraints.
- **Errors:** custom 400, 403, 404, 500 and "form expired" (CSRF) pages. `DEBUG` comes from `.env` and defaults to `False`.
- **Access:** every view requires login; roles are checked in the view (`role_required`), not only in templates.
  Helpers asking for another user's stock entry get a 404.
- **Requests:** read-only pages accept GET only; deletes and role changes need POST with a CSRF token and
  show a confirmation page first. Successful POSTs redirect, and the submit button is disabled after one click.
- **Data integrity:** all foreign keys use `PROTECT` so history is never lost; stock changes run inside
  `transaction.atomic()` with the product row locked; duplicate-save races become form errors, not crashes.
- **Uploads:** profile photos must be real JPG/PNG/WebP images up to 2 MB and are served only to logged-in users.

## Project layout
```
accounts/    users, roles, login, dashboards, profile (PD1)
inventory/   categories, products, stock movements (PD2)
  services.py   all stock changes go through here
  management/commands/seed_demo.py
templates/   Django templates
static/css/  styles
docs/        PD completion reports
```

## Branching
`main` (stable) ← `develop` (integration) ← `feature/<name>`. Merged feature branches are kept.

## Notes
- `.env`, `venv/`, `__pycache__/` and `media/` are in `.gitignore`. Never commit `.env`.
- Stock movements are read-only in the Django admin so stock can't drift from the log.
