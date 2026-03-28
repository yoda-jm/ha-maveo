# Authentication

**Status: working**

Maveo uses AWS Cognito for identity and then exchanges the resulting JWT for
temporary AWS credentials via the Cognito Identity Pool.  Those AWS credentials
are what gets used for every subsequent API and IoT call.

---

## Step 1 — Cognito USER_PASSWORD_AUTH

```
POST https://cognito-idp.<region>.amazonaws.com/
X-Amz-Target: AWSCognitoIdentityProviderService.InitiateAuth
Content-Type: application/x-amz-json-1.1

{
  "ClientId": "<client_id>",
  "AuthFlow": "USER_PASSWORD_AUTH",
  "AuthParameters": {
    "USERNAME": "<email>",
    "PASSWORD": "<password>"
  }
}
```

Response `AuthenticationResult`:
| Field | Use |
|---|---|
| `IdToken` | JWT; passed to Identity Pool |
| `AccessToken` | Cognito user operations |
| `RefreshToken` | Long-lived; can refresh the session |

The `IdToken` is a standard JWT.  Decoded payload (EU example):
```json
{
  "iss": "https://cognito-idp.eu-central-1.amazonaws.com/eu-central-1_ozbW8rTAj",
  "aud": "34eruqhvvnniig5bccrre6s0ck",
  "email": "user@example.com"
}
```

---

## Step 2 — Cognito Identity Pool → identity_id + AWS credentials

```python
# botocore / boto3 calls (no raw HTTP needed)

cognito_identity.get_id(
    IdentityPoolId="<identity_pool_id>",
    Logins={
        "cognito-idp.<region>.amazonaws.com/<user_pool_id>": id_token
    }
)
# → {"IdentityId": "eu-central-1:90fdae04-5dd7-c740-f1d3-46a0d9153738"}

cognito_identity.get_credentials_for_identity(
    IdentityId=identity_id,
    Logins={...same logins dict...}
)
# → {"Credentials": {"AccessKeyId", "SecretKey", "SessionToken", "Expiration"}}
```

The `identity_id` (e.g. `eu-central-1:90fdae04-…`) is used as the `owner`
field in REST API calls.

The temporary AWS credentials (`AccessKeyId` / `SecretKey` / `SessionToken`)
are used for SigV4-signed IoT WebSocket connections.

---

## Regional constants (EU / US)

| Parameter | EU | US |
|---|---|---|
| `aws_region` | `eu-central-1` | `us-west-2` |
| `client_id` | `34eruqhvvnniig5bccrre6s0ck` | `6uf5ra21th645p7c2o6ih65pit` |
| `user_pool_id` | `eu-central-1_ozbW8rTAj` | `us-west-2_6Ni2Wq0tP` |
| `identity_pool_id` | `eu-central-1:b3ebe605-53c9-463e-8738-70ae01b042ee` | `us-west-2:a982cd04-863c-4fd4-8397-47deb11c8ec0` |
| REST base URL | `https://eu-central-1.api-prod.marantec-cloud.de` | `https://us-west-2.api-prod.marantec-cloud.de` |
| IoT hostname | `eu-central-1.iot-prod.marantec-cloud.de` | `us-west-2.iot-prod.marantec-cloud.de` |

All constants were extracted from the decompiled native library
`libmaveo-app_armeabi-v7a.so` (app version 2.6.0).

---

## Token lifetime

AWS temporary credentials from the Identity Pool typically expire after 1 hour
(the `Expiration` field in the response).  The app must re-authenticate before
that point.  The `RefreshToken` from step 1 can be used with
`InitiateAuth` `REFRESH_TOKEN_AUTH` flow to get fresh Cognito tokens without
re-entering the password.
