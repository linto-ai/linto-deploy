# Studio Feature Flags

Environment variables that **enable features** (excluding server settings)

## Linked Front / API

| Feature                                            | API                             | Frontend                                | Default |
| -------------------------------------------------- | ------------------------------- | --------------------------------------- | ------- |
| Speaker identification (voiceprints / diarization) | `ENABLE_SPEAKER_IDENTIFICATION` | `VUE_APP_ENABLE_SPEAKER_IDENTIFICATION` | `false` |
| Disable account creation                           | `DISABLE_USER_CREATION`         | `VUE_APP_DISABLE_USER_CREATION`         | `false` |
| Disable user invitation                            | `DISABLE_USER_INVITATION`       | `VUE_APP_DISABLE_USER_INVITATION`       | `false` |

## API only

| Variable                                | Feature                                | Default |
| --------------------------------------- | -------------------------------------- | ------- |
| `LOCAL_AUTH_ENABLED`                    | Local username/password auth           | `true`  |
| `OIDC_GOOGLE_ENABLED`                   | Google OAuth login                     | `false` |
| `OIDC_GITHUB_ENABLED`                   | GitHub OAuth login                     | `false` |
| `CORS_ENABLED`                          | CORS (cross-origin API access)         | `false` |
| `DISABLE_DEFAULT_ORGANIZATION_CREATION` | Disable auto-creation of a default org | `false` |

## Frontend only

| Variable                        | Feature                                            | Default |
| ------------------------------- | -------------------------------------------------- | ------- |
| `VUE_APP_ENABLE_SESSION`        | Live session management (creation, quick sessions) | `false` |
| `VUE_APP_ENABLE_WATERMARK`      | Watermark during live transcription                | `false` |
| `VUE_APP_ENABLE_TTS`            | Text-to-speech on transcription results            | `false` |
| `VUE_APP_ENABLE_SECURITY_LEVEL` | Security level selector (creation forms)           | `false` |
| `VUE_APP_SHOW_LOGIN_FOOTER`     | Footer on the login page                           | `false` |
