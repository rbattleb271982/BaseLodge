# BaseLodge — Capacitor Navigation Notes

## Critical rule

Never include route paths inside Capacitor server.url.

Correct:

server: {
  url: "https://app.baselodgeapp.com"
}

Incorrect:

server: {
  url: "https://app.baselodgeapp.com/home"
}

## Why

iOS WKWebView / Capacitor navigation can treat path-specific server URLs as outside the native app shell.

Example:

App shell starts:

https://app.baselodgeapp.com/home

User navigates:

https://app.baselodgeapp.com/my-trips

iOS may interpret this as outside the shell and hand navigation to browser-like behavior.

Observed symptoms:

- white flash
- browser/Safari controls appearing
- app shell disappearing
- app behaving like mobile web
- Android unaffected

Android WebView may appear fine because Android is more permissive.

## Required configuration

Always include:

allowNavigation: [
  "https://app.baselodgeapp.com"
]

in Capacitor config.

## Release reminder

Whenever Capacitor config changes:

1. Replit publish/deploy
2. GitHub push
3. git pull origin main
4. npx cap sync ios
5. npx cap sync android
6. Xcode archive/TestFlight

## Related issue history

Original issue:
Home → Trips caused iOS app-shell escape.

Resolution:
Changed server.url to root domain and added allowNavigation.

Do not delete this note.
