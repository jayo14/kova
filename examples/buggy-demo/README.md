# Buggy Demo Application

A lightweight demo web application with two intentional bugs planted for Kova verification:

1. **Planted Bug 1 (Network 500 Failure)**:
   - Route: `/contact`
   - UI reports success (`"Thank you! Your message has been sent."`), but background request `POST /api/contact` responds with HTTP 500.
   - **Kova Detection**: Fails with `"UI reported success but request POST /api/contact returned 500"`.

2. **Planted Bug 2 (Authentication Verification Failure)**:
   - Route: `/login`
   - Submitting the form fails authentication and redirects back to `/login?error=auth_failed`, keeping the password field on screen.
   - **Kova Detection**: Fails verification check `auth_verified` because the URL still contains `/login` and the password input is still visible.

## Running Locally

```bash
python examples/buggy-demo/server.py 8090
```

Runs on `http://127.0.0.1:8090`.
