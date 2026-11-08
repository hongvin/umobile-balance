# Recovered MyUMobile request contract

This is an unofficial private app API, recovered from MyUMobile 4.0.2 and verified with a U Home 5G account. It can change. Login uses normal subscriber credentials and device approval; no app-private session extraction or TLS interception is required.

Base: `https://api-myumobileapp.u.com.my/mobile`.

| Method | Path | Purpose |
| --- | --- | --- |
| POST | `/auth/v1/auth/login/email` | Email/password login with client device UUID and nested deviceInfo |
| POST | `/auth/v1/auth/refresh` | Rotate an existing refresh token |
| GET | `/user/v1/balance` | Read quota using Bearer access token |
| POST | `/auth/v1/device/request-confirm` | Request primary-phone approval (or native Mac TAC) |
| POST | `/auth/v1/device/poll-result` | Check a pending approval |
| POST | `/auth/v1/device/complete` | Complete an approved login |
| POST | `/auth/v1/device/approve-by-tac` | Native Mac TAC alternative, mock-tested only |

Device metadata uses the recovered `IOS` protocol value and app version `4.0.2`; OS/model metadata describes the actual client. Do not copy an existing official-app UUID or token. This project creates its own persistent UUID.

An HTTP 422 `LOGIN_BIND_DEVICE_VERIFY` challenge contains a temporary `secretToken`. Request-confirm uses that secret as Bearer authentication and flat metadata plus `deviceId` and `type: PRIMARY`. Poll/complete use `deviceId` and `sessionId`. `approved` must be boolean true before completing login. The returned `sseToken` is not an API access token. Temporary challenge data remains in memory.

Refresh sends only `refreshToken` in its JSON body. A rotated token is saved before attempting the next balance request. A balance HTTP 401 permits at most one refresh/retry; rejected refresh requires a new sign-in. No unlimited retry loop or automatic registered-device removal is used.

Balance rows contain `type`, `category`, `consumed`, `originalBalance`, `balance`, names and expiry. DATA quantities are bytes. The MyUMobile display convention is `bytes / 1,073,741,824`, labeled GB. The Python/ESP32 client chooses a DATA row with category PLAN when present; the native macOS client preserves multiple pools for selection.

Live verification covered email login, primary-phone approval, token rotation and balance on Apple silicon and the Feather ESP32-S3 TFT. Automated tests use synthetic fixtures. Windows/Linux live account authorization, non-home-broadband plans and other boards remain unverified. No actual API token or subscriber response belongs in this repository.
