# TindaTrack

An inventory, sales, and utang (credit) management system for sari-sari store owners.
IM2 project by Prince Kenn P. Sorita (CSIT327-G5).

**Stack:** Python · Django (full stack, Django templates) · PostgreSQL on Supabase

## Phase 1 — Account feature

| Requirement | Where it lives |
|---|---|
| Registration with validation (required fields, valid + unique email, matching passwords) | `accounts/forms.py` → `RegisterForm`, view `register` |
| Hashed passwords (Django auth, never plain text) | `User.set_password` via `UserCreationForm` / `UserManager` |
| Login with error on bad credentials | `accounts/views.py` → `LoginView`, `LoginForm` |
| Logout ends the session | `LogoutView` (POST) |
| Protected pages send logged-out users to login | `@login_required`, `role_required` in `accounts/decorators.py` |
| Two roles: Store owner (`OWNER`) and Store helper (`HELPER`) | `User.Role`, DB `CHECK` constraint `users_role_valid` |
| Role-based dashboards; typing the other role's URL gives a 403 | `/owner/dashboard/`, `/helper/dashboard/`, `role_required` |
| View and edit own profile (name, email, contact number, photo) | `/profile/`, `/profile/edit/` — both use `request.user`, never an id in the URL |
| Change password | `/profile/password/` |

The `users` table follows the SDD data dictionary: `email` (unique, used to log in),
`full_name`, `role` (`OWNER`/`HELPER`, default `HELPER`), `is_active`, `created_at`.

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
python manage.py createsuperuser     # optional: admin account (created as an OWNER)
python manage.py runserver
```

Open http://127.0.0.1:8000/ — you'll be sent to the login page.

## Tests

```bash
python manage.py test accounts
```

20 tests cover registration validation, password hashing, login/logout,
login-required redirects, role dashboards (including blocked cross-role URLs),
and profile editing. Django creates a temporary test database on your Postgres server.

## Notes

- `.env`, `venv/`, `__pycache__/` and `media/` are in `.gitignore`. Never commit `.env`.
- Uploaded profile photos are saved in `media/` and served by Django only while `DEBUG=True`.
