# API examples

Captured from `docker compose up --build` (memory provider, demo members seeded at start). Subject ids are random per run. Sign-in tokens are left out on purpose.

## Readiness probe

```bash
curl -s http://127.0.0.1:8550/healthz
```

```json
{"status": "ok", "provider": "memory"}
```

## Look up a seeded member

```bash
curl -s -X POST http://127.0.0.1:8550/graphql -H 'Content-Type: application/json' \
  -d '{"query": "{ getUser(username: \"rhiannon.pike\") { username email confirmed goalType goalTarget goalTimeframe sessionsPerWeek } }"}'
```

```json
{
  "data": {
    "getUser": {
      "username": "rhiannon.pike",
      "email": "rhiannon.pike@example.com",
      "confirmed": true,
      "goalType": "fat_loss",
      "goalTarget": "6 kg",
      "goalTimeframe": "June",
      "sessionsPerWeek": "4"
    }
  }
}
```

## Preview how a goal will be structured

```bash
curl -s -X POST http://127.0.0.1:8550/graphql -H 'Content-Type: application/json' \
  -d '{"query": "query ($t: String!) { previewGoal(text: $t) { goalType target timeframe sessionsPerWeek source } }", "variables": {"t": "Get my deadlift stronger - 140 kg within 4 months, training four times a week"}}'
```

```json
{
  "data": {
    "previewGoal": {
      "goalType": "strength",
      "target": "140 kg",
      "timeframe": "4 months",
      "sessionsPerWeek": 4,
      "source": "rules"
    }
  }
}
```

## Sign up with a free-text goal

```bash
curl -s -X POST http://127.0.0.1:8550/graphql -H 'Content-Type: application/json' \
  -d '{"query": "mutation ($u: String!, $n: String!, $p: String!, $e: String!, $g: String) { signup(username: $u, name: $n, password: $p, email: $e, goal: $g) { user { username confirmed goalType } goal { goalType target timeframe sessionsPerWeek source } } }", "variables": {"u": "amelia.novak", "n": "Amelia Novak", "p": "Str0ng-Demo-Pass!", "e": "amelia.novak@example.com", "g": "Run a half marathon in 12 weeks, three sessions a week"}}'
```

```json
{
  "data": {
    "signup": {
      "user": {
        "username": "amelia.novak",
        "confirmed": false,
        "goalType": "endurance"
      },
      "goal": {
        "goalType": "endurance",
        "target": null,
        "timeframe": "12 weeks",
        "sessionsPerWeek": 3,
        "source": "rules"
      }
    }
  }
}
```

## Sign-in before confirmation

```bash
curl -s -X POST http://127.0.0.1:8550/graphql -H 'Content-Type: application/json' \
  -d '{"query": "mutation { signin(username: \"amelia.novak\", password: \"Str0ng-Demo-Pass!\") { expiresIn } }"}'
```

```json
{
  "errors": [
    {
      "message": "This account has not been confirmed yet. Check your email for the code.",
      "locations": [
        {
          "line": 1,
          "column": 12
        }
      ],
      "path": [
        "signin"
      ],
      "extensions": {
        "code": "USER_NOT_CONFIRMED"
      }
    }
  ],
  "data": {
    "signin": null
  }
}
```

## Confirm with the OTP (always 123456 on the memory provider)

```bash
curl -s -X POST http://127.0.0.1:8550/graphql -H 'Content-Type: application/json' \
  -d '{"query": "mutation { confirmUser(username: \"amelia.novak\", otp: \"123456\") { success user { username confirmed } } }"}'
```

```json
{
  "data": {
    "confirmUser": {
      "success": true,
      "user": {
        "username": "amelia.novak",
        "confirmed": true
      }
    }
  }
}
```

## Sign in (token values left out of this transcript)

```bash
curl -s -X POST http://127.0.0.1:8550/graphql -H 'Content-Type: application/json' \
  -d '{"query": "mutation { signin(username: \"amelia.novak\", password: \"Str0ng-Demo-Pass!\") { expiresIn user { username email goalType sessionsPerWeek } } }"}'
```

```json
{
  "data": {
    "signin": {
      "expiresIn": 3600,
      "user": {
        "username": "amelia.novak",
        "email": "amelia.novak@example.com",
        "goalType": "endurance",
        "sessionsPerWeek": "3"
      }
    }
  }
}
```

## A wrong password

```bash
curl -s -X POST http://127.0.0.1:8550/graphql -H 'Content-Type: application/json' \
  -d '{"query": "mutation { signin(username: \"amelia.novak\", password: \"not-her-password\") { expiresIn } }"}'
```

```json
{
  "errors": [
    {
      "message": "Username or password is incorrect.",
      "locations": [
        {
          "line": 1,
          "column": 12
        }
      ],
      "path": [
        "signin"
      ],
      "extensions": {
        "code": "INVALID_CREDENTIALS"
      }
    }
  ],
  "data": {
    "signin": null
  }
}
```

## An unknown username returns the identical error

```bash
curl -s -X POST http://127.0.0.1:8550/graphql -H 'Content-Type: application/json' \
  -d '{"query": "mutation { signin(username: \"nobody.here\", password: \"not-her-password\") { expiresIn } }"}'
```

```json
{
  "errors": [
    {
      "message": "Username or password is incorrect.",
      "locations": [
        {
          "line": 1,
          "column": 12
        }
      ],
      "path": [
        "signin"
      ],
      "extensions": {
        "code": "INVALID_CREDENTIALS"
      }
    }
  ],
  "data": {
    "signin": null
  }
}
```

## A blank required field

```bash
curl -s -X POST http://127.0.0.1:8550/graphql -H 'Content-Type: application/json' \
  -d '{"query": "mutation { signup(username: \" \", name: \"X\", password: \"Str0ng-Demo-Pass!\", email: \"x@example.com\") { user { username } } }"}'
```

```json
{
  "errors": [
    {
      "message": "username is required.",
      "locations": [
        {
          "line": 1,
          "column": 12
        }
      ],
      "path": [
        "signup"
      ],
      "extensions": {
        "code": "INVALID_INPUT"
      }
    }
  ],
  "data": {
    "signup": null
  }
}
```
